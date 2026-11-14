"""Jira Cloud: send Charcha tasks to Jira and keep their status in step.

One company connection (JiraConnection, id=1), set up in Admin →
Integrations, either way:
* "Connect with Jira" (auth_type "oauth"): Atlassian OAuth 2.0 (3LO) with the
  app in ATLASSIAN_CLIENT_ID/SECRET. Calls go to
  api.atlassian.com/ex/jira/{cloud_id}; the access token (1 h) is refreshed
  with a rotating refresh token, which lapses only after 90 idle days — the
  2-minute sync keeps it alive.
* API token (auth_type "token"): a service account's email + token, basic
  auth against the site itself.
Works on Jira Free.

* Create: one click per task, a bulk selection, every open task of a
  meeting, or automatically when notes are ready (`auto_send`). Project from
  `project_map`, else the default; a subtask whose parent is in Jira becomes
  a Jira sub-task. The description carries the transcript quote and a link
  back to the meeting.
* People: Charcha users are linked to Jira users (JiraUserLink) by email, then
  exact display name — Jira Free usually hides emails — and admins can fix
  links by hand. Links drive assignee <-> owner and comment authors.
* Two-way fields: summary <-> task text, assignee <-> owner, due date,
  priority, status category. Each task keeps a snapshot of the issue as last
  synced; on a poll, only fields that differ from it (changed *in Jira*) are
  copied into Charcha, so neither side overwrites what the other didn't
  touch. Charcha edits are pushed at once (`push_changes`); failures land in
  `tasks.jira_error`, and an issue deleted in Jira unlinks the task.
* Comments both ways, deduplicated by Jira comment id.
* A loop (app.main lifespan, Postgres advisory lock, one process) polls
  every SYNC_SECONDS: one JQL search (`labels = charcha AND updated >= -Nm`)
  returning fields and comments. Polling rather than webhooks: no setup in
  Jira, works on every plan.
"""

import asyncio
import datetime
import logging
import re
import uuid

import secrets
import urllib.parse

import httpx
import jwt
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.db import async_session, engine
from app.database.models import JiraConnection, JiraUserLink, Meeting, MeetingAttendee, MeetingTask, TaskComment, TaskHistory, User
from app.services import privacy_service, secret_box

logger = logging.getLogger(__name__)

ADVISORY_LOCK_KEY = 7_311_204_120
SYNC_SECONDS = 120
# Never look further back than this, however long the loop was down.
MAX_LOOKBACK_MINUTES = 7 * 24 * 60
SUMMARY_LIMIT = 250

# Charcha status <-> Jira status category key.
TO_JIRA = {"pending": "new", "in_progress": "indeterminate", "done": "done"}
FROM_JIRA = {"new": "pending", "indeterminate": "in_progress", "done": "done"}

SITE_RE = re.compile(r"^https://[a-z0-9][a-z0-9-]*\.atlassian\.net$")

AUTHORIZE_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"
API_GATEWAY = "https://api.atlassian.com/ex/jira"
# Create/transition/search issues, look up assignees, and stay connected.
SCOPES = "read:jira-work write:jira-work read:jira-user offline_access"
# Refresh this long before the access token actually expires.
REFRESH_EARLY = datetime.timedelta(minutes=2)


class JiraError(RuntimeError):
    pass


class JiraNotFound(JiraError):
    """The issue (or project) doesn't exist — e.g. deleted in Jira."""


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def normalize_site(raw: str) -> str:
    """"acme.atlassian.net/jira/…" → "https://acme.atlassian.net".
    Only Atlassian Cloud sites: the backend calls this URL with the token."""
    value = (raw or "").strip().lower()
    value = re.sub(r"^https?://", "", value).split("/")[0]
    site = f"https://{value}"
    if not SITE_RE.match(site):
        raise JiraError("Enter your Jira Cloud address, like yourcompany.atlassian.net")
    return site


def _client(site: str, email: str, token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=site, auth=(email, token), timeout=20.0, headers={"Accept": "application/json"}
    )


