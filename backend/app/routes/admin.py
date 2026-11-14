import datetime
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.config import settings
from app.database.models import AdminAuditEvent, AiUsageEvent, Decision, Meeting, MeetingAttendee, Team, Trace, User
from app.dependencies import meeting_visibility_clause, require_admin
from app.services.password_service import hash_password
from app.services import attendee_service, email_service, exchange_rate_service, notetaker_monitor, usage_ledger
from app.services.exchange_rate_service import usd_to_inr

router = APIRouter(prefix="/api/admin", tags=["admin"])
ROLES = {"member", "team_admin", "admin"}
STATUSES = {"active", "suspended"}


class TeamBody(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=500)


class AccountCreateBody(BaseModel):
    email: str
    name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    role: str = "member"
    status: str = "active"
    job_title: str | None = Field(default=None, max_length=120)
    team_id: uuid.UUID | None = None
    department: str | None = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Invalid email address")
        return value

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in ROLES:
            raise ValueError("Invalid role")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in STATUSES:
            raise ValueError("Invalid status")
        return value


class AccountUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    role: str | None = None
    status: str | None = None
    job_title: str | None = Field(default=None, max_length=120)
    team_id: uuid.UUID | None = None
    department: str | None = Field(default=None, max_length=120)
    password: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str | None) -> str | None:
        if value is not None and value not in ROLES:
            raise ValueError("Invalid role")
        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in STATUSES:
            raise ValueError("Invalid status")
        return value


def _is_configured_admin(user: User) -> bool:
    return user.email.strip().lower() in settings.admin_email_list


def _effective_role(user: User) -> str:
    return "super_admin" if _is_configured_admin(user) else user.role


def _audit(db: AsyncSession, actor: User, action: str, target_type: str, target_id, **details) -> None:
    db.add(AdminAuditEvent(
        actor_id=actor.id,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        details=details or None,
    ))


async def _ensure_team(db: AsyncSession, team_id: uuid.UUID | None) -> None:
    if team_id is not None and await db.get(Team, team_id) is None:
        raise HTTPException(status_code=422, detail="Team not found")


