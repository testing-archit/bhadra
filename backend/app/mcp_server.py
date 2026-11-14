"""Charcha as an MCP server, so Claude (Desktop, Code, claude.ai) and other
assistants can read a person's meetings, tasks and decisions and ask memory.

Mounted inside the API at /api/mcp (streamable HTTP). Each person creates a
connector token in Settings: a JWT with purpose "mcp" that the regular API
refuses (get_current_user rejects any token with a purpose) and this server
accepts. Every tool runs as that person and goes through the same access
rules as the web app, so a connector can never read more than they can.
"""
import asyncio
import datetime
import uuid

import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from sqlalchemy import or_, select

from app.config import settings
from app.database.db import async_session
from app.database.models import Decision, Meeting, MeetingTask, Risk, User
from app.dependencies import JWT_ALGORITHM, user_can_read_meeting, visible_meeting_ids

CONNECTOR_PURPOSE = "mcp"
CONNECTOR_DAYS = 90
MCP_PATH = "/api/mcp"


def public_base_url() -> str:
    return (settings.public_api_url or settings.public_app_url or "http://localhost:8000").rstrip("/")


def connector_url() -> str:
    return f"{public_base_url()}{MCP_PATH}"


def create_connector_token(user: User) -> tuple[str, datetime.datetime]:
    now = datetime.datetime.now(datetime.UTC)
    expires = now + datetime.timedelta(days=CONNECTOR_DAYS)
    payload = {"sub": str(user.id), "email": user.email, "purpose": CONNECTOR_PURPOSE, "iat": int(now.timestamp()), "exp": expires}
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM), expires


class ConnectorTokenVerifier:
    """Accepts only connector tokens of active people; a password change
    (sessions_valid_after) revokes them like any session."""

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            payload = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM], options={"require": ["sub", "exp"]})
            if payload.get("purpose") != CONNECTOR_PURPOSE:
                return None
            user_id = uuid.UUID(payload["sub"])
        except (jwt.PyJWTError, ValueError, TypeError):
            return None
        async with async_session() as db:
            user = await db.get(User, user_id)
        if user is None or user.status != "active":
            return None
        if user.sessions_valid_after is not None and payload.get("iat", 0) < int(user.sessions_valid_after.timestamp()):
            return None
        return AccessToken(
            token=token, client_id="charcha-connector", scopes=["charcha"], expires_at=int(payload["exp"]), subject=str(user.id)
        )


server = MCPServer(
    name="Charcha",
    title="Charcha meeting memory",
    instructions=(
        "Charcha holds this person's meetings: summaries, transcripts, tasks, decisions and risks, much of it in "
        "Hindi, English or Hinglish. Use search_meetings or list_decisions to find things, get_meeting for detail, "
        "and ask_memory for questions that span meetings. Cite meeting titles and dates in answers."
    ),
    token_verifier=ConnectorTokenVerifier(),
    auth=AuthSettings(
        issuer_url=public_base_url(),
        resource_server_url=connector_url(),
        required_scopes=["charcha"],
        validate_token_resource=False,
    ),
)

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)


async def _user(db) -> User:
    token = get_access_token()
    if token is None or not token.subject:
        raise PermissionError("Not signed in to Charcha")
    user = await db.get(User, uuid.UUID(token.subject))
    if user is None or user.status != "active":
        raise PermissionError("This Charcha account is not active")
    return user


def _date(value) -> str | None:
    return value.date().isoformat() if value else None


@server.tool(title="Search meetings", annotations=READ)
async def search_meetings(query: str = "", limit: int = 10) -> list[dict]:
    """Meetings this person can read, newest first. `query` matches the title or summary (any language)."""
    limit = max(1, min(limit, 50))
    async with async_session() as db:
        user = await _user(db)
        statement = select(Meeting).where(Meeting.id.in_(visible_meeting_ids(user)))
        if query.strip():
            pattern = f"%{query.strip()}%"
            statement = statement.where(or_(Meeting.title.ilike(pattern), Meeting.summary.ilike(pattern)))
        meetings = (await db.scalars(statement.order_by(Meeting.date.desc()).limit(limit))).all()
        return [
            {"id": str(m.id), "title": m.title, "date": _date(m.date), "source": m.source, "summary": (m.summary or "")[:600]}
            for m in meetings
        ]