async def _call(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> dict:
    response = await client.request(method, path, **kwargs)
    if response.status_code == 401:
        raise JiraError(
            "Jira rejected the email or API token. Check the token was made with plain \"Create API token\" "
            "(not \"with scopes\") while signed in as this email, and that your browser didn't fill in a saved password"
        )
    if response.status_code == 404:
        raise JiraNotFound(f"Jira says it doesn't exist (404): {response.text[:200]}")
    if response.status_code == 403:
        raise JiraError("The Jira account doesn't have permission for this")
    if not response.is_success:
        raise JiraError(f"Jira error {response.status_code}: {response.text[:300]}")
    return response.json() if response.content else {}


async def get_connection(db: AsyncSession) -> JiraConnection | None:
    return await db.get(JiraConnection, 1)


# ---------------------------------------------------------------- OAuth

def oauth_available() -> bool:
    return bool(settings.atlassian_client_id and settings.atlassian_client_secret and settings.public_api_url)


def redirect_uri() -> str:
    return f"{settings.public_api_url.rstrip('/')}/api/jira/oauth/callback"


def make_state(user_id: uuid.UUID) -> str:
    # `purpose` keeps it from ever being accepted as a session token.
    return jwt.encode(
        {"sub": str(user_id), "purpose": "jira-link", "nonce": secrets.token_urlsafe(8),
         "exp": _now() + datetime.timedelta(minutes=15)},
        settings.jwt_secret,
        algorithm="HS256",
    )


def read_state(state: str) -> uuid.UUID:
    try:
        payload = jwt.decode(state, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as error:
        raise JiraError("The Jira sign-in took too long. Try Connect with Jira again.") from error
    if payload.get("purpose") != "jira-link":
        raise JiraError("Invalid Jira sign-in request")
    return uuid.UUID(payload["sub"])


def authorization_url(state: str) -> str:
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "audience": "api.atlassian.com",
        "client_id": settings.atlassian_client_id,
        "scope": SCOPES,
        "redirect_uri": redirect_uri(),
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    })


async def _token_request(body: dict) -> dict:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(TOKEN_URL, json={
            "client_id": settings.atlassian_client_id,
            "client_secret": settings.atlassian_client_secret,
            **body,
        })
    if not response.is_success:
        raise JiraError(f"Atlassian refused the sign-in ({response.status_code}): {response.text[:200]}")
    tokens = response.json()
    if not tokens.get("refresh_token"):
        raise JiraError("Atlassian didn't return a refresh token — the app needs the offline_access scope")
    return tokens


async def exchange_code(code: str) -> dict:
    return await _token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri()})


async def accessible_sites(access_token: str) -> list[dict]:
    """Jira sites the signed-in account granted access to: [{id, url, name}]."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(RESOURCES_URL, headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"})
    if not response.is_success:
        raise JiraError(f"Couldn't list your Jira sites ({response.status_code})")
    return [site for site in response.json() if "write:jira-work" in (site.get("scopes") or [])]


def store_tokens(connection: JiraConnection, tokens: dict) -> None:
    connection.access_token_encrypted = secret_box.encrypt(tokens["access_token"])
    connection.access_token_expires_at = _now() + datetime.timedelta(seconds=int(tokens.get("expires_in", 3600)))
    # Rotating refresh tokens: each refresh hands back a new one.
    connection.refresh_token_encrypted = secret_box.encrypt(tokens["refresh_token"])


async def _oauth_access_token(db: AsyncSession, connection: JiraConnection) -> str:
    token = secret_box.decrypt(connection.access_token_encrypted or "")
    expires = connection.access_token_expires_at
    if token and expires and expires - REFRESH_EARLY > _now():
        return token
    # One refresh at a time: the old refresh token stops working once used.
    locked = (
        await db.execute(select(JiraConnection).where(JiraConnection.id == connection.id).with_for_update())
    ).scalar_one()
    token = secret_box.decrypt(locked.access_token_encrypted or "")
    if token and locked.access_token_expires_at and locked.access_token_expires_at - REFRESH_EARLY > _now():
        await db.commit()
        return token
    refresh = secret_box.decrypt(locked.refresh_token_encrypted or "")
    if not refresh:
        raise JiraError("The Jira connection has expired — an admin needs to Connect with Jira again")
    try:
        tokens = await _token_request({"grant_type": "refresh_token", "refresh_token": refresh})
    except JiraError as error:
        raise JiraError(f"The Jira connection has expired — an admin needs to Connect with Jira again ({error})") from error
    store_tokens(locked, tokens)
    await db.commit()
    return tokens["access_token"]


async def open_client(db: AsyncSession | None, connection: JiraConnection) -> httpx.AsyncClient:
    """An HTTP client for this connection's Jira REST API (/rest/api/3/...)."""
    if connection.auth_type == "oauth":
        if db is None:
            raise JiraError("An OAuth Jira connection needs a database session")
        token = await _oauth_access_token(db, connection)
        return httpx.AsyncClient(
            base_url=f"{API_GATEWAY}/{connection.cloud_id}",
            timeout=20.0,
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        )
    token = secret_box.decrypt(connection.api_token_encrypted or "")
    if not token:
        raise JiraError("The saved Jira token can't be read any more — reconnect Jira in Admin")
    return _client(connection.site_url, connection.email or "", token)


