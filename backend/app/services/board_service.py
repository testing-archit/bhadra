"""Versioned meeting boards built from grounded notes and live captions."""

import datetime
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import async_session
from app.database.models import Decision, Meeting, MeetingBoard, MeetingBoardRevision, MeetingInsight, MeetingTask, Risk


def serialize(board: MeetingBoard) -> dict:
    return {
        "id": str(board.id),
        "meeting_id": str(board.meeting_id) if board.meeting_id else None,
        "capture_request_id": str(board.capture_request_id) if board.capture_request_id else None,
        "title": board.title,
        "nodes": board.nodes or [],
        "edges": board.edges or [],
        "version": board.version,
        "paused": board.paused,
        "ai_cursor_seconds": board.ai_cursor_seconds,
        "updated_at": board.updated_at.isoformat() if board.updated_at else None,
    }


def _node(identifier: str, kind: str, title: str, text: str, x: int, y: int, *, evidence=None) -> dict:
    first = next((item for item in (evidence or []) if isinstance(item, dict)), None)
    return {
        "id": identifier,
        "kind": kind,
        "title": title[:160],
        "text": text[:4000],
        "x": x,
        "y": y,
        "origin": "ai",
        "locked": False,
        "source_start_ms": first.get("start_ms") if first else None,
        "source_id": first.get("segment_id") if first else None,
    }


def notes_to_canvas(meeting: Meeting, tasks: list[MeetingTask], decisions: list[Decision], risks: list[Risk], insight: MeetingInsight | None) -> tuple[list, list]:
    """A zero-cost first board; no second model call after note extraction."""
    nodes: list[dict] = []
    edges: list[dict] = []
    summary = meeting.summary or (insight.overview if insight else None)
    if summary:
        nodes.append(_node("summary", "summary", "Meeting in brief", summary, 80, 70))
    columns = [
        ("decision", "Decisions", decisions, lambda row: row.decision, lambda row: row.reason or "", 80),
        ("task", "Next steps", tasks, lambda row: row.description, lambda row: " · ".join(part for part in [row.owner, row.deadline] if part), 450),
        ("risk", "Risks", risks, lambda row: row.description, lambda row: row.severity or "", 820),
    ]
    for kind, heading, rows, title_of, text_of, x in columns:
        for index, row in enumerate(rows[:20]):
            identifier = f"{kind}:{row.id}"
            nodes.append(_node(identifier, kind, title_of(row), text_of(row), x, 250 + index * 190, evidence=row.evidence))
            if summary:
                edges.append({"id": f"summary:{identifier}", "source": "summary", "target": identifier})
    if insight:
        for index, question in enumerate((insight.open_questions or [])[:8]):
            nodes.append(_node(f"question:{index}", "question", "Open question", question, 820, 250 + (len(risks) + index) * 190))
    return nodes, edges


async def _record(db: AsyncSession, board: MeetingBoard, source: str, actor_id: uuid.UUID | None = None) -> None:
    db.add(MeetingBoardRevision(
        board_id=board.id,
        version=board.version,
        nodes=board.nodes or [],
        edges=board.edges or [],
        actor_id=actor_id,
        source=source,
    ))


async def get_for_meeting(db: AsyncSession, meeting_id: uuid.UUID) -> MeetingBoard | None:
    return await db.scalar(select(MeetingBoard).where(MeetingBoard.meeting_id == meeting_id))


async def ensure_for_meeting(db: AsyncSession, meeting: Meeting) -> MeetingBoard:
    """Build the initial board once; never replace a board people have edited."""
    # Both the post-ingest job and an early page load may try to create it.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": str(meeting.id)})
    existing = await get_for_meeting(db, meeting.id)
    if existing:
        return existing
    tasks = list((await db.scalars(select(MeetingTask).where(MeetingTask.meeting_id == meeting.id, MeetingTask.deleted_at.is_(None)))).all())
    decisions = list((await db.scalars(select(Decision).where(Decision.meeting_id == meeting.id, Decision.deleted_at.is_(None)))).all())
    risks = list((await db.scalars(select(Risk).where(Risk.meeting_id == meeting.id, Risk.deleted_at.is_(None)))).all())
    insight = await db.get(MeetingInsight, meeting.id)
    nodes, edges = notes_to_canvas(meeting, tasks, decisions, risks, insight)
    board = MeetingBoard(meeting_id=meeting.id, title=f"{meeting.title} · board", nodes=nodes, edges=edges, version=1)
    db.add(board)
    await db.flush()
    await _record(db, board, "initial")
    return board


async def ensure_from_meeting(meeting_id: uuid.UUID) -> None:
    """Best-effort post-ingest job; the page also creates a missing board."""
    async with async_session() as db:
        meeting = await db.get(Meeting, meeting_id)
        if meeting is None or meeting.deleted_at is not None:
            return
        await ensure_for_meeting(db, meeting)
        await db.commit()


async def save_snapshot(
    db: AsyncSession,
    board: MeetingBoard,
    *,
    expected_version: int,
    nodes: list,
    edges: list,
    actor_id: uuid.UUID | None,
    source: str,
    title: str | None = None,
) -> bool:
    """Caller locks the row. False means a collaborator saved first."""
    if board.version != expected_version:
        return False
    board.nodes = nodes
    board.edges = edges
    if title is not None:
        board.title = title
    board.version += 1
    board.updated_at = datetime.datetime.now(datetime.UTC)
    await _record(db, board, source, actor_id)
    return True
