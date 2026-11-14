"""Jira Cloud integration: the admin connection and "send to Jira"."""

import uuid

import urllib.parse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.database.models import AdminAuditEvent, JiraConnection, JiraUserLink, Meeting, MeetingTask, Project, TaskHistory, User
from app.dependencies import get_current_user, is_admin, require_admin, user_can_read_meeting
from app.services import jira_service, privacy_service, secret_box
from app.services.calendar_service import app_url

router = APIRouter(tags=["jira"])


class JiraSettings(BaseModel):
    site_url: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    # Blank on an update keeps the saved token.
    api_token: str | None = Field(default=None, max_length=1000)
    default_project_key: str = Field(min_length=1, max_length=50)
    project_map: dict[str, str] = Field(default_factory=dict)


class JiraProjectSettings(BaseModel):
    default_project_key: str = Field(min_length=1, max_length=50)
    project_map: dict[str, str] = Field(default_factory=dict)
    auto_send: str | None = Field(default=None, pattern="^(off|mapped|all)$")


class PersonLink(BaseModel):
    # None = "this person isn't in Jira".
    account_id: str | None = Field(default=None, max_length=128)


class BulkSend(BaseModel):
    task_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


def _payload(connection: JiraConnection | None) -> dict:
    base = {"oauth_available": jira_service.oauth_available()}
    if connection is None:
        return {**base, "connected": False}
    return {
        **base,
        "connected": True,
        "auth_type": connection.auth_type,
        "site_url": connection.site_url,
        "email": connection.email,
        "account_name": connection.account_name,
        "default_project_key": connection.default_project_key,
        "project_map": connection.project_map or {},
        "auto_send": connection.auto_send,
        "last_synced_at": connection.last_synced_at.isoformat() if connection.last_synced_at else None,
        "last_error": connection.last_error,
    }


@router.get("/api/jira/status")
async def jira_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """What every page needs to show "Send to Jira" and issue links."""
    connection = await jira_service.get_connection(db)
    # Not usable for sending until a default project is picked.
    ready = connection is not None and bool(connection.default_project_key)
    return {"connected": ready, "site_url": connection.site_url if ready else None}


