import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.database.models import Decision, Meeting, MeetingTask, User
from app.dependencies import get_current_user, meeting_visibility_clause

router = APIRouter(prefix="/api/digest", tags=["digest"])


def _week_bounds(week_offset: int) -> tuple[datetime.datetime, datetime.datetime]:
    now = datetime.datetime.now(datetime.UTC)
    monday = (now - datetime.timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = monday + datetime.timedelta(weeks=week_offset)
    end = start + datetime.timedelta(days=7)
    return start, end


@router.get("")
async def get_digest(
    week_offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """This week (or an earlier week, via week_offset) at a glance —
    meetings held, tasks completed, decisions made, and any decisions that
    contradicted an earlier one. Scoped to the meetings you attended, like
    every other view."""
    visibility = meeting_visibility_clause(user)
    start, end = _week_bounds(week_offset)

    meeting_query = select(Meeting).where(
        Meeting.date >= start,
        Meeting.date < end,
        Meeting.deleted_at.is_(None),
    )
    if visibility is not None:
        meeting_query = meeting_query.where(visibility)
    meetings = (await db.execute(meeting_query.order_by(Meeting.date))).scalars().all()
    meeting_ids = [m.id for m in meetings]

    task_counts: dict = {}
    decision_counts: dict = {}
    if meeting_ids:
        tc_result = await db.execute(
            select(MeetingTask.meeting_id, func.count(MeetingTask.id))
            .where(MeetingTask.meeting_id.in_(meeting_ids), MeetingTask.deleted_at.is_(None))
            .group_by(MeetingTask.meeting_id)
        )
        task_counts = dict(tc_result.all())
        dc_result = await db.execute(
            select(Decision.meeting_id, func.count(Decision.id))
            .where(Decision.meeting_id.in_(meeting_ids), Decision.deleted_at.is_(None))
            .group_by(Decision.meeting_id)
        )
        decision_counts = dict(dc_result.all())

    completed_query = (
        select(func.count(MeetingTask.id))
        .select_from(MeetingTask)
        .join(Meeting, MeetingTask.meeting_id == Meeting.id)
        .where(
            MeetingTask.status == "done",
            MeetingTask.deleted_at.is_(None),
            Meeting.deleted_at.is_(None),
            MeetingTask.updated_at >= start,
            MeetingTask.updated_at < end,
        )
    )
    if visibility is not None:
        completed_query = completed_query.where(visibility)
    tasks_completed = (await db.execute(completed_query)).scalar_one() or 0

    decisions_query = (
        select(Decision, Meeting.title, Meeting.date)
        .join(Meeting, Decision.meeting_id == Meeting.id)
        .where(
            Meeting.date >= start,
            Meeting.date < end,
            Meeting.deleted_at.is_(None),
            Decision.deleted_at.is_(None),
        )
        .order_by(Meeting.date)
    )
    if visibility is not None:
        decisions_query = decisions_query.where(visibility)
    decisions_rows = (await db.execute(decisions_query)).all()

    return {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "meetings_count": len(meetings),
        "tasks_completed": tasks_completed,
        "decisions_made": len(decisions_rows),
        "contradictions_found": sum(1 for d, _, _ in decisions_rows if d.conflict_note),
        "meetings": [
            {
                "id": str(m.id),
                "title": m.title,
                "date": m.date.isoformat(),
                "summary": m.summary,
                "task_count": task_counts.get(m.id, 0),
                "decision_count": decision_counts.get(m.id, 0),
            }
            for m in meetings
        ],
        "decisions": [
            {
                "id": str(d.id),
                "decision": d.decision,
                "meeting_id": str(d.meeting_id),
                "meeting_title": title,
                "meeting_date": date.isoformat(),
                "conflict_note": d.conflict_note,
            }
            for d, title, date in decisions_rows
        ],
    }
