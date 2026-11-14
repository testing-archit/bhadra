import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Decision, Meeting, MeetingTask, Risk
from app.services import qdrant_service

logger = logging.getLogger(__name__)


async def rebuild_meeting_index(db: AsyncSession, meeting_id: uuid.UUID, *, strict: bool = False) -> None:
    """Replace the search index content with the current relational meeting
    record.

    Search is derived data, so by default an unreachable vector store never
    fails (or rolls back) the edit that triggered this: the failure is
    recorded as the meeting's indexing stage, which the person can retry,
    exactly like a failed background re-index. `strict=True` raises instead
    (the processing pipeline, which records the stage itself)."""
    try:
        await _rebuild(db, meeting_id)
    except Exception as error:
        if strict:
            raise
        from app.services import processing_service

        logger.exception("Re-indexing meeting %s failed; the edit is kept", meeting_id)
        try:
            await processing_service.set_stage(meeting_id, "indexing", "failed", error=error)
        except Exception:
            logger.exception("Couldn't record the failed indexing stage for meeting %s", meeting_id)


async def _rebuild(db: AsyncSession, meeting_id: uuid.UUID) -> None:
    result = await db.execute(
        select(Meeting)
        .options(
            selectinload(Meeting.tasks).selectinload(MeetingTask.project),
            selectinload(Meeting.decisions).selectinload(Decision.project),
            selectinload(Meeting.risks).selectinload(Risk.project),
        )
        .where(Meeting.id == meeting_id)
    )
    meeting = result.scalar_one_or_none()
    if meeting is None or meeting.deleted_at is not None:
        await asyncio.to_thread(qdrant_service.delete_meeting, str(meeting_id))
        return

    decisions = [
        {
            "decision": item.decision,
            "reason": item.reason or "",
            "alternatives": item.alternatives or [],
            "project": item.project.name if item.project and item.project.deleted_at is None else "",
        }
        for item in meeting.decisions
        if item.deleted_at is None
    ]
    tasks = [
        {
            "task": item.description,
            "assignedTo": item.owner or "",
            "dueDate": item.deadline or "",
            "priority": item.priority or "",
            "project": item.project.name if item.project and item.project.deleted_at is None else "",
        }
        for item in meeting.tasks
        if item.deleted_at is None
    ]
    risks = [
        {
            "risk": item.description,
            "severity": item.severity or "",
            "project": item.project.name if item.project and item.project.deleted_at is None else "",
        }
        for item in meeting.risks
        if item.deleted_at is None
    ]
    await asyncio.to_thread(
        qdrant_service.replace_meeting,
        str(meeting.id),
        meeting.title,
        meeting.date.isoformat(),
        meeting.summary or "",
        meeting.transcript or "",
        decisions,
        tasks,
        meeting.department,
        risks,
    )