@router.get("/api/admin/jira")
async def get_jira_settings(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    return _payload(await jira_service.get_connection(db))


@router.put("/api/admin/jira")
async def save_jira_settings(
    body: JiraSettings, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    connection = await jira_service.get_connection(db)
    try:
        site = jira_service.normalize_site(body.site_url)
    except jira_service.JiraError as error:
        raise HTTPException(status_code=422, detail=str(error))
    token = (body.api_token or "").strip()
    if not token:
        if connection is None:
            raise HTTPException(status_code=422, detail="Paste the Jira API token")
        token = secret_box.decrypt(connection.api_token_encrypted) or ""
    email = body.email.strip().lower()
    try:
        account_name = await jira_service.verify(site, email, token)
        projects = {p["key"] for p in await jira_service.list_projects(
            None, JiraConnection(auth_type="token", site_url=site, email=email, api_token_encrypted=secret_box.encrypt(token))
        )}
    except jira_service.JiraError as error:
        raise HTTPException(status_code=422, detail=str(error))
    default_key = body.default_project_key.strip().upper()
    project_map = {k: v.strip().upper() for k, v in body.project_map.items() if v and v.strip()}
    unknown = sorted(({default_key} | set(project_map.values())) - projects)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Not Jira projects this account can see: {', '.join(unknown)}")
    if connection is None:
        connection = JiraConnection(id=1, site_url=site, email=email, api_token_encrypted="", default_project_key=default_key)
        db.add(connection)
    connection.auth_type = "token"
    connection.site_url, connection.email = site, email
    connection.api_token_encrypted = secret_box.encrypt(token)
    connection.cloud_id = connection.refresh_token_encrypted = connection.access_token_encrypted = None
    connection.access_token_expires_at = None
    connection.default_project_key = default_key
    connection.project_map = project_map
    connection.account_name = account_name
    connection.connected_by = admin.id
    connection.last_error = None
    db.add(AdminAuditEvent(
        actor_id=admin.id, action="jira.connected", target_type="integration", target_id="jira",
        details={"site_url": site, "email": email, "default_project_key": default_key, "project_map": project_map},
    ))
    await db.commit()
    return _payload(connection)


@router.delete("/api/admin/jira")
async def disconnect_jira(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    """Forget the connection. Issue links on tasks stay, so reconnecting the
    same site picks syncing back up."""
    connection = await jira_service.get_connection(db)
    if connection is not None:
        await db.delete(connection)
        db.add(AdminAuditEvent(actor_id=admin.id, action="jira.disconnected", target_type="integration", target_id="jira", details={}))
        await db.commit()
    return {"connected": False}


@router.get("/api/admin/jira/projects")
async def jira_projects(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    """Both sides of the project mapping."""
    connection = await jira_service.get_connection(db)
    if connection is None:
        raise HTTPException(status_code=409, detail="Connect Jira first")
    try:
        jira = await jira_service.list_projects(db, connection)
    except jira_service.JiraError as error:
        raise HTTPException(status_code=502, detail=str(error))
    charcha = (
        await db.execute(select(Project).where(Project.deleted_at.is_(None)).order_by(Project.name))
    ).scalars().all()
    return {"jira": jira, "charcha": [{"id": str(p.id), "name": p.name} for p in charcha]}


@router.put("/api/admin/jira/projects")
async def save_jira_projects(
    body: JiraProjectSettings, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    """Default project and Charcha → Jira project mapping, for either kind of
    connection (right after Connect with Jira, this is the only step left)."""
    connection = await jira_service.get_connection(db)
    if connection is None:
        raise HTTPException(status_code=409, detail="Connect Jira first")
    try:
        projects = {p["key"] for p in await jira_service.list_projects(db, connection)}
    except jira_service.JiraError as error:
        raise HTTPException(status_code=502, detail=str(error))
    default_key = body.default_project_key.strip().upper()
    project_map = {k: v.strip().upper() for k, v in body.project_map.items() if v and v.strip()}
    unknown = sorted(({default_key} | set(project_map.values())) - projects)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Not Jira projects this account can see: {', '.join(unknown)}")
    connection.default_project_key = default_key
    connection.project_map = project_map
    if body.auto_send is not None:
        connection.auto_send = body.auto_send
    db.add(AdminAuditEvent(
        actor_id=admin.id, action="jira.projects", target_type="integration", target_id="jira",
        details={"default_project_key": default_key, "project_map": project_map, "auto_send": connection.auto_send},
    ))
    await db.commit()
    return _payload(connection)


@router.get("/api/admin/jira/oauth/start")
async def start_jira_oauth(admin: User = Depends(require_admin)) -> dict:
    """Where the Connect with Jira button sends the browser."""
    if not jira_service.oauth_available():
        raise HTTPException(
            status_code=503,
            detail="Connect with Jira isn't set up on this server (ATLASSIAN_CLIENT_ID / ATLASSIAN_CLIENT_SECRET)",
        )
    return {"url": jira_service.authorization_url(jira_service.make_state(admin.id))}


@router.get("/api/jira/oauth/callback", include_in_schema=False)
async def jira_oauth_callback(
    state: str = "", code: str = "", error: str = "", db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    """Atlassian sends the browser here after the consent screen; store the
    connection and go back to Admin → Integrations with the outcome."""
    def back(outcome: str, message: str = "") -> RedirectResponse:
        query = {"tab": "integrations", "jira": outcome}
        if message:
            query["message"] = message[:200]
        return RedirectResponse(app_url(f"/admin?{urllib.parse.urlencode(query)}"), status_code=303)

    if error:
        return back("cancelled" if error == "access_denied" else "error", "" if error == "access_denied" else error)
    try:
        admin_id = jira_service.read_state(state)
        tokens = await jira_service.exchange_code(code)
        sites = await jira_service.accessible_sites(tokens["access_token"])
    except jira_service.JiraError as failure:
        return back("error", str(failure))
    admin = await db.get(User, admin_id)
    if admin is None or admin.status != "active" or not is_admin(admin):
        return back("error", "Only a Charcha admin can connect Jira")
    if not sites:
        return back("error", "That Atlassian account has no Jira site Charcha can write to")
    site = sites[0]

    connection = await jira_service.get_connection(db)
    if connection is None:
        connection = JiraConnection(id=1, site_url=site["url"])
        db.add(connection)
    if connection.site_url.rstrip("/") != site["url"].rstrip("/"):
        # A different site: the old project choices don't apply there.
        connection.default_project_key, connection.project_map = None, {}
    connection.auth_type = "oauth"
    connection.site_url = site["url"].rstrip("/")
    connection.cloud_id = site["id"]
    connection.email = connection.api_token_encrypted = None
    jira_service.store_tokens(connection, tokens)
    connection.account_name = site.get("name")
    connection.connected_by = admin.id
    connection.last_error = None
    db.add(AdminAuditEvent(
        actor_id=admin.id, action="jira.connected", target_type="integration", target_id="jira",
        details={"site_url": connection.site_url, "auth": "oauth", "sites_offered": [s["url"] for s in sites]},
    ))
    await db.commit()
    return back("connected")


@router.post("/api/admin/jira/sync")
async def sync_jira_now(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    if await jira_service.get_connection(db) is None:
        raise HTTPException(status_code=409, detail="Connect Jira first")
    changed = await jira_service.sync_once(db)
    return {"changed": changed, **_payload(await jira_service.get_connection(db))}


# ---------------------------------------------------------------- people

async def _people_payload(db: AsyncSession, jira_users: list[dict]) -> dict:
    links = {link.user_id: link for link in (await db.execute(select(JiraUserLink))).scalars().all()}
    people = (await db.execute(select(User).where(User.status == "active").order_by(User.name, User.email))).scalars().all()
    return {
        "jira_users": sorted(
            ({"account_id": u["accountId"], "name": u.get("displayName"), "email": u.get("emailAddress")} for u in jira_users),
            key=lambda u: (u["name"] or "").lower(),
        ),
        "people": [
            {
                "user_id": str(p.id),
                "name": p.name or p.email,
                "email": p.email,
                "account_id": links[p.id].account_id if p.id in links else None,
                "jira_name": links[p.id].display_name if p.id in links else None,
                # "email" | "name" (auto) | "manual" | None (no match yet)
                "matched_by": links[p.id].matched_by if p.id in links else None,
            }
            for p in people
        ],
    }


@router.get("/api/admin/jira/people")
async def jira_people(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    """Charcha people and the Jira user each one is (auto-matching first)."""
    connection = await jira_service.get_connection(db)
    if connection is None:
        raise HTTPException(status_code=409, detail="Connect Jira first")
    try:
        async with await jira_service.open_client(db, connection) as client:
            users, newly_linked = await jira_service.match_people(db, client)
    except jira_service.JiraError as error:
        raise HTTPException(status_code=502, detail=str(error))
    if newly_linked:
        await db.commit()
    return await _people_payload(db, users)


@router.put("/api/admin/jira/people/{user_id}")
async def set_jira_person(
    user_id: uuid.UUID, body: PersonLink, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    """Pin who someone is in Jira (or that they aren't); auto-matching never
    overrides it."""
    person = await db.get(User, user_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    connection = await jira_service.get_connection(db)
    if connection is None:
        raise HTTPException(status_code=409, detail="Connect Jira first")
    try:
        async with await jira_service.open_client(db, connection) as client:
            users = await jira_service.jira_users(client)
    except jira_service.JiraError as error:
        raise HTTPException(status_code=502, detail=str(error))
    chosen = next((u for u in users if u["accountId"] == body.account_id), None) if body.account_id else None
    if body.account_id and chosen is None:
        raise HTTPException(status_code=422, detail="That Jira user wasn't found")
    if body.account_id:
        # One Jira user is one Charcha person.
        other = (
            await db.execute(select(JiraUserLink).where(JiraUserLink.account_id == body.account_id, JiraUserLink.user_id != user_id))
        ).scalar_one_or_none()
        if other is not None:
            await db.delete(other)
            await db.flush()
    link = await db.get(JiraUserLink, user_id) or JiraUserLink(user_id=user_id, matched_by="manual")
    link.account_id = body.account_id
    link.display_name = chosen.get("displayName") if chosen else None
    link.matched_by = "manual"
    db.add(link)
    db.add(AdminAuditEvent(
        actor_id=admin.id, action="jira.person", target_type="user", target_id=str(user_id),
        details={"account_id": body.account_id, "jira_name": link.display_name},
    ))
    await db.flush()
    await db.commit()
    return await _people_payload(db, users)


@router.delete("/api/admin/jira/people/{user_id}")
async def reset_jira_person(user_id: uuid.UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    """Back to automatic matching for this person."""
    link = await db.get(JiraUserLink, user_id)
    if link is not None:
        await db.delete(link)
        await db.commit()
    return await jira_people(admin, db)


# ---------------------------------------------------------------- activity

@router.get("/api/admin/jira/activity")
async def jira_activity(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    """How much is linked, what Jira changed lately, and what's failing."""
    live = (MeetingTask.deleted_at.is_(None), MeetingTask.jira_issue_key.isnot(None))
    linked = await db.scalar(select(func.count()).select_from(MeetingTask).where(*live)) or 0
    open_linked = await db.scalar(select(func.count()).select_from(MeetingTask).where(*live, MeetingTask.status != "done")) or 0
    problems = (
        await db.execute(
            select(MeetingTask).where(MeetingTask.deleted_at.is_(None), MeetingTask.jira_error.isnot(None))
            .order_by(MeetingTask.updated_at.desc()).limit(20)
        )
    ).scalars().all()
    recent = (
        await db.execute(
            select(TaskHistory, MeetingTask.description, MeetingTask.jira_issue_key, MeetingTask.meeting_id)
            .join(MeetingTask, TaskHistory.task_id == MeetingTask.id)
            .where(TaskHistory.source == "jira")
            .order_by(TaskHistory.changed_at.desc())
            .limit(20)
        )
    ).all()
    return {
        "linked": linked,
        "open_linked": open_linked,
        "problems": [
            {"task_id": str(t.id), "description": t.description, "issue_key": t.jira_issue_key, "error": t.jira_error, "meeting_id": str(t.meeting_id)}
            for t in problems
        ],
        "recent": [
            {
                "task_id": str(entry.task_id), "description": description, "issue_key": key, "meeting_id": str(meeting_id),
                "field": entry.field, "old_value": entry.old_value, "new_value": entry.new_value,
                "changed_at": entry.changed_at.isoformat(),
            }
            for entry, description, key, meeting_id in recent
        ],
    }


# ---------------------------------------------------------------- sending

@router.post("/api/tasks/jira/bulk")
async def send_selected_to_jira(body: BulkSend, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """The Tasks page's "Send selected to Jira". Only tasks this person can
    see; ones already in Jira just return their key."""
    from app.routes.tasks import _get_owned_task

    tasks = []
    for task_id in dict.fromkeys(body.task_ids):
        try:
            task, _ = await _get_owned_task(task_id, user, db)
            tasks.append(task)
        except HTTPException:
            continue
    created, failed = await jira_service.send_tasks(db, tasks)
    return {"created": created, "failed": failed}


@router.delete("/api/tasks/{task_id}/jira")
async def unlink_task_from_jira(task_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """Stop syncing this task. The Jira issue itself is left alone."""
    from app.routes.tasks import _get_owned_task

    task, _ = await _get_owned_task(task_id, user, db)
    task.jira_issue_key = task.jira_status = task.jira_error = None
    task.jira_snapshot = None
    await db.commit()
    return {"id": str(task.id), "jira_issue_key": None}


@router.post("/api/meetings/{meeting_id}/jira")
async def send_meeting_tasks_to_jira(
    meeting_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Every open task of the meeting that isn't in Jira yet. Tasks that fail
    are reported in `failed`; the rest are still sent."""
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, meeting_id):
        raise HTTPException(status_code=404, detail="Meeting not found")
    tasks = (
        await db.execute(
            select(MeetingTask)
            .where(
                MeetingTask.meeting_id == meeting_id,
                MeetingTask.deleted_at.is_(None),
                MeetingTask.jira_issue_key.is_(None),
                MeetingTask.status != "done",
            )
            .order_by(MeetingTask.created_at)
        )
    ).scalars().all()
    # A task held from an owner who wasn't in the meeting waits for the
    # recorder or organizer — sending it would assign it to them in Jira.
    inside = await privacy_service.owners_in_meeting(db, list(tasks))
    held = {str(t.id) for t in tasks if privacy_service.owner_access(t, inside) == "held"}
    created, failed = await jira_service.send_tasks(db, [t for t in tasks if str(t.id) not in held])
    failed.update({
        task_id: "Its owner wasn't in this meeting — send it to them from the task first"
        for task_id in held
    })
    if failed and not created:
        raise HTTPException(status_code=502, detail=next(iter(failed.values())))
    return {"created": created, "failed": failed}