# ---------------------------------------------------------------- setup

async def verify(site: str, email: str, token: str) -> str:
    """The Jira account's display name, or JiraError."""
    async with _client(site, email, token) as client:
        me = await _call(client, "GET", "/rest/api/3/myself")
    return me.get("displayName") or email


async def list_projects(db: AsyncSession | None, connection: JiraConnection) -> list[dict]:
    projects: list[dict] = []
    async with await open_client(db, connection) as client:
        start = 0
        while True:
            page = await _call(client, "GET", "/rest/api/3/project/search", params={"startAt": start, "maxResults": 50})
            projects += [{"key": p["key"], "name": p["name"]} for p in page.get("values", [])]
            if page.get("isLast", True):
                return sorted(projects, key=lambda p: p["name"].lower())
            start += len(page.get("values", [])) or 50


# ---------------------------------------------------------------- people

async def jira_users(client: httpx.AsyncClient) -> list[dict]:
    """Active human Jira users: [{accountId, displayName, emailAddress?}]."""
    users: list[dict] = []
    start = 0
    while True:
        page = await _call(client, "GET", "/rest/api/3/users/search", params={"startAt": start, "maxResults": 100})
        if not isinstance(page, list) or not page:
            break
        users += [u for u in page if u.get("accountType") == "atlassian" and u.get("active")]
        if len(page) < 100:
            break
        start += len(page)
    return users


def _norm(value: str | None) -> str:
    return " ".join((value or "").lower().split())


async def match_people(db: AsyncSession, client: httpx.AsyncClient) -> tuple[list[dict], list[uuid.UUID]]:
    """Auto-links Charcha people to Jira users — email first, then an exact,
    unambiguous display name — without touching manual links. Returns the
    Jira users (for the admin picker) and the people newly linked. Commits."""
    users = await jira_users(client)
    by_email = {_norm(u.get("emailAddress")): u for u in users if u.get("emailAddress")}
    names: dict[str, list[dict]] = {}
    for u in users:
        names.setdefault(_norm(u.get("displayName")), []).append(u)
    links = {link.user_id: link for link in (await db.execute(select(JiraUserLink))).scalars().all()}
    taken = {link.account_id for link in links.values() if link.account_id}
    people = (await db.execute(select(User).where(User.status == "active"))).scalars().all()
    newly_linked: list[uuid.UUID] = []
    for person in people:
        link = links.get(person.id)
        if link is not None and link.matched_by == "manual":
            continue
        match, how = by_email.get(_norm(person.email)), "email"
        if match is None and person.name:
            candidates = names.get(_norm(person.name), [])
            match, how = (candidates[0], "name") if len(candidates) == 1 else (None, "")
        if match is None or (match["accountId"] in taken and (link is None or link.account_id != match["accountId"])):
            continue
        if link is None:
            link = JiraUserLink(user_id=person.id, matched_by=how)
            db.add(link)
        if link.account_id is None:
            newly_linked.append(person.id)
        link.account_id, link.display_name, link.matched_by = match["accountId"], match.get("displayName"), how
        taken.add(match["accountId"])
    await db.commit()
    return users, newly_linked