@router.get("/overview")
async def admin_overview(
    _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    user_counts = (await db.execute(
        select(func.count(User.id), func.count(User.id).filter(User.status == "active"))
    )).one()
    team_count = (await db.execute(select(func.count(Team.id)))).scalar_one()
    meeting_count = (await db.execute(
        select(func.count(Meeting.id)).where(Meeting.deleted_at.is_(None))
    )).scalar_one()
    failed_traces = (await db.execute(
        select(func.count(Trace.id)).where(Trace.status != "success")
    )).scalar_one()
    last_trace = (await db.execute(select(func.max(Trace.created_at)))).scalar_one()
    return {
        "total_users": user_counts[0], "active_users": user_counts[1],
        "suspended_users": user_counts[0] - user_counts[1], "teams": team_count,
        "meetings": meeting_count, "failed_operations": failed_traces,
        "last_activity_at": last_trace.isoformat() if last_trace else None,
        "services": [
            {"name": "API", "status": "operational"},
            {"name": "PostgreSQL", "status": "operational"},
            {"name": "Qdrant", "status": "operational"},
        ],
    }


@router.get("/teams")
async def list_teams(
    _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    result = await db.execute(
        select(Team, func.count(User.id)).outerjoin(User, User.team_id == Team.id)
        .group_by(Team.id).order_by(Team.name)
    )
    return [{
        "id": str(team.id), "name": team.name, "description": team.description,
        "member_count": count, "created_at": team.created_at.isoformat(),
    } for team, count in result.all()]


@router.post("/teams", status_code=201)
async def create_team(
    body: TeamBody, actor: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    name = body.name.strip()
    existing = await db.execute(select(Team).where(func.lower(Team.name) == name.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A team with this name already exists")
    team = Team(name=name, description=body.description.strip() if body.description else None)
    db.add(team)
    await db.flush()
    _audit(db, actor, "team.created", "team", team.id, name=team.name)
    await db.commit()
    await db.refresh(team)
    return {"id": str(team.id), "name": team.name, "description": team.description, "member_count": 0, "created_at": team.created_at.isoformat()}


@router.patch("/teams/{team_id}")
async def update_team(
    team_id: uuid.UUID, body: TeamBody, actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    team = await db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    team.name = body.name.strip()
    team.description = body.description.strip() if body.description else None
    _audit(db, actor, "team.updated", "team", team.id, name=team.name)
    await db.commit()
    return {"id": str(team.id), "name": team.name, "description": team.description}


@router.delete("/teams/{team_id}")
async def delete_team(
    team_id: uuid.UUID, actor: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    team = await db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    await db.delete(team)
    _audit(db, actor, "team.deleted", "team", team.id, name=team.name)
    await db.commit()
    return {"ok": True}


@router.get("/accounts")
async def list_accounts(
    _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    last_activity = (
        select(Trace.user_id, func.max(Trace.created_at).label("last_activity"))
        .group_by(Trace.user_id).subquery()
    )
    result = await db.execute(
        select(User, Team.name, last_activity.c.last_activity)
        .outerjoin(Team, User.team_id == Team.id)
        .outerjoin(last_activity, last_activity.c.user_id == User.id)
        .order_by(User.created_at.desc())
    )
    return [{
        "id": str(user.id), "email": user.email, "name": user.name,
        "role": _effective_role(user), "status": user.status,
        "job_title": user.job_title, "team_id": str(user.team_id) if user.team_id else None,
        "team_name": team_name, "department": user.department,
        "auth_method": "Google" if user.google_sub else "Password",
        "created_at": user.created_at.isoformat(),
        "last_activity_at": activity.isoformat() if activity else None,
    } for user, team_name, activity in result.all()]


@router.post("/accounts", status_code=201)
async def create_account(
    body: AccountCreateBody, actor: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    if (await db.execute(select(User).where(func.lower(User.email) == body.email))).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    await _ensure_team(db, body.team_id)
    user = User(email=body.email, name=body.name.strip(), password_hash=hash_password(body.password),
                role=body.role, status=body.status, job_title=body.job_title,
                team_id=body.team_id, department=body.department)
    db.add(user)
    await db.flush()
    await attendee_service.link_new_account(db, user)
    _audit(db, actor, "account.created", "user", user.id, email=user.email, role=user.role)
    if user.status == "active":
        # They choose their own password from the email (or use Google);
        # the one the admin typed is never emailed.
        token = await email_service.issue_password_link(db, user, "invite")
        await email_service.enqueue(
            db, "invite", user.id, {"token": token, "invited_by": actor.name or actor.email}, dedupe_key=f"invite:{user.id}"
        )
    await db.commit()
    return {"id": str(user.id), "email": user.email, "name": user.name, "role": user.role, "status": user.status}


@router.patch("/accounts/{user_id}")
async def update_account(
    user_id: uuid.UUID, body: AccountUpdateBody, actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if _is_configured_admin(user) and (body.role is not None or body.status == "suspended"):
        raise HTTPException(status_code=422, detail="Configured super-admins cannot be demoted or suspended")
    if user.id == actor.id and body.status == "suspended":
        raise HTTPException(status_code=422, detail="You cannot suspend your own account")
    await _ensure_team(db, body.team_id)
    changed = body.model_fields_set
    for field in ("name", "role", "status", "job_title", "team_id", "department"):
        if field in changed:
            setattr(user, field, getattr(body, field))
    if body.password:
        user.password_hash = hash_password(body.password)
        # A password reset by an admin signs out the person's existing
        # sessions, as a reset by them does (not the admin's own, mid-edit).
        if user.id != actor.id:
            user.sessions_valid_after = datetime.datetime.now(datetime.UTC)
    _audit(db, actor, "account.updated", "user", user.id, fields=sorted(changed))
    await db.commit()
    return {"id": str(user.id), "email": user.email, "name": user.name, "role": _effective_role(user), "status": user.status}


@router.get("/audit-events")
async def list_audit_events(
    _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    result = await db.execute(
        select(AdminAuditEvent, User.email).outerjoin(User, User.id == AdminAuditEvent.actor_id)
        .order_by(AdminAuditEvent.created_at.desc()).limit(200)
    )
    return [{
        "id": str(event.id), "actor_email": email or "Deleted admin", "action": event.action,
        "target_type": event.target_type, "target_id": event.target_id,
        "details": event.details, "created_at": event.created_at.isoformat(),
    } for event, email in result.all()]


def _churn_rate(total: int, conflicted: int) -> float:
    return round(conflicted / total, 4) if total else 0.0


@router.get("/traces")
async def list_traces(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(select(Trace).order_by(Trace.created_at.desc()).limit(200))
    traces = result.scalars().all()
    confidential = set((await db.execute(
        select(Meeting.id).where(Meeting.id.in_({t.meeting_id for t in traces if t.meeting_id}), Meeting.confidential)
    )).scalars().all()) if traces else set()
    return [
        {
            "id": str(t.id),
            "meeting_title": "Confidential meeting" if t.meeting_id in confidential else t.meeting_title,
            "duration_minutes": t.duration_minutes,
            "transcription_requests": t.transcription_requests,
            "ai_input_tokens": t.ai_input_tokens,
            "ai_output_tokens": t.ai_output_tokens,
            "ai_cache_hits": t.ai_cache_hits,
            "tasks_found": t.tasks_found,
            "decisions_found": t.decisions_found,
            "status": t.status,
            "created_at": t.created_at.isoformat(),
        }
        for t in traces
    ]


@router.get("/usage-summary")
async def usage_summary(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(
            func.count(Trace.id),
            func.sum(Trace.ai_input_tokens),
            func.sum(Trace.ai_output_tokens),
            func.sum(Trace.ai_cache_hits),
            func.sum(Trace.transcription_requests),
            func.sum(Trace.duration_minutes),
        )
    )
    count, input_tokens, output_tokens, cache_hits, transcription_requests, duration_minutes = result.one()

    # Attributed via the trace's user (always set, even for traces whose
    # meeting insert was rolled back on a failed ingest) rather than the
    # meeting's department, so failed ingests are still counted somewhere.
    department_col = func.coalesce(User.department, "unassigned")
    dept_result = await db.execute(
        select(
            department_col,
            func.count(Trace.id),
            func.sum(Trace.ai_input_tokens),
            func.sum(Trace.ai_output_tokens),
            func.sum(Trace.ai_cache_hits),
            func.sum(Trace.transcription_requests),
            func.sum(Trace.duration_minutes),
        )
        .select_from(Trace)
        .join(User, Trace.user_id == User.id)
        .group_by(department_col)
        .order_by(func.count(Trace.id).desc())
    )
    by_department = [
        {
            "department": dept,
            "meetings_processed": dept_count or 0,
            "ai_input_tokens": dept_input or 0,
            "ai_output_tokens": dept_output or 0,
            "ai_cache_hits": dept_cache or 0,
            "transcription_requests": dept_transcription or 0,
            "duration_minutes": dept_duration or 0,
        }
        for dept, dept_count, dept_input, dept_output, dept_cache, dept_transcription, dept_duration in dept_result.all()
    ]

    exchange_rate = await usd_to_inr()

    return {
        "meetings_processed": count or 0,
        "ai_input_tokens": input_tokens or 0,
        "ai_output_tokens": output_tokens or 0,
        "ai_cache_hits": cache_hits or 0,
        "transcription_requests": transcription_requests or 0,
        "duration_minutes": duration_minutes or 0,
        "exchange_rate": exchange_rate,
        "by_department": by_department,
    }


@router.get("/decision-churn")
async def decision_churn(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """How often decisions get reversed/contradicted (Decision.conflict_note
    set by the contradiction-detection check at ingest time), overall, by
    department, and by month — a signal of decision-making volatility that
    didn't exist as measurable data before conflict_note."""
    conflicted_count = func.count(Decision.id).filter(Decision.conflict_note.isnot(None))

    overall_result = await db.execute(
        select(func.count(Decision.id), conflicted_count)
        .select_from(Decision)
        .where(Decision.deleted_at.is_(None))
    )
    total, conflicted = overall_result.one()
    total = total or 0
    conflicted = conflicted or 0

    department_col = func.coalesce(Meeting.department, "unassigned")
    dept_result = await db.execute(
        select(department_col, func.count(Decision.id), conflicted_count)
        .select_from(Decision)
        .join(Meeting, Decision.meeting_id == Meeting.id)
        .where(Decision.deleted_at.is_(None), Meeting.deleted_at.is_(None))
        .group_by(department_col)
        .order_by(func.count(Decision.id).desc())
    )
    by_department = [
        {
            "department": dept,
            "total_decisions": dept_total or 0,
            "conflicted_decisions": dept_conflicted or 0,
            "churn_rate": _churn_rate(dept_total or 0, dept_conflicted or 0),
        }
        for dept, dept_total, dept_conflicted in dept_result.all()
    ]

    month_col = func.date_trunc("month", Meeting.date)
    month_result = await db.execute(
        select(month_col, func.count(Decision.id), conflicted_count)
        .select_from(Decision)
        .join(Meeting, Decision.meeting_id == Meeting.id)
        .where(Decision.deleted_at.is_(None), Meeting.deleted_at.is_(None))
        .group_by(month_col)
        .order_by(month_col)
    )
    by_month = [
        {
            "month": month.strftime("%Y-%m"),
            "total_decisions": month_total or 0,
            "conflicted_decisions": month_conflicted or 0,
            "churn_rate": _churn_rate(month_total or 0, month_conflicted or 0),
        }
        for month, month_total, month_conflicted in month_result.all()
    ]

    return {
        "total_decisions": total,
        "conflicted_decisions": conflicted,
        "churn_rate": _churn_rate(total, conflicted),
        "by_department": by_department,
        "by_month": by_month,
    }


@router.get("/meetings")
async def admin_meetings(
    q: str = "",
    limit: int = 100,
    offset: int = 0,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Every meeting in the organisation, for admins only. This is the one
    place admins see meetings they weren't part of — their own Home, Meetings
    and memory chat stay limited to their meetings (see
    `meeting_visibility_clause`). A confidential meeting the admin wasn't in
    is listed without its title and can't be opened or found by its content."""
    limit = max(1, min(limit, 200))
    query = select(Meeting).where(Meeting.deleted_at.is_(None))
    needle = q.strip()
    if needle:
        pattern = f"%{needle}%"
        query = query.where(
            (or_(~Meeting.confidential, meeting_visibility_clause(admin)) & (Meeting.title.ilike(pattern) | Meeting.summary.ilike(pattern)))
            | Meeting.user_id.in_(select(User.id).where(User.name.ilike(pattern) | User.email.ilike(pattern)))
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    meetings = (await db.execute(query.order_by(Meeting.date.desc()).offset(max(0, offset)).limit(limit))).scalars().all()
    ids = [m.id for m in meetings]
    owners = {u.id: u for u in (await db.execute(select(User).where(User.id.in_({m.user_id for m in meetings})))).scalars().all()} if meetings else {}
    counts: dict = {}
    if ids:
        for meeting_id, access, count in (
            await db.execute(
                select(MeetingAttendee.meeting_id, MeetingAttendee.access, func.count())
                .where(MeetingAttendee.meeting_id.in_(ids), MeetingAttendee.user_id.isnot(None))
                .group_by(MeetingAttendee.meeting_id, MeetingAttendee.access)
            )
        ).all():
            counts.setdefault(meeting_id, {})[access] = count
    inside = set(
        (await db.execute(select(Meeting.id).where(Meeting.id.in_(ids), meeting_visibility_clause(admin)))).scalars().all()
    ) if ids else set()
    return {
        "total": total or 0,
        "meetings": [
            {
                "id": str(m.id),
                "title": "Confidential meeting" if m.confidential and m.id not in inside else m.title,
                "confidential": m.confidential,
                "can_open": not m.confidential or m.id in inside,
                "date": m.date.isoformat(),
                "duration_minutes": m.duration_minutes,
                "source": m.source,
                "owner": (owners[m.user_id].name or owners[m.user_id].email) if m.user_id in owners else None,
                "with_access": counts.get(m.id, {}).get("granted", 0),
                "pending_access": counts.get(m.id, {}).get("pending", 0),
            }
            for m in meetings
        ],
    }


@router.get("/ai-costs")
async def admin_ai_costs(
    days: int = 30,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """AI spend from the usage ledger: every call priced in USD and converted
    to INR at the rate in force when it happened."""
    days = max(1, min(days, 365))
    since = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)
    window = AiUsageEvent.occurred_at >= since

    def money(usd, inr) -> dict:
        return {"usd": round(float(usd or 0), 6), "inr": round(float(inr or 0), 4)}

    totals = (
        await db.execute(
            select(func.count(), func.sum(AiUsageEvent.usd_cost), func.sum(AiUsageEvent.inr_cost),
                   func.sum(AiUsageEvent.input_tokens), func.sum(AiUsageEvent.output_tokens),
                   func.sum(AiUsageEvent.cached_tokens), func.sum(AiUsageEvent.audio_seconds)).where(window)
        )
    ).one()

    async def grouped(column):
        rows = (
            await db.execute(
                select(column, func.count(), func.sum(AiUsageEvent.usd_cost), func.sum(AiUsageEvent.inr_cost))
                .where(window).group_by(column).order_by(func.sum(AiUsageEvent.inr_cost).desc())
            )
        ).all()
        return [{"key": str(key) if key is not None else None, "calls": calls, **money(usd, inr)} for key, calls, usd, inr in rows]

    by_user = await grouped(AiUsageEvent.user_id)
    user_ids = [uuid.UUID(row["key"]) for row in by_user if row["key"]]
    names = {str(u.id): u.name or u.email for u in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars()} if user_ids else {}
    for row in by_user:
        row["label"] = names.get(row["key"], "System / no user") if row["key"] else "System / no user"

    day = func.date_trunc("day", AiUsageEvent.occurred_at)
    by_day = [
        {"day": d.date().isoformat(), "calls": calls, **money(usd, inr)}
        for d, calls, usd, inr in (
            await db.execute(
                select(day, func.count(), func.sum(AiUsageEvent.usd_cost), func.sum(AiUsageEvent.inr_cost))
                .where(window).group_by(day).order_by(day)
            )
        ).all()
    ]
    recent = (await db.execute(select(AiUsageEvent).order_by(AiUsageEvent.occurred_at.desc()).limit(40))).scalars().all()
    overrides = usage_ledger._overrides()
    return {
        "days": days,
        "totals": {
            "calls": totals[0],
            **money(totals[1], totals[2]),
            "input_tokens": int(totals[3] or 0),
            "output_tokens": int(totals[4] or 0),
            "cached_tokens": int(totals[5] or 0),
            "audio_minutes": round(float(totals[6] or 0) / 60, 1),
        },
        "by_feature": await grouped(AiUsageEvent.feature),
        "by_model": await grouped(AiUsageEvent.model),
        "by_user": by_user,
        "by_day": by_day,
        "recent": [
            {
                "occurred_at": e.occurred_at.isoformat(),
                "feature": e.feature,
                "model": e.model,
                "input_tokens": e.input_tokens,
                "output_tokens": e.output_tokens,
                "audio_seconds": e.audio_seconds,
                "usd_to_inr": e.usd_to_inr,
                "rate_source": e.rate_source,
                **money(e.usd_cost, e.inr_cost),
            }
            for e in recent
        ],
        "rate_now": await exchange_rate_service.usd_to_inr(),
        "prices": {
            "model_in_use": settings.gemini_model,
            "tokens": {**usage_ledger.default_token_prices(), **{k: v for k, v in overrides.items() if isinstance(v, dict)}},
            "source": usage_ledger.PRICES_SOURCE,
            "audio_per_minute": {k: usage_ledger.audio_price_per_minute(k) for k in usage_ledger.DEFAULT_AUDIO_PRICES},
            "overridden": sorted(overrides),
        },
    }


@router.get("/notetaker")
async def notetaker_overview(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    """Live and queued visits across the organisation, capacity per notetaker
    instance, and why visits failed in the last week."""
    return await notetaker_monitor.overview(db)
