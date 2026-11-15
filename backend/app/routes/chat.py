import asyncio
import logging
import re
import datetime
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.db import get_db
from app.database.models import MemoryConversation, MemoryMessage, Meeting, Trace, User
from app.dependencies import get_current_user, meeting_visibility_clause, user_can_read_meeting, visible_meeting_ids
from app.rate_limit import limiter
from app.services import memory_retriever, transcript_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])
MAX_SCOPE_MEETINGS = 10


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    meeting_id: str | None = None
    # Ask across an explicit set of meetings instead of all company memory.
    meeting_ids: list[str] = Field(default_factory=list, max_length=MAX_SCOPE_MEETINGS)
    conversation_id: str | None = None
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=12)


MAX_TITLE_LENGTH = 60
HISTORY_MESSAGES = 6


async def _get_owned_conversation(
    conversation_id: uuid.UUID, user: User, db: AsyncSession
) -> MemoryConversation:
    result = await db.execute(
        select(MemoryConversation)
        .options(selectinload(MemoryConversation.messages))
        .where(MemoryConversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


async def _log_chat_trace(db: AsyncSession, user: User, label: str, usage: dict) -> None:
    db.add(
        Trace(
            user_id=user.id,
            meeting_id=None,
            meeting_title=label,
            ai_input_tokens=usage["input_tokens"] + usage["cache_tokens_read"],
            ai_output_tokens=usage["output_tokens"],
            ai_cache_hits=usage["cache_tokens_read"],
            status="success",
        )
    )
    await db.commit()


async def _meeting_payload(db: AsyncSession, meeting: Meeting) -> dict:
    """What grounded answers read for one meeting: notes, items and lines."""
    segments = await transcript_service.ensure_segments(db, meeting)
    return {
        "id": str(meeting.id),
        "title": meeting.title,
        "date": meeting.date.isoformat(),
        "summary": meeting.summary,
        "transcript": meeting.transcript,
        "segments": [
            {
                "id": str(segment.id),
                "seq": segment.seq,
                "start_ms": segment.start_ms,
                "speaker": transcript_service.display_label(segment),
                "text": segment.text,
            }
            for segment in segments
        ],
        "decisions": [
            {"decision": d.decision, "reason": d.reason}
            for d in meeting.decisions
            if d.deleted_at is None
        ],
        "tasks": [
            {"description": t.description, "owner": t.owner}
            for t in meeting.tasks
            if t.deleted_at is None
        ],
    }


async def _recent_readable_meetings(db: AsyncSession, user: User, query: str = "") -> list[Meeting]:
    """The newest meetings this person can read, for answering company-wide
    questions straight from the records when vector search can't."""
    # Rank before limiting: an older ADR must remain findable without vectors.
    # Keep the same access rules and ten-meeting generation budget.
    stop = {"why", "did", "the", "for", "and", "what", "who", "how", "was", "were", "our", "does", "that", "this", "from", "choose", "about", "with", "have", "has", "are", "can", "you"}
    terms = list(dict.fromkeys(word for word in re.findall(r"[^\W_]+", query.lower()) if len(word) > 2 and word not in stop))[:12]
    score = sum((case((Meeting.title.ilike(f"%{term}%"), 4), else_=0) + case((func.coalesce(Meeting.summary, "").ilike(f"%{term}%"), 2), else_=0) + case((func.coalesce(Meeting.transcript, "").ilike(f"%{term}%"), 1), else_=0) for term in terms), 0)
    ordering = [score.desc(), Meeting.date.desc()] if terms else [Meeting.date.desc()]
    result = await db.execute(
        select(Meeting)
        .options(selectinload(Meeting.tasks), selectinload(Meeting.decisions))
        .where(Meeting.id.in_(visible_meeting_ids(user)), Meeting.confidential.is_(False))
        .order_by(*ordering)
        .limit(MAX_SCOPE_MEETINGS)
    )
    return list(result.scalars().all())


@router.post("")
@limiter.limit("20/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Question cannot be empty")
    if body.conversation_id:
        try:
            conversation_uuid = uuid.UUID(body.conversation_id)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="Invalid conversation ID") from error
        conversation = await _get_owned_conversation(conversation_uuid, user, db)
        history = [
            {"role": message.role, "content": message.content}
            for message in conversation.messages[-HISTORY_MESSAGES:]
        ]
        if conversation.scope_meeting_ids:
            requested_ids = list(conversation.scope_meeting_ids)
        elif conversation.meeting_id:
            requested_ids = [str(conversation.meeting_id)]
        else:
            requested_ids = []
    else:
        history = [message.model_dump() for message in body.history[-HISTORY_MESSAGES:]]
        requested_ids = list(dict.fromkeys(([body.meeting_id] if body.meeting_id else []) + body.meeting_ids))
        title = query if len(query) <= MAX_TITLE_LENGTH else query[: MAX_TITLE_LENGTH - 1] + "…"
        conversation = MemoryConversation(user_id=user.id, title=title)
        db.add(conversation)
        await db.flush()
        if len(requested_ids) > MAX_SCOPE_MEETINGS:
            raise HTTPException(status_code=422, detail=f"Select at most {MAX_SCOPE_MEETINGS} meetings")

    if requested_ids:
        try:
            meeting_uuids = [uuid.UUID(value) for value in requested_ids]
        except ValueError as error:
            raise HTTPException(status_code=422, detail="Invalid meeting ID") from error
        result = await db.execute(
            select(Meeting)
            .options(selectinload(Meeting.tasks), selectinload(Meeting.decisions))
            .where(Meeting.id.in_(meeting_uuids), Meeting.deleted_at.is_(None))
            .order_by(Meeting.date)
        )
        # Access is rechecked on every question — a stored conversation scope
        # is never trusted, so revoked or deleted meetings drop out at once.
        meetings = [m for m in result.scalars().all() if await user_can_read_meeting(db, user, m.id)]
        if len(meetings) != len(meeting_uuids) and not body.conversation_id:
            raise HTTPException(status_code=404, detail="Meeting not found")
        if not meetings:
            raise HTTPException(status_code=404, detail="These meetings are no longer available to you")

        meeting_data = [await _meeting_payload(db, meeting) for meeting in meetings]
        if len(meeting_data) == 1:
            answer = await asyncio.to_thread(
                memory_retriever.answer_query_for_meeting, query, meeting_data[0], history
            )
            label = f"Chat — {meetings[0].title}"
        else:
            answer = await asyncio.to_thread(
                memory_retriever.answer_query_for_meetings, query, meeting_data, history
            )
            label = f"Chat — {len(meetings)} meetings"
        if not body.conversation_id:
            if len(meetings) == 1:
                conversation.meeting_id = meetings[0].id
            else:
                conversation.scope_meeting_ids = [str(m.id) for m in meetings]
    else:
        visibility = meeting_visibility_clause(user)
        if visibility is None:
            meeting_ids = None
        else:
            meeting_ids = [str(mid) for mid in (await db.execute(visible_meeting_ids(user))).scalars().all()]
        try:
            answer = await asyncio.to_thread(memory_retriever.answer_query, query, meeting_ids, 8, history)
        except Exception:
            logger.warning("Vector search unavailable; answering from recent meetings", exc_info=True)
            answer = None
        label = "Chat — company memory"
        # Without a reachable vector store, or for meetings that were never
        # indexed, answer from the newest readable meetings' own records.
        if answer is None or not answer.get("sources"):
            recent = await _recent_readable_meetings(db, user, query)
            if recent:
                if answer is not None:
                    answer.pop("usage", None)
                answer = await asyncio.to_thread(
                    memory_retriever.answer_query_for_meetings,
                    query,
                    [await _meeting_payload(db, meeting) for meeting in recent],
                    history,
                )
            elif answer is None:
                raise HTTPException(status_code=503, detail="Company memory is unavailable right now. Try again shortly.")

    db.add(MemoryMessage(conversation_id=conversation.id, role="user", content=query))
    db.add(
        MemoryMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=answer["answer"],
            sources=answer["sources"],
        )
    )
    conversation.updated_at = datetime.datetime.now(datetime.UTC)
    usage = answer.pop("usage")
    db.add(
        Trace(
            user_id=user.id,
            meeting_id=None,
            meeting_title=label,
            ai_input_tokens=usage["input_tokens"] + usage["cache_tokens_read"],
            ai_output_tokens=usage["output_tokens"],
            ai_cache_hits=usage["cache_tokens_read"],
            status="success",
        )
    )
    await db.commit()
    return {"conversation_id": str(conversation.id), **answer}


