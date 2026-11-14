"""Durable processing-stage state for meetings.

Stage writes use their own short session so they survive a rollback of the
caller's transaction — a failed extraction must still be *recorded* as failed.
"""

import asyncio
import datetime
import uuid

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.database.db import async_session
from app.database.models import ProcessingStage

STAGES = ("transcription", "extraction", "indexing", "audio", "diarization")
STAGE_LABELS = {
    "transcription": "Transcription",
    "extraction": "AI notes",
    "indexing": "Search indexing",
    "audio": "Audio assembly",
    "diarization": "Speaker analysis",
}
MAX_ERROR_CHARS = 500

# Bounds how many background pipelines one API process runs at once, so a
# burst of uploads queues instead of starving request handling.
_pipeline_slots: asyncio.Semaphore | None = None


def pipeline_slots() -> asyncio.Semaphore:
    global _pipeline_slots
    if _pipeline_slots is None:
        _pipeline_slots = asyncio.Semaphore(max(1, settings.max_concurrent_processing))
    return _pipeline_slots


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _clip(error: BaseException | str | None) -> str | None:
    if error is None:
        return None
    text = str(error) if not isinstance(error, str) else error
    # Errors can quote provider responses; keep them short and never let a
    # whole transcript ride along into the database or logs.
    return (text or type(error).__name__)[:MAX_ERROR_CHARS]


async def set_stage(
    meeting_id: uuid.UUID,
    stage: str,
    status: str,
    *,
    error: BaseException | str | None = None,
    detail: dict | None = None,
) -> None:
    now = _now()
    values: dict = {"status": status, "updated_at": now}
    if status == "running":
        values["started_at"] = now
        values["finished_at"] = None
        values["last_error"] = None
    if status in {"succeeded", "failed", "skipped"}:
        values["finished_at"] = now
    if status == "failed":
        values["last_error"] = _clip(error)
    if status == "succeeded":
        values["last_error"] = None
    if detail is not None:
        values["detail"] = detail
    insert_values = {"meeting_id": meeting_id, "stage": stage, "attempts": 1 if status == "running" else 0, **values}
    statement = pg_insert(ProcessingStage).values(**insert_values)
    update_values = dict(values)
    if status == "running":
        update_values["attempts"] = ProcessingStage.attempts + 1
    statement = statement.on_conflict_do_update(
        constraint="uq_processing_stage", set_=update_values
    )
    async with async_session() as db:
        await db.execute(statement)
        await db.commit()


async def list_stages(db, meeting_id: uuid.UUID) -> list[dict]:
    rows = (
        await db.execute(select(ProcessingStage).where(ProcessingStage.meeting_id == meeting_id))
    ).scalars().all()
    order = {name: index for index, name in enumerate(STAGES)}
    return [
        {
            "stage": row.stage,
            "label": STAGE_LABELS.get(row.stage, row.stage),
            "status": row.status,
            "attempts": row.attempts,
            "last_error": row.last_error,
            "detail": row.detail or {},
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        }
        for row in sorted(rows, key=lambda r: order.get(r.stage, 99))
    ]


async def get_stage(db, meeting_id: uuid.UUID, stage: str) -> ProcessingStage | None:
    return (
        await db.execute(
            select(ProcessingStage).where(
                ProcessingStage.meeting_id == meeting_id, ProcessingStage.stage == stage
            )
        )
    ).scalar_one_or_none()


async def fail_interrupted_stages() -> int:
    """Run at startup: anything still "running" belonged to a process that
    died mid-stage. Mark it failed so it shows a Retry button instead of a
    spinner that never ends."""
    # Thresholds sit above the longest legitimate stage (a 30-minute Prisma
    # timeout) so a sibling worker's in-flight stage is never failed by
    # another worker restarting.
    now = _now()
    stale = or_(
        and_(ProcessingStage.status == "running", ProcessingStage.updated_at < now - datetime.timedelta(minutes=45)),
        and_(ProcessingStage.status == "pending", ProcessingStage.updated_at < now - datetime.timedelta(minutes=10)),
    )
    async with async_session() as db:
        result = await db.execute(
            update(ProcessingStage)
            .where(stale)
            .values(status="failed", last_error="Interrupted by a server restart — retry to resume", finished_at=now)
        )
        await db.commit()
        return result.rowcount or 0
