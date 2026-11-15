"""Meeting whiteboards with invite-based access and optimistic edits."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.database.models import CaptureRequest, FigJamConnection, LiveCaption, Meeting, MeetingBoard, MeetingBoardRevision, User
from app.dependencies import get_current_user, user_can_read_meeting
from app.services import board_service, capture_service, mermaid_safety


router = APIRouter(prefix="/api/boards", tags=["boards"])


async def _readable_capture(db: AsyncSession, user: User, capture_id: uuid.UUID) -> CaptureRequest:
    capture = await db.get(CaptureRequest, capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail="Board not found")
    if capture.meeting_id:
        meeting = await db.get(Meeting, capture.meeting_id)
        if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, meeting.id):
            raise HTTPException(status_code=404, detail="Board not found")
        return capture
    emails = {str(person.get("email") or "").strip().lower() for person in (capture.invitees or []) if isinstance(person, dict)}
    if (user.id != capture.user_id and user.id not in await capture_service.subscriber_ids(db, capture.id)
            and user.email.lower() not in emails and user.email.lower() != (capture.organizer_email or "").lower()):
        raise HTTPException(status_code=404, detail="Board not found")
    return capture


class BoardNode(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    kind: Literal["summary", "decision", "task", "risk", "question", "idea", "note", "timeline", "diagram"]
    title: str = Field(min_length=1, max_length=160)
    text: str = Field(default="", max_length=4000)
    x: float = Field(ge=-20000, le=20000)
    y: float = Field(ge=-20000, le=20000)
    origin: Literal["ai", "manual"] = "manual"
    locked: bool = False
    source_start_ms: int | None = Field(default=None, ge=0)
    source_id: str | None = Field(default=None, max_length=120)


class BoardEdge(BaseModel):
    id: str = Field(min_length=1, max_length=180)
    source: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=120)


class BoardUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    nodes: list[BoardNode] = Field(max_length=120)
    edges: list[BoardEdge] = Field(max_length=200)

    @model_validator(mode="after")
    def valid_graph(self):
        identifiers = [node.id for node in self.nodes]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Board node ids must be unique")
        ids = set(identifiers)
        if len({edge.id for edge in self.edges}) != len(self.edges):
            raise ValueError("Board edge ids must be unique")
        if any(edge.source not in ids or edge.target not in ids for edge in self.edges):
            raise ValueError("Board edges must connect existing nodes")
        for node in self.nodes:
            if node.kind == "diagram":
                node.text = mermaid_safety.clean(node.text)
        return self


async def _readable_board(db: AsyncSession, user: User, board_id: uuid.UUID) -> MeetingBoard:
    board = await db.get(MeetingBoard, board_id)
    if board is None:
        raise HTTPException(status_code=404, detail="Board not found")
    if board.meeting_id is None and board.capture_request_id is not None:
        await _readable_capture(db, user, board.capture_request_id)
        return board
    if board.meeting_id is None:
        raise HTTPException(status_code=404, detail="Board not found")
    meeting = await db.get(Meeting, board.meeting_id)
    if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, meeting.id):
        raise HTTPException(status_code=404, detail="Board not found")
    return board


@router.get("/meetings/{meeting_id}")
async def meeting_board(
    meeting_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, meeting_id):
        raise HTTPException(status_code=404, detail="Meeting not found")
    board = await board_service.ensure_for_meeting(db, meeting)
    file_url = await db.scalar(select(FigJamConnection.file_url).join(CaptureRequest,
        CaptureRequest.id == FigJamConnection.capture_request_id).where(CaptureRequest.meeting_id == meeting_id).limit(1))
    await db.commit()
    return {**board_service.serialize(board), 'external_url': file_url}


@router.get("/captures/{capture_id}")
async def capture_board(
    capture_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    capture = await _readable_capture(db, user, capture_id)
    if capture.meeting_id:
        meeting = await db.get(Meeting, capture.meeting_id)
        if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, meeting.id):
            raise HTTPException(status_code=404, detail="Board not found")
        board = await board_service.ensure_for_meeting(db, meeting)
        await db.commit()
        return board_service.serialize(board)
    board = await board_service.ensure_for_capture(db, capture)
    await db.commit()
    return board_service.serialize(board)


@router.get("/captures/{capture_id}/captions")
async def capture_captions(
    capture_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _readable_capture(db, user, capture_id)
    rows = list((await db.scalars(
        select(LiveCaption).where(LiveCaption.capture_request_id == capture_id)
        .order_by(LiveCaption.seq.desc()).limit(250)
    )).all())[::-1]
    return [{"seq": row.seq, "speaker": row.speaker, "text": row.text,
             "start": row.start_seconds, "end": row.end_seconds} for row in rows]


@router.put("/{board_id}")
async def update_board(
    board_id: uuid.UUID,
    body: BoardUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _readable_board(db, user, board_id)
    board = (await db.execute(select(MeetingBoard).where(MeetingBoard.id == board_id).with_for_update())).scalar_one()
    if board.version != body.expected_version:
        raise HTTPException(status_code=409, detail={"message": "Board changed in another tab", "board": board_service.serialize(board)})
    old = {node["id"]: node for node in board.nodes or []}
    nodes = []
    for entry in body.nodes:
        node = entry.model_dump()
        previous = old.get(node["id"])
        if previous:
            # An edited AI node becomes human-owned; later AI updates leave it alone.
            changed = any(previous.get(key) != node[key] for key in ("kind", "title", "text", "x", "y", "locked"))
            node["origin"] = "manual" if changed or previous.get("origin") == "manual" else "ai"
            node["source_start_ms"] = previous.get("source_start_ms")
            node["source_id"] = previous.get("source_id")
        else:
            node["origin"] = "manual"
            node["source_start_ms"] = None
            node["source_id"] = None
        nodes.append(node)
    await board_service.save_snapshot(
        db, board, expected_version=body.expected_version,
        nodes=nodes, edges=[edge.model_dump() for edge in body.edges],
        actor_id=user.id, source="manual", title=body.title,
    )
    await db.commit()
    return board_service.serialize(board)


@router.get("/{board_id}/history")
async def board_history(
    board_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _readable_board(db, user, board_id)
    rows = (await db.scalars(
        select(MeetingBoardRevision).where(MeetingBoardRevision.board_id == board_id)
        .order_by(MeetingBoardRevision.version.desc()).limit(50)
    )).all()
    return [{"version": row.version, "source": row.source, "actor_id": str(row.actor_id) if row.actor_id else None,
             "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows]


class BoardPause(BaseModel):
    paused: bool


@router.post("/{board_id}/pause")
async def pause_board(
    board_id: uuid.UUID,
    body: BoardPause,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _readable_board(db, user, board_id)
    board = (await db.execute(select(MeetingBoard).where(MeetingBoard.id == board_id).with_for_update())).scalar_one()
    board.paused = body.paused
    await db.commit()
    return board_service.serialize(board)