@router.get("/conversations")
async def list_conversations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(
        select(MemoryConversation)
        .where(MemoryConversation.user_id == user.id)
        .order_by(MemoryConversation.updated_at.desc())
    )
    return [
        {
            "id": str(conversation.id),
            "title": conversation.title,
            "meeting_id": str(conversation.meeting_id) if conversation.meeting_id else None,
            "updated_at": conversation.updated_at.isoformat(),
        }
        for conversation in result.scalars().all()
    ]


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conversation = await _get_owned_conversation(conversation_id, user, db)
    # Stored sources are re-filtered on every read so a meeting the user lost
    # access to (or that was deleted) stops being linked from old answers.
    cited = {
        source.get("meeting_id")
        for message in conversation.messages
        for source in (message.sources or [])
        if source.get("meeting_id")
    }
    readable: set[str] = set()
    for meeting_id in cited:
        try:
            meeting_uuid = uuid.UUID(meeting_id)
        except ValueError:
            continue
        meeting = await db.get(Meeting, meeting_uuid)
        if meeting is not None and meeting.deleted_at is None and await user_can_read_meeting(db, user, meeting_uuid):
            readable.add(meeting_id)
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "meeting_id": str(conversation.meeting_id) if conversation.meeting_id else None,
        "scope_meeting_ids": conversation.scope_meeting_ids or [],
        "messages": [
            {
                "role": message.role,
                "content": message.content,
                "sources": [
                    source for source in (message.sources or [])
                    if not source.get("meeting_id") or source.get("meeting_id") in readable
                ],
                "created_at": message.created_at.isoformat(),
            }
            for message in conversation.messages
        ],
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conversation = await _get_owned_conversation(conversation_id, user, db)
    await db.delete(conversation)
    await db.commit()
    return {"ok": True}
