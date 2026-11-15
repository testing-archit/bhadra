import asyncio
import shutil
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, union, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.db import get_db
from app.database.models import (
    Decision,
    Meeting,
    MeetingTask,
    Project,
    RecordingSession,
    Risk,
    Trace,
    User,
    meeting_projects,
)
from app.dependencies import (
    department_scope,
    get_current_user,
    meeting_visibility_clause,
    user_can_manage_meeting_access,
    user_can_read_meeting,
)
from app.services import qdrant_service
from app.services.meeting_index_service import rebuild_meeting_index

router = APIRouter(prefix="/api/recycle-bin", tags=["recycle-bin"])
ItemType = Literal["meeting", "project", "task", "decision", "risk"]
MODEL_BY_TYPE = {
    "meeting": Meeting,
    "project": Project,
    "task": MeetingTask,
    "decision": Decision,
    "risk": Risk,
}


def _item_payload(item_type: ItemType, item, meeting_title: str | None = None) -> dict:
    if item_type == "meeting":
        title, detail = item.title, item.summary or "Meeting and transcript"
    elif item_type == "project":
        title, detail = item.name, "Project grouping and its associations"
    elif item_type == "task":
        title, detail = item.description, f"Task from {meeting_title}"
    elif item_type == "decision":
        title, detail = item.decision, f"Decision from {meeting_title}"
    else:
        title, detail = item.description, f"Risk from {meeting_title}"
    return {
        "id": str(item.id),
        "type": item_type,
        "title": title,
        "detail": detail,
        "deleted_at": item.deleted_at.isoformat(),
    }


@router.get("")
async def list_recycle_bin(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    scope = department_scope(user)
    visibility = meeting_visibility_clause(user)
    items: list[dict] = []

    meeting_query = select(Meeting).where(Meeting.deleted_at.isnot(None))
    # Projects span meetings and have no attendee list of their own, so they
    # stay department-scoped.
    project_query = select(Project).where(Project.deleted_at.isnot(None))
    if visibility is not None:
        meeting_query = meeting_query.where(visibility)
    if scope is not None:
        project_query = project_query.where(Project.department == scope)
    for meeting in (await db.execute(meeting_query)).scalars().all():
        items.append(_item_payload("meeting", meeting))
    for project in (await db.execute(project_query)).scalars().all():
        items.append(_item_payload("project", project))

    child_specs = (
        ("task", MeetingTask),
        ("decision", Decision),
        ("risk", Risk),
    )
    for item_type, model in child_specs:
        query = (
            select(model, Meeting.title)
            .join(Meeting, model.meeting_id == Meeting.id)
            .where(model.deleted_at.isnot(None), Meeting.deleted_at.is_(None))
        )
        if visibility is not None:
            query = query.where(visibility)
        for item, meeting_title in (await db.execute(query)).all():
            items.append(_item_payload(item_type, item, meeting_title))

    return sorted(items, key=lambda item: item["deleted_at"], reverse=True)


async def _get_scoped_item(
    db: AsyncSession, item_type: ItemType, item_id: uuid.UUID, user: User
):
    model = MODEL_BY_TYPE[item_type]
    item = await db.get(model, item_id)
    if item is None or item.deleted_at is None:
        raise HTTPException(status_code=404, detail="Deleted item not found")
    if item_type == "project":
        scope = department_scope(user)
        if scope is not None and item.department != scope:
            raise HTTPException(status_code=404, detail="Deleted item not found")
        return item

    meeting_id = item.id if item_type == "meeting" else item.meeting_id
    if item_type != "meeting" and await db.get(Meeting, meeting_id) is None:
        raise HTTPException(status_code=404, detail="Source meeting not found")
    if not await user_can_read_meeting(db, user, meeting_id):
        raise HTTPException(status_code=404, detail="Deleted item not found")
    return item


async def _project_meeting_ids(db: AsyncSession, project_id: uuid.UUID) -> set[uuid.UUID]:
    result = await db.execute(
        union(
            select(meeting_projects.c.meeting_id).where(meeting_projects.c.project_id == project_id),
            select(MeetingTask.meeting_id).where(MeetingTask.project_id == project_id),
            select(Decision.meeting_id).where(Decision.project_id == project_id),
            select(Risk.meeting_id).where(Risk.project_id == project_id),
        )
    )
    return set(result.scalars().all())


@router.post("/{item_type}/{item_id}/restore")
async def restore_item(
    item_type: ItemType,
    item_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    item = await _get_scoped_item(db, item_type, item_id, user)
    # Deleting a meeting needs the right to manage it; so does bringing it back.
    if item_type == "meeting" and not await user_can_manage_meeting_access(db, user, item):
        raise HTTPException(
            status_code=403,
            detail="Only the meeting's organizer, the person who recorded it, or a Wilco admin can restore it",
        )
    if item_type in {"task", "decision", "risk"}:
        meeting = await db.get(Meeting, item.meeting_id)
        if meeting is None or meeting.deleted_at is not None:
            raise HTTPException(status_code=409, detail="Restore the source meeting first")

    item.deleted_at = None
    item.deleted_by = None
    await db.flush()
    if item_type == "meeting":
        await rebuild_meeting_index(db, item.id)
    elif item_type == "project":
        for meeting_id in await _project_meeting_ids(db, item.id):
            await rebuild_meeting_index(db, meeting_id)
    else:
        await rebuild_meeting_index(db, item.meeting_id)
    await db.commit()
    return {"ok": True}


@router.delete("/{item_type}/{item_id}")
async def permanently_delete_item(
    item_type: ItemType,
    item_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    item = await _get_scoped_item(db, item_type, item_id, user)
    if item_type == "meeting":
        if not await user_can_manage_meeting_access(db, user, item):
            raise HTTPException(
                status_code=403,
                detail="Only the meeting's organizer, the person who recorded it, or a Wilco admin can delete it",
            )
        await asyncio.to_thread(qdrant_service.delete_meeting, str(item.id))
        await db.execute(update(Trace).where(Trace.meeting_id == item.id).values(meeting_id=None))
        # The recording (audio, diarization, speaker maps) goes with the
        # meeting. Rows are removed here; files after the commit succeeds.
        recordings = (
            await db.execute(select(RecordingSession).where(RecordingSession.meeting_id == item.id))
        ).scalars().all()
        recording_dirs = [Path(settings.recordings_dir).resolve() / str(r.id) for r in recordings]
        for recording in recordings:
            await db.delete(recording)
        await db.delete(item)
        await db.commit()
        for directory in recording_dirs:
            shutil.rmtree(directory, ignore_errors=True)
        return {"ok": True}
    elif item_type == "project":
        meeting_ids = await _project_meeting_ids(db, item.id)
        await db.execute(update(MeetingTask).where(MeetingTask.project_id == item.id).values(project_id=None))
        await db.execute(update(Decision).where(Decision.project_id == item.id).values(project_id=None))
        await db.execute(update(Risk).where(Risk.project_id == item.id).values(project_id=None))
        await db.execute(delete(meeting_projects).where(meeting_projects.c.project_id == item.id))
        await db.delete(item)
        await db.flush()
        for meeting_id in meeting_ids:
            await rebuild_meeting_index(db, meeting_id)
    else:
        meeting_id = item.meeting_id
        await db.delete(item)
        await db.flush()
        await rebuild_meeting_index(db, meeting_id)
    await db.commit()
    return {"ok": True}