async def _account_for_user(db: AsyncSession, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    link = await db.get(JiraUserLink, user_id)
    return link.account_id if link else None


async def _user_for_account(db: AsyncSession, account_id: str | None) -> User | None:
    if not account_id:
        return None
    link = (await db.execute(select(JiraUserLink).where(JiraUserLink.account_id == account_id))).scalar_one_or_none()
    return await db.get(User, link.user_id) if link else None


async def _owner_user(db: AsyncSession, task: MeetingTask) -> User | None:
    """The Charcha person who owns the task: the resolved owner, else the
    owner's name when exactly one active person has it."""
    if task.owner_user_id:
        return await db.get(User, task.owner_user_id)
    if not (task.owner or "").strip():
        return None
    matches = (
        await db.execute(select(User).where(func.lower(User.name) == task.owner.strip().lower(), User.status == "active"))
    ).scalars().all()
    return matches[0] if len(matches) == 1 else None


# ---------------------------------------------------------------- access

# The per-person container for hand-made tasks (app/routes/tasks.py) isn't a
# meeting anyone should be let into because one of its tasks is in Jira.
MANUAL_TASKS_MEETING_TITLE = "Manually Added Tasks"


def _is_placeholder(meeting: Meeting | None) -> bool:
    return meeting is not None and meeting.title == MANUAL_TASKS_MEETING_TITLE and not meeting.source


# ---------------------------------------------------------------- issue content

_issue_types: dict[tuple[str, bool], str] = {}

# Charcha priority <-> Jira priority name.
PRIORITY_TO_JIRA = {"high": "High", "medium": "Medium", "low": "Low"}
PRIORITY_FROM_JIRA = {"highest": "High", "high": "High", "medium": "Medium", "low": "Low", "lowest": "Low"}


async def _issue_type_id(client: httpx.AsyncClient, project_key: str, subtask: bool = False) -> str:
    key = (project_key, subtask)
    if key not in _issue_types:
        meta = await _call(client, "GET", f"/rest/api/3/issue/createmeta/{project_key}/issuetypes")
        types = [t for t in meta.get("issueTypes", meta.get("values", [])) if bool(t.get("subtask")) == subtask]
        if not types:
            raise JiraError(f"Jira project {project_key} has no {'sub-task' if subtask else 'issue'} type Charcha can create")
        chosen = next((t for t in types if t.get("name", "").lower() == "task"), types[0])
        _issue_types[key] = chosen["id"]
    return _issue_types[key]


def _paragraph(*parts: dict) -> dict:
    return {"type": "paragraph", "content": [p for p in parts if p.get("text")]}


def _text(value: str, link: str | None = None, strong: bool = False, em: bool = False) -> dict:
    node: dict = {"type": "text", "text": value}
    marks = []
    if link:
        marks.append({"type": "link", "attrs": {"href": link}})
    if strong:
        marks.append({"type": "strong"})
    if em:
        marks.append({"type": "em"})
    if marks:
        node["marks"] = marks
    return node


def _quote(evidence: list[dict] | None) -> str | None:
    for item in evidence or []:
        excerpt = (item.get("excerpt") or "").strip()
        if excerpt and item.get("verified", True):
            return excerpt
    return None


def _description(task: MeetingTask, meeting: Meeting | None, owner_unassigned: str | None) -> dict:
    """The issue body: the task, who/when if Jira can't hold it, the line of
    the transcript it came from, and a link back to the meeting."""
    from app.services.calendar_service import app_url

    blocks = [_paragraph(_text(task.description))]
    if owner_unassigned:
        blocks.append(_paragraph(_text("Owner: ", strong=True), _text(owner_unassigned)))
    if task.deadline and not task.due_date:
        blocks.append(_paragraph(_text("Due: ", strong=True), _text(task.deadline)))
    quote = _quote(task.evidence)
    if quote:
        blocks.append({"type": "blockquote", "content": [_paragraph(_text(f"“{quote}”", em=True))]})
    if meeting is not None and meeting.title and not _is_placeholder(meeting):
        when = meeting.date.strftime("%d %b %Y") if meeting.date else ""
        blocks.append(
            _paragraph(
                _text("From the meeting "),
                _text(meeting.title, link=app_url(f"/meetings/{meeting.id}?tab=actions")),
                _text(f" ({when}) in Charcha." if when else " in Charcha."),
            )
        )
    return {"type": "doc", "version": 1, "content": blocks}


def _adf_text(node) -> str:
    """Plain text of an Atlassian Document Format body (Jira comments)."""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return node.get("text", "")
    if node.get("type") == "hardBreak":
        return "\n"
    if node.get("type") == "mention":
        return (node.get("attrs") or {}).get("text", "")
    inner = "".join(_adf_text(child) for child in node.get("content", []))
    return inner + ("\n" if node.get("type") in ("paragraph", "heading", "listItem", "blockquote", "codeBlock") else "")


def project_key_for(connection: JiraConnection, task: MeetingTask) -> str | None:
    mapped = (connection.project_map or {}).get(str(task.project_id)) if task.project_id else None
    return mapped or connection.default_project_key


def issue_url(connection: JiraConnection | None, key: str | None) -> str | None:
    return f"{connection.site_url}/browse/{key}" if connection and key else None


def _snapshot(fields: dict) -> dict:
    """The fields Charcha mirrors, from a Jira issue's `fields`."""
    return {
        "summary": " ".join((fields.get("summary") or "").split()),
        "assignee": (fields.get("assignee") or {}).get("accountId"),
        "duedate": fields.get("duedate"),
        "priority": (fields.get("priority") or {}).get("name"),
        "category": ((fields.get("status") or {}).get("statusCategory") or {}).get("key"),
    }


# ---------------------------------------------------------------- create

async def create_issue(db: AsyncSession, task: MeetingTask) -> str:
    """Creates the Jira issue for `task` (idempotent: an already linked task
    returns its key) and records the link and snapshot. A Charcha subtask
    whose parent is already in Jira becomes a Jira sub-task. Commits."""
    if task.jira_issue_key:
        return task.jira_issue_key
    connection = await get_connection(db)
    if connection is None:
        raise JiraError("Jira isn't connected — an admin can connect it in Admin → Integrations")
    if not connection.default_project_key:
        raise JiraError("Jira is connected but has no default project yet — an admin can pick one in Admin → Integrations")
    meeting = await db.get(Meeting, task.meeting_id)
    if meeting is not None and meeting.confidential:
        raise JiraError("This meeting is confidential, so its tasks aren't sent to Jira")
    parent = await db.get(MeetingTask, task.parent_task_id) if task.parent_task_id else None
    parent_key = parent.jira_issue_key if parent is not None else None
    # A sub-task lives in its parent's project.
    project_key = parent_key.rsplit("-", 1)[0] if parent_key else project_key_for(connection, task)
    owner = await _owner_user(db, task)
    async with await open_client(db, connection) as client:
        account_id = await _account_for_user(db, owner.id if owner else None)
        summary = " ".join(task.description.split())[:SUMMARY_LIMIT]
        fields: dict = {
            "project": {"key": project_key},
            "issuetype": {"id": await _issue_type_id(client, project_key, subtask=bool(parent_key))},
            "summary": summary,
            "description": _description(task, meeting, None if account_id else (task.owner or None)),
            "labels": ["charcha"],
        }
        if parent_key:
            fields["parent"] = {"key": parent_key}
        optional: dict = {}
        if account_id:
            optional["assignee"] = {"accountId": account_id}
        if task.due_date:
            optional["duedate"] = task.due_date.isoformat()
        priority = PRIORITY_TO_JIRA.get((task.priority or "").lower())
        if priority:
            optional["priority"] = {"name": priority}
        try:
            created = await _call(client, "POST", "/rest/api/3/issue", json={"fields": {**fields, **optional}})
        except JiraError as error:
            # A project's screen may lack due date / priority / assignee, or the
            # owner can't be assigned there: the issue matters more than those.
            if not optional or "400" not in str(error):
                raise
            fields["description"] = _description(task, meeting, task.owner or None)
            created = await _call(client, "POST", "/rest/api/3/issue", json={"fields": fields})
            optional = {}
        key = created["key"]
        task.jira_issue_key = key
        task.jira_error = None
        task.jira_synced_at = _now()
        task.jira_snapshot = {
            "summary": summary,
            "assignee": account_id if "assignee" in optional else None,
            "duedate": optional.get("duedate"),
            "priority": priority if "priority" in optional else None,
            "category": "new",
        }
        await db.commit()
        # A task already in progress or done shouldn't arrive as "To Do".
        if task.status in ("in_progress", "done"):
            await _push_status(client, task)
            await db.commit()
    return key


async def send_tasks(db: AsyncSession, tasks: list[MeetingTask]) -> tuple[dict[str, str], dict[str, str]]:
    """Sends each task, parents before their subtasks so they nest.
    Returns ({task id: key}, {task id: error})."""
    # Ids, not objects: a failure rolls back, which expires every loaded task,
    # and reading an expired attribute can't lazy-load under asyncio.
    order = [task.id for task in sorted(tasks, key=lambda t: t.parent_task_id is not None)]
    created: dict[str, str] = {}
    failed: dict[str, str] = {}
    for task_id in order:
        task = await db.get(MeetingTask, task_id)
        if task is None:
            continue
        try:
            created[str(task_id)] = await create_issue(db, task)
        except JiraError as error:
            failed[str(task_id)] = str(error)
            await db.rollback()
    return created, failed


async def auto_send(meeting_id: uuid.UUID) -> int:
    """When a meeting's notes are ready: send its open tasks if the admin
    chose automatic sending. Background task; never raises."""
    try:
        async with async_session() as db:
            connection = await get_connection(db)
            if connection is None or connection.auto_send not in ("all", "mapped") or not connection.default_project_key:
                return 0
            query = select(MeetingTask).where(
                MeetingTask.meeting_id == meeting_id,
                MeetingTask.deleted_at.is_(None),
                MeetingTask.jira_issue_key.is_(None),
                MeetingTask.status != "done",
            )
            meeting = await db.get(Meeting, meeting_id)
            if meeting is None or meeting.confidential:
                return 0
            tasks = list((await db.execute(query)).scalars().all())
            # A task held from an owner who wasn't in the meeting stays out
            # of Jira too — the assignee would see it there.
            inside = await privacy_service.owners_in_meeting(db, tasks)
            tasks = [t for t in tasks if privacy_service.owner_access(t, inside) != "held"]
            if connection.auto_send == "mapped":
                mapped = set((connection.project_map or {}).keys())
                tasks = [t for t in tasks if t.project_id and str(t.project_id) in mapped]
            created, failed = await send_tasks(db, tasks)
            if failed:
                logger.warning("Auto-send to Jira for meeting %s: %d failed (%s)", meeting_id, len(failed), next(iter(failed.values())))
            return len(created)
    except Exception:
        logger.exception("Jira auto-send failed for meeting %s", meeting_id)
        return 0


# ---------------------------------------------------------------- Charcha -> Jira

async def _transition(client: httpx.AsyncClient, key: str, category: str) -> str | None:
    """Moves the issue into a status of `category`; returns that status name.
    None when the workflow has no such status (MT on Jira Free has no
    In Progress) — that is not an error, the issue just stays put."""
    issue = await _call(client, "GET", f"/rest/api/3/issue/{key}", params={"fields": "status"})
    status = issue["fields"]["status"]
    if status["statusCategory"]["key"] == category:
        return status["name"]
    options = await _call(client, "GET", f"/rest/api/3/issue/{key}/transitions")
    transition = next(
        (t for t in options.get("transitions", []) if t["to"]["statusCategory"]["key"] == category), None
    )
    if transition is None:
        return None
    await _call(client, "POST", f"/rest/api/3/issue/{key}/transitions", json={"transition": {"id": transition["id"]}})
    return transition["to"]["name"]


async def _push_status(client: httpx.AsyncClient, task: MeetingTask) -> None:
    category = TO_JIRA.get(task.status)
    if category is None:
        return
    name = await _transition(client, task.jira_issue_key, category)
    if name is not None:
        task.jira_status = name
        task.jira_snapshot = {**(task.jira_snapshot or {}), "category": category}


async def push_changes(task_id: uuid.UUID, changed: set[str]) -> None:
    """Charcha -> Jira after a person edited a linked task (`changed` holds
    task field names). Background task; failures are recorded on the task
    (jira_error), never raised. An issue deleted in Jira is unlinked."""
    try:
        async with async_session() as db:
            task = await db.get(MeetingTask, task_id)
            connection = await get_connection(db)
            if task is None or not task.jira_issue_key or connection is None:
                return
            snapshot = dict(task.jira_snapshot or {})
            try:
                async with await open_client(db, connection) as client:
                    edit: dict = {}
                    if "description" in changed:
                        edit["summary"] = " ".join(task.description.split())[:SUMMARY_LIMIT]
                    if "due_date" in changed:
                        edit["duedate"] = task.due_date.isoformat() if task.due_date else None
                    if "priority" in changed:
                        edit["priority"] = {"name": PRIORITY_TO_JIRA[task.priority.lower()]} if (task.priority or "").lower() in PRIORITY_TO_JIRA else None
                        if edit["priority"] is None:
                            edit.pop("priority")
                    if edit:
                        await _call(client, "PUT", f"/rest/api/3/issue/{task.jira_issue_key}", json={"fields": edit})
                        snapshot.update({
                            k: (v["name"] if k == "priority" else v) for k, v in edit.items()
                        })
                    if "owner" in changed:
                        owner = await _owner_user(db, task)
                        account_id = await _account_for_user(db, owner.id if owner else None)
                        if account_id or not (task.owner or "").strip():
                            # A named owner who isn't in Jira leaves the assignee alone.
                            await _call(client, "PUT", f"/rest/api/3/issue/{task.jira_issue_key}/assignee", json={"accountId": account_id})
                            snapshot["assignee"] = account_id
                    task.jira_snapshot = snapshot
                    if "status" in changed:
                        await _push_status(client, task)
                task.jira_error = None
                task.jira_synced_at = _now()
            except JiraNotFound:
                task.jira_error = f"{task.jira_issue_key} was deleted in Jira, so the task was unlinked"
                task.jira_issue_key, task.jira_status, task.jira_snapshot = None, None, None
            except JiraError as error:
                task.jira_error = str(error)[:500]
            await db.commit()
    except Exception:
        logger.exception("Could not push task %s to Jira", task_id)


async def push_comment(comment_id: uuid.UUID) -> None:
    """Mirror a Charcha comment onto the linked issue. Background task."""
    try:
        async with async_session() as db:
            comment = await db.get(TaskComment, comment_id)
            if comment is None or comment.jira_comment_id or comment.source == "jira":
                return
            task = await db.get(MeetingTask, comment.task_id)
            connection = await get_connection(db)
            if task is None or not task.jira_issue_key or connection is None:
                return
            author = await db.get(User, comment.user_id) if comment.user_id else None
            body = {"type": "doc", "version": 1, "content": [
                _paragraph(_text(comment.body)),
                _paragraph(_text(f"— {(author.name or author.email) if author else 'A teammate'}, via Charcha", em=True)),
            ]}
            try:
                async with await open_client(db, connection) as client:
                    created = await _call(client, "POST", f"/rest/api/3/issue/{task.jira_issue_key}/comment", json={"body": body})
                comment.jira_comment_id = str(created["id"])
            except JiraError as error:
                task.jira_error = f"Comment not copied to Jira: {error}"[:500]
            await db.commit()
    except Exception:
        logger.exception("Could not copy comment %s to Jira", comment_id)


# ---------------------------------------------------------------- Jira -> Charcha

SYNC_FIELDS = ["status", "summary", "assignee", "duedate", "priority", "comment", "updated"]


PEOPLE_REMATCH = datetime.timedelta(hours=1)
_people_matched_at: datetime.datetime | None = None


async def sync_once(db: AsyncSession) -> int:
    """Jira → Charcha: fields and comments of every linked issue updated since
    the last poll. Returns how many tasks changed."""
    global _people_matched_at
    connection = await get_connection(db)
    if connection is None:
        return 0
    if _people_matched_at is None or _now() - _people_matched_at > PEOPLE_REMATCH:
        # New Charcha accounts and new Jira users get linked without a visit
        # to the admin page.
        try:
            async with await open_client(db, connection) as client:
                _, newly_linked = await match_people(db, client)
            _people_matched_at = _now()
        except JiraError as error:
            logger.warning("Jira people matching failed: %s", error)
    started = _now()
    since = connection.last_synced_at or (started - datetime.timedelta(days=1))
    # Relative minutes, so the Jira account's time zone doesn't matter; a
    # couple of minutes of overlap so nothing falls between polls.
    minutes = min(int((started - since).total_seconds() // 60) + 2, MAX_LOOKBACK_MINUTES)
    changed = 0
    try:
        async with await open_client(db, connection) as client:
            token = None
            while True:
                body = {
                    "jql": f'labels = charcha AND updated >= "-{minutes}m" ORDER BY updated ASC',
                    "fields": SYNC_FIELDS,
                    "maxResults": 100,
                }
                if token:
                    body["nextPageToken"] = token
                page = await _call(client, "POST", "/rest/api/3/search/jql", json=body)
                for issue in page.get("issues", []):
                    changed += await apply_issue(db, issue, client)
                token = page.get("nextPageToken")
                if not token or page.get("isLast", False):
                    break
            await _backfill_snapshots(db, client)
        connection.last_synced_at = started
        connection.last_error = None
    except JiraError as error:
        connection.last_error = str(error)[:500]
        logger.warning("Jira sync failed: %s", error)
    await db.commit()
    return changed


async def _backfill_snapshots(db: AsyncSession, client: httpx.AsyncClient) -> None:
    """Linked tasks with no snapshot yet (sent before snapshots existed):
    record the issue as it is now, so the first edit made in Jira afterwards
    is recognised as a change instead of becoming the baseline."""
    tasks = (
        await db.execute(
            select(MeetingTask).where(MeetingTask.jira_issue_key.isnot(None), MeetingTask.jira_snapshot.is_(None)).limit(100)
        )
    ).scalars().all()
    if not tasks:
        return
    by_key = {task.jira_issue_key: task for task in tasks}
    keys = ", ".join(f'"{key}"' for key in by_key)
    try:
        page = await _call(client, "POST", "/rest/api/3/search/jql", json={"jql": f"key in ({keys})", "fields": SYNC_FIELDS, "maxResults": 100})
    except JiraError as error:
        # JQL rejects the whole query when one of the keys was deleted in
        # Jira; that must not stop the regular sync from completing.
        logger.warning("Jira snapshot backfill skipped: %s", error)
        return
    for issue in page.get("issues", []):
        task = by_key.get(issue["key"])
        if task is not None:
            fields = issue.get("fields") or {}
            task.jira_snapshot = _snapshot(fields)
            task.jira_status = (fields.get("status") or {}).get("name") or task.jira_status
            task.jira_synced_at = _now()


def _history(task: MeetingTask, field: str, old, new) -> TaskHistory:
    return TaskHistory(
        task_id=task.id, changed_by=None, source="jira", field=field,
        old_value=None if old is None else str(old), new_value=None if new is None else str(new),
    )


async def apply_issue(db: AsyncSession, issue: dict, client: httpx.AsyncClient | None = None) -> int:
    """Copies what changed *in Jira* since the last snapshot onto the task;
    fields nobody changed in Jira are left as Charcha has them. Returns 1 when
    the task changed."""
    task = (
        await db.execute(select(MeetingTask).where(MeetingTask.jira_issue_key == issue["key"]))
    ).scalar_one_or_none()
    if task is None or task.deleted_at is not None:
        return 0
    fields = issue.get("fields") or {}
    current = _snapshot(fields)
    before = task.jira_snapshot
    task.jira_status = (fields.get("status") or {}).get("name") or task.jira_status
    task.jira_synced_at = _now()
    task.jira_snapshot = current
    touched = False
    if before is not None:
        if current["summary"] and current["summary"] != before.get("summary") and current["summary"] != " ".join(task.description.split()):
            db.add(_history(task, "description", task.description, current["summary"]))
            task.description, touched = current["summary"], True
        if current["assignee"] != before.get("assignee"):
            person = await _user_for_account(db, current["assignee"])
            name = (person.name or person.email) if person else ((fields.get("assignee") or {}).get("displayName"))
            if (person.id if person else None) != task.owner_user_id or name != task.owner:
                db.add(_history(task, "owner", task.owner, name))
                task.owner, task.owner_user_id, touched = name, (person.id if person else None), True
        if current["duedate"] != before.get("duedate"):
            due = datetime.date.fromisoformat(current["duedate"]) if current["duedate"] else None
            if due != task.due_date:
                db.add(_history(task, "due_date", task.due_date, due))
                task.due_date, touched = due, True
                # The spoken phrase ("Friday") no longer describes the date.
                task.deadline = None
        if current["priority"] != before.get("priority"):
            priority = PRIORITY_FROM_JIRA.get((current["priority"] or "").lower())
            if priority != task.priority:
                db.add(_history(task, "priority", task.priority, priority))
                task.priority, touched = priority, True
        category = current["category"]
        if category != before.get("category") and FROM_JIRA.get(category) not in (None, task.status):
            new = FROM_JIRA[category]
            db.add(_history(task, "status", task.status, new))
            task.status, touched = new, True
    touched |= await _pull_comments(db, task, issue, fields, client)
    return 1 if touched else 0


async def _pull_comments(db: AsyncSession, task: MeetingTask, issue: dict, fields: dict, client: httpx.AsyncClient | None) -> bool:
    block = fields.get("comment") or {}
    comments = block.get("comments") or []
    if block.get("total", 0) > len(comments) and client is not None:
        comments = []
        start = 0
        while True:
            page = await _call(client, "GET", f"/rest/api/3/issue/{issue['key']}/comment", params={"startAt": start, "maxResults": 100, "orderBy": "created"})
            comments += page.get("comments", [])
            start += len(page.get("comments", []))
            if not page.get("comments") or start >= page.get("total", 0):
                break
    if not comments:
        return False
    ids = [str(c["id"]) for c in comments]
    known = set(
        (await db.execute(select(TaskComment.jira_comment_id).where(TaskComment.jira_comment_id.in_(ids)))).scalars().all()
    )
    added = False
    for comment in comments:
        if str(comment["id"]) in known:
            continue
        text_body = _adf_text(comment.get("body")).strip()
        if not text_body:
            continue
        author = comment.get("author") or {}
        person = await _user_for_account(db, author.get("accountId"))
        created = comment.get("created")
        db.add(TaskComment(
            task_id=task.id,
            user_id=person.id if person else None,
            author_name=author.get("displayName"),
            body=text_body,
            source="jira",
            jira_comment_id=str(comment["id"]),
            created_at=datetime.datetime.fromisoformat(created.replace("Z", "+00:00")) if created else _now(),
        ))
        added = True
    return added


# ---------------------------------------------------------------- loop

async def run_once() -> None:
    async with engine.connect() as lock_conn:
        locked = await lock_conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": ADVISORY_LOCK_KEY})
        if not locked:
            await lock_conn.rollback()
            return
        try:
            async with async_session() as db:
                changed = await sync_once(db)
                if changed:
                    logger.info("Jira sync updated %d task(s)", changed)
        finally:
            await lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_LOCK_KEY})
            await lock_conn.commit()


async def run_forever() -> None:
    while True:
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Jira sync iteration failed; retrying")
        await asyncio.sleep(SYNC_SECONDS)