@server.tool(title="Get a meeting", annotations=READ)
async def get_meeting(meeting_id: str) -> dict:
    """One meeting's summary, tasks, decisions and risks."""
    async with async_session() as db:
        user = await _user(db)
        try:
            mid = uuid.UUID(meeting_id)
        except ValueError:
            return {"error": "Not a meeting id"}
        meeting = await db.get(Meeting, mid)
        if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, mid):
            return {"error": "Meeting not found"}
        tasks = (await db.scalars(select(MeetingTask).where(MeetingTask.meeting_id == mid, MeetingTask.deleted_at.is_(None)))).all()
        decisions = (await db.scalars(select(Decision).where(Decision.meeting_id == mid, Decision.deleted_at.is_(None)))).all()
        risks = (await db.scalars(select(Risk).where(Risk.meeting_id == mid, Risk.deleted_at.is_(None)))).all()
        return {
            "id": str(meeting.id),
            "title": meeting.title,
            "date": _date(meeting.date),
            "duration_minutes": meeting.duration_minutes,
            "summary": meeting.summary,
            "tasks": [{"id": str(t.id), "task": t.description, "owner": t.owner, "deadline": t.deadline, "status": t.status} for t in tasks],
            "decisions": [{"decision": d.decision, "reason": d.reason, "alternatives": d.alternatives or [], "reverses": d.conflict_note} for d in decisions],
            "risks": [{"risk": r.description, "severity": r.severity} for r in risks],
        }


@server.tool(title="List my tasks", annotations=READ)
async def list_my_tasks(include_done: bool = False, limit: int = 30) -> list[dict]:
    """Tasks assigned to this person in meetings they can read, soonest due first."""
    limit = max(1, min(limit, 100))
    async with async_session() as db:
        user = await _user(db)
        names = [n for n in {user.name, (user.name or "").split(" ")[0], user.email.split("@")[0]} if n]
        statement = (
            select(MeetingTask, Meeting.title)
            .join(Meeting, Meeting.id == MeetingTask.meeting_id)
            .where(
                MeetingTask.deleted_at.is_(None),
                Meeting.id.in_(visible_meeting_ids(user)),
                or_(MeetingTask.owner_user_id == user.id, *[MeetingTask.owner.ilike(n) for n in names]),
            )
        )
        if not include_done:
            statement = statement.where(MeetingTask.status != "done")
        rows = (await db.execute(statement.order_by(MeetingTask.due_date.asc().nulls_last()).limit(limit))).all()
        return [
            {"id": str(t.id), "task": t.description, "deadline": t.deadline, "due_date": t.due_date.isoformat() if t.due_date else None, "status": t.status, "priority": t.priority, "meeting": title}
            for t, title in rows
        ]


@server.tool(title="List decisions", annotations=READ)
async def list_decisions(limit: int = 20) -> list[dict]:
    """Recent decisions from meetings this person can read, with the reason and rejected alternatives."""
    limit = max(1, min(limit, 100))
    async with async_session() as db:
        user = await _user(db)
        rows = (await db.execute(
            select(Decision, Meeting.title, Meeting.date)
            .join(Meeting, Meeting.id == Decision.meeting_id)
            .where(Decision.deleted_at.is_(None), Meeting.id.in_(visible_meeting_ids(user)))
            .order_by(Meeting.date.desc())
            .limit(limit)
        )).all()
        return [
            {"decision": d.decision, "reason": d.reason, "alternatives": d.alternatives or [], "reverses": d.conflict_note, "meeting": title, "date": _date(date)}
            for d, title, date in rows
        ]


@server.tool(title="Ask meeting memory", annotations=READ)
async def ask_memory(question: str) -> dict:
    """Answers a question from this person's recent meetings, with the meetings it came from."""
    from app.routes.chat import _meeting_payload, _recent_readable_meetings
    from app.services import memory_retriever

    async with async_session() as db:
        user = await _user(db)
        meetings = await _recent_readable_meetings(db, user)
        if not meetings:
            return {"answer": "There are no meetings in Charcha yet that this person can read.", "meetings": []}
        payload = [await _meeting_payload(db, meeting) for meeting in meetings]
    result = await asyncio.to_thread(memory_retriever.answer_query_for_meetings, question, payload, [])
    return {"answer": result["answer"], "meetings": [{"title": m["title"], "date": m["date"][:10]} for m in payload]}


@server.tool(
    title="Create a task",
    annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False),
)
async def create_task(description: str, owner: str = "", deadline: str = "") -> dict:
    """Adds a task to this person's Charcha task list (like adding one by hand)."""
    from app.routes.tasks import TaskCreate
    from app.routes.tasks import create_task as create_task_route

    async with async_session() as db:
        user = await _user(db)
        created = await create_task_route(
            TaskCreate(description=description, owner=owner or None, deadline=deadline or None), user=user, db=db
        )
    return {"id": created.get("id"), "task": created.get("description"), "owner": created.get("owner"), "deadline": created.get("deadline")}


def http_app():
    """The ASGI app for app.mount(MCP_PATH, ...). Host checks are off: the API
    runs behind nginx on a public address, and every request needs a token."""
    return server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
