import datetime
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.database.models import Decision, Meeting, Project, User
from app.dependencies import get_current_user, meeting_visibility_clause
from app.services import vocabulary_service
from app.services.meeting_index_service import rebuild_meeting_index


def _visibility(user: User) -> tuple:
    """Splat into a .where() — empty for admins, one clause for everyone else,
    restricting decisions to the meetings the user attended."""
    clause = meeting_visibility_clause(user)
    return () if clause is None else (clause,)


router = APIRouter(prefix="/api/decisions", tags=["decisions"])


class DecisionUpdate(BaseModel):
    decision: str | None = Field(default=None, max_length=4000)
    reason: str | None = Field(default=None, max_length=8000)
    alternatives: list[str] | None = None
    participants: list[str] | None = None

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Decision is required")
        return value


@router.delete("/{decision_id}")
async def delete_decision(
    decision_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Decision)
        .join(Meeting, Decision.meeting_id == Meeting.id)
        .where(
            Decision.id == decision_id,
            Decision.deleted_at.is_(None),
            Meeting.deleted_at.is_(None),
            *_visibility(user),
        )
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    decision = row[0]

    meeting_id = decision.meeting_id
    decision.deleted_at = datetime.datetime.now(datetime.UTC)
    decision.deleted_by = user.id
    await db.flush()
    await rebuild_meeting_index(db, meeting_id)
    await db.commit()
    return {"ok": True}


@router.get("")
async def list_decisions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = (
        select(Decision, Meeting.title, Meeting.date, Project.name)
        .join(Meeting, Decision.meeting_id == Meeting.id)
        .outerjoin(Project, and_(Decision.project_id == Project.id, Project.deleted_at.is_(None)))
        .where(Decision.deleted_at.is_(None), Meeting.deleted_at.is_(None))
        .order_by(Decision.created_at.desc())
    )
    query = query.where(*_visibility(user))

    result = await db.execute(query)
    return [
        {
            "id": str(decision.id),
            "meeting_id": str(decision.meeting_id),
            "meeting_title": title,
            "meeting_date": date.isoformat(),
            "decision": decision.decision,
            "reason": decision.reason,
            "alternatives": decision.alternatives or [],
            "participants": decision.participants or [],
            "conflict_note": decision.conflict_note,
            "project": project_name,
            "project_id": str(decision.project_id) if decision.project_id else None,
            "verified_at": decision.verified_at.isoformat() if decision.verified_at else None,
        }
        for decision, title, date, project_name in result.all()
    ]


@router.get("/{decision_id}")
async def get_decision(
    decision_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Decision, Meeting.title, Meeting.date, Project.name)
        .join(Meeting, Decision.meeting_id == Meeting.id)
        .outerjoin(Project, and_(Decision.project_id == Project.id, Project.deleted_at.is_(None)))
        .where(
            Decision.id == decision_id,
            Decision.deleted_at.is_(None),
            Meeting.deleted_at.is_(None),
            *_visibility(user),
        )
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")

    decision, title, date, project_name = row

    return {
        "id": str(decision.id),
        "meeting_id": str(decision.meeting_id),
        "meeting_title": title,
        "meeting_date": date.isoformat(),
        "decision": decision.decision,
        "reason": decision.reason,
        "alternatives": decision.alternatives or [],
        "participants": decision.participants or [],
        "conflict_note": decision.conflict_note,
        "project": project_name,
        "project_id": str(decision.project_id) if decision.project_id else None,
        "verified_at": decision.verified_at.isoformat() if decision.verified_at else None,
    }


@router.patch("/{decision_id}")
async def update_decision(
    decision_id: uuid.UUID,
    body: DecisionUpdate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Decision)
        .join(Meeting, Decision.meeting_id == Meeting.id)
        .where(
            Decision.id == decision_id,
            Decision.deleted_at.is_(None),
            Meeting.deleted_at.is_(None),
            *_visibility(user),
        )
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    decision = row[0]

    updates = body.model_dump(exclude_unset=True)
    before = {"decision": decision.decision, "reason": decision.reason}
    for field, value in updates.items():
        if field in {"alternatives", "participants"}:
            value = [item.strip() for item in (value or []) if item.strip()]
        elif isinstance(value, str):
            value = value.strip()
        setattr(decision, field, value)
    decision.verified_at = datetime.datetime.now(datetime.UTC)
    decision.verified_by = user.id
    await db.flush()
    corrections, propagation = await vocabulary_service.correct_from_edit(
        db, decision.meeting_id, [(before["decision"], decision.decision), (before["reason"], decision.reason)], user
    )
    await rebuild_meeting_index(db, decision.meeting_id)
    await db.commit()
    vocabulary_service.schedule_followups(background_tasks, decision.meeting_id, propagation)
    return {
        "learned_corrections": corrections,
        "id": str(decision.id),
        "decision": decision.decision,
        "reason": decision.reason,
        "alternatives": decision.alternatives or [],
        "participants": decision.participants or [],
        "verified_at": decision.verified_at.isoformat(),
    }
