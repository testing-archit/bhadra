import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import and_, delete, func, select, union, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.database.models import Decision, Meeting, MeetingTask, Project, Risk, User, meeting_projects
from app.dependencies import department_scope, get_current_user, meeting_visibility_clause
from app.services.meeting_index_service import rebuild_meeting_index

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectNameRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Project name is required")
        return value


@router.post("")
async def create_project(
    body: ProjectNameRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _ensure_name_free(db, body.name)
    project = Project(name=body.name, department=department_scope(user) or user.department)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return {
        "id": str(project.id),
        "name": project.name,
        "department": project.department,
        "meeting_count": 0,
        "task_count": 0,
        "decision_count": 0,
        "risk_count": 0,
    }


async def _ensure_name_free(db: AsyncSession, name: str, project_id: uuid.UUID | None = None) -> None:
    """Project names are unique regardless of case (they're matched that way
    at ingest), including against projects in the Recycle Bin."""
    query = select(Project).where(func.lower(Project.name) == name.lower())
    if project_id is not None:
        query = query.where(Project.id != project_id)
    existing_project = (await db.execute(query)).scalar_one_or_none()
    if existing_project:
        detail = (
            "A project with this name is in the Recycle Bin"
            if existing_project.deleted_at is not None
            else "A project with this name already exists"
        )
        raise HTTPException(status_code=409, detail=detail)


async def _project_meeting_ids(db: AsyncSession, project_id: uuid.UUID) -> set[uuid.UUID]:
    """Every meeting the project appears in — tagged directly, or through one
    of its tasks, decisions or risks."""
    result = await db.execute(
        union(
            select(meeting_projects.c.meeting_id).where(meeting_projects.c.project_id == project_id),
            select(MeetingTask.meeting_id).where(MeetingTask.project_id == project_id),
            select(Decision.meeting_id).where(Decision.project_id == project_id),
            select(Risk.meeting_id).where(Risk.project_id == project_id),
        )
    )
    return set(result.scalars().all())


async def _editable_project(db: AsyncSession, user: User, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    scope = department_scope(user)
    if project is None or project.deleted_at is not None or (
        scope is not None and project.department != scope
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}")
async def rename_project(
    project_id: uuid.UUID,
    body: ProjectNameRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await _editable_project(db, user, project_id)
    if body.name != project.name:
        await _ensure_name_free(db, body.name, project.id)
        project.name = body.name
        await db.flush()
        # Company Memory indexes items with their project's name.
        for meeting_id in await _project_meeting_ids(db, project.id):
            await rebuild_meeting_index(db, meeting_id)
        await db.commit()
    return {"id": str(project.id), "name": project.name, "department": project.department}


@router.delete("/{project_id}")
async def delete_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await _editable_project(db, user, project_id)
    affected_meeting_ids = await _project_meeting_ids(db, project.id)

    # Preserve associations while the project is recoverable. Normal views
    # and Company Memory ignore deleted projects until they are restored.
    project.deleted_at = datetime.datetime.now(datetime.UTC)
    project.deleted_by = user.id
    await db.flush()
    for meeting_id in affected_meeting_ids:
        await rebuild_meeting_index(db, meeting_id)
    await db.commit()
    return {"ok": True}


@router.get("")
async def list_projects(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = (
        select(
            Project,
            func.count(func.distinct(MeetingTask.id)),
            func.count(func.distinct(Decision.id)),
            func.count(func.distinct(Risk.id)),
            func.count(func.distinct(Meeting.id)),
        )
        .outerjoin(MeetingTask, and_(MeetingTask.project_id == Project.id, MeetingTask.deleted_at.is_(None)))
        .outerjoin(Decision, and_(Decision.project_id == Project.id, Decision.deleted_at.is_(None)))
        .outerjoin(Risk, and_(Risk.project_id == Project.id, Risk.deleted_at.is_(None)))
        .outerjoin(meeting_projects, meeting_projects.c.project_id == Project.id)
        .outerjoin(Meeting, and_(Meeting.id == meeting_projects.c.meeting_id, Meeting.deleted_at.is_(None)))
        .where(Project.deleted_at.is_(None))
        .group_by(Project.id)
        .order_by(Project.name)
    )
    scope = department_scope(user)
    if scope is not None:
        query = query.where(Project.department == scope)

    result = await db.execute(query)
    return [
        {
            "id": str(project.id),
            "name": project.name,
            "department": project.department,
            "task_count": task_count,
            "decision_count": decision_count,
            "risk_count": risk_count,
            "meeting_count": meeting_count,
        }
        for project, task_count, decision_count, risk_count, meeting_count in result.all()
    ]


@router.get("/{project_id}")
async def get_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    project = await db.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Project not found")

    scope = department_scope(user)
    if scope is not None and project.department != scope:
        raise HTTPException(status_code=404, detail="Project not found")

    # A project gathers meetings from many people; show only the ones this
    # person may read, like every other list.
    visibility = meeting_visibility_clause(user)
    tasks_result = await db.execute(
        select(MeetingTask, Meeting.title, Meeting.date, Meeting.summary)
        .join(Meeting, MeetingTask.meeting_id == Meeting.id)
        .where(
            MeetingTask.project_id == project_id,
            MeetingTask.deleted_at.is_(None),
            Meeting.deleted_at.is_(None),
            visibility,
        )
        .order_by(MeetingTask.created_at.desc())
    )
    decisions_result = await db.execute(
        select(Decision, Meeting.title, Meeting.date, Meeting.summary)
        .join(Meeting, Decision.meeting_id == Meeting.id)
        .where(
            Decision.project_id == project_id,
            Decision.deleted_at.is_(None),
            Meeting.deleted_at.is_(None),
            visibility,
        )
        .order_by(Decision.created_at.desc())
    )
    risks_result = await db.execute(
        select(Risk, Meeting.title, Meeting.date, Meeting.summary)
        .join(Meeting, Risk.meeting_id == Meeting.id)
        .where(
            Risk.project_id == project_id,
            Risk.deleted_at.is_(None),
            Meeting.deleted_at.is_(None),
            visibility,
        )
        .order_by(Risk.created_at.desc())
    )
    meetings_result = await db.execute(
        select(Meeting)
        .join(meeting_projects, meeting_projects.c.meeting_id == Meeting.id)
        .where(
            meeting_projects.c.project_id == project_id,
            Meeting.deleted_at.is_(None),
            visibility,
        )
        .order_by(Meeting.date.desc())
    )

    return {
        "id": str(project.id),
        "name": project.name,
        "department": project.department,
        "meetings": [
            {
                "id": str(meeting.id),
                "title": meeting.title,
                "date": meeting.date.isoformat(),
                "duration_minutes": meeting.duration_minutes,
                "summary": meeting.summary,
            }
            for meeting in meetings_result.scalars().all()
        ],
        "tasks": [
            {
                "id": str(t.id),
                "meeting_id": str(t.meeting_id),
                "meeting_title": title,
                "meeting_date": date.isoformat(),
                "meeting_summary": summary,
                "owner": t.owner,
                "description": t.description,
                "deadline": t.deadline,
                "priority": t.priority,
                "status": t.status,
            }
            for t, title, date, summary in tasks_result.all()
        ],
        "decisions": [
            {
                "id": str(d.id),
                "meeting_id": str(d.meeting_id),
                "meeting_title": title,
                "meeting_date": date.isoformat(),
                "meeting_summary": summary,
                "decision": d.decision,
                "reason": d.reason,
                "alternatives": d.alternatives,
                "participants": d.participants,
                "conflict_note": d.conflict_note,
            }
            for d, title, date, summary in decisions_result.all()
        ],
        "risks": [
            {
                "id": str(r.id),
                "meeting_id": str(r.meeting_id),
                "meeting_title": title,
                "meeting_date": date.isoformat(),
                "meeting_summary": summary,
                "description": r.description,
                "severity": r.severity,
            }
            for r, title, date, summary in risks_result.all()
        ],
    }
