import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.db import get_db
from app.database.models import PolicyConversation, PolicyMessage, Trace, User
from app.dependencies import get_current_user
from app.rate_limit import limiter
from app.services import policy_retriever

router = APIRouter(prefix="/api/policy-chat", tags=["policy-chat"])

# How many prior turns get sent back to Gemini as conversational context —
# enough to resolve a follow-up like "what about for interns?" without
# growing the prompt (and cost) unboundedly as a conversation gets long.
HISTORY_TURNS = 6

MAX_TITLE_LENGTH = 60


def _ordered_messages(conversation: PolicyConversation) -> list[PolicyMessage]:
    # PostgreSQL now() is fixed for the transaction, so a new user message and
    # its assistant reply can receive an identical created_at. Always put the
    # question first for both history and API responses in that tie case.
    return sorted(
        conversation.messages,
        key=lambda message: (message.created_at, 0 if message.role == "user" else 1, str(message.id)),
    )


async def _get_owned_conversation(
    conversation_id: uuid.UUID, user: User, db: AsyncSession
) -> PolicyConversation:
    result = await db.execute(
        select(PolicyConversation)
        .options(selectinload(PolicyConversation.messages))
        .where(PolicyConversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


class AskRequest(BaseModel):
    query: str
    conversation_id: str | None = None


@router.post("/ask")
@limiter.limit("20/minute")
async def ask(
    request: Request,
    body: AskRequest,
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
            {"role": m.role, "content": m.content} for m in _ordered_messages(conversation)[-HISTORY_TURNS:]
        ]
    else:
        conversation = PolicyConversation(
            user_id=user.id,
            title=query if len(query) <= MAX_TITLE_LENGTH else query[: MAX_TITLE_LENGTH - 1] + "…",
        )
        db.add(conversation)
        await db.flush()
        history = []

    db.add(PolicyMessage(conversation_id=conversation.id, role="user", content=query))

    result = await asyncio.to_thread(policy_retriever.answer_query, query, history)

    db.add(
        PolicyMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=result["answer"],
            sources=result["sources"],
        )
    )
    conversation.updated_at = datetime.now(timezone.utc)

    usage = result["usage"]
    if usage is not None:
        db.add(
            Trace(
                user_id=user.id,
                meeting_id=None,
                meeting_title=f"Policy chat — {conversation.title}",
                ai_input_tokens=usage["input_tokens"] + usage["cache_tokens_read"],
                ai_output_tokens=usage["output_tokens"],
                ai_cache_hits=usage["cache_tokens_read"],
                status="success",
            )
        )

    await db.commit()

    return {
        "conversation_id": str(conversation.id),
        "answer": result["answer"],
        "sources": result["sources"],
    }


@router.get("/conversations")
async def list_conversations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(
        select(PolicyConversation)
        .where(PolicyConversation.user_id == user.id)
        .order_by(PolicyConversation.updated_at.desc())
    )
    return [
        {"id": str(c.id), "title": c.title, "updated_at": c.updated_at.isoformat()}
        for c in result.scalars().all()
    ]


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conversation = await _get_owned_conversation(conversation_id, user, db)
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "sources": m.sources,
                "created_at": m.created_at.isoformat(),
            }
            for m in _ordered_messages(conversation)
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
