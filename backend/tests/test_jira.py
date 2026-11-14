"""Jira Cloud integration against a fake Jira (httpx.MockTransport)."""

import datetime
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.services import jira_service as js


def fake_jira(routes: dict):
    """routes: {(METHOD, path): response json or callable(request) -> (status, json)}"""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        calls.append((key, json.loads(request.content) if request.content else None))
        if key not in routes:
            return httpx.Response(404, json={"errorMessages": ["not faked"]})
        result = routes[key]
        status, body = result(request) if callable(result) else (200, result)
        return httpx.Response(status, json=body)

    client = httpx.AsyncClient(base_url="https://x.atlassian.net", transport=httpx.MockTransport(handler))
    return client, calls


def test_site_must_be_atlassian_cloud():
    assert js.normalize_site("acme.atlassian.net/jira/software/projects") == "https://acme.atlassian.net"
    assert js.normalize_site("https://acme.atlassian.net/") == "https://acme.atlassian.net"
    for bad in ("http://169.254.169.254", "evil.com", "acme.atlassian.net.evil.com", ""):
        with pytest.raises(js.JiraError):
            js.normalize_site(bad)


def _status(name, category):
    return {"name": name, "statusCategory": {"key": category}}


async def test_transition_picks_the_target_category():
    client, calls = fake_jira({
        ("GET", "/rest/api/3/issue/MEM-1"): {"fields": {"status": _status("To Do", "new")}},
        ("GET", "/rest/api/3/issue/MEM-1/transitions"): {"transitions": [
            {"id": "21", "to": _status("In Progress", "indeterminate")},
            {"id": "31", "to": _status("Done", "done")},
        ]},
        ("POST", "/rest/api/3/issue/MEM-1/transitions"): {},
    })
    async with client:
        assert await js._transition(client, "MEM-1", "done") == "Done"
    assert calls[-1] == (("POST", "/rest/api/3/issue/MEM-1/transitions"), {"transition": {"id": "31"}})


async def test_workflow_without_the_category_is_not_an_error():
    # MT on Jira Free has only To Do and Done.
    client, calls = fake_jira({
        ("GET", "/rest/api/3/issue/MT-1"): {"fields": {"status": _status("To Do", "new")}},
        ("GET", "/rest/api/3/issue/MT-1/transitions"): {"transitions": [{"id": "31", "to": _status("Done", "done")}]},
    })
    async with client:
        assert await js._transition(client, "MT-1", "indeterminate") is None
    assert all(method == "GET" for (method, _), _ in calls)


async def test_transition_is_a_no_op_when_already_there():
    client, calls = fake_jira({("GET", "/rest/api/3/issue/MEM-2"): {"fields": {"status": _status("Done", "done")}}})
    async with client:
        assert await js._transition(client, "MEM-2", "done") == "Done"
    assert len(calls) == 1


async def test_issue_type_prefers_task_and_skips_subtasks():
    js._issue_types.clear()
    client, _ = fake_jira({("GET", "/rest/api/3/issue/createmeta/MEM/issuetypes"): {"issueTypes": [
        {"id": "1", "name": "Sub-task", "subtask": True},
        {"id": "2", "name": "Story", "subtask": False},
        {"id": "3", "name": "Task", "subtask": False},
    ]}})
    async with client:
        assert await js._issue_type_id(client, "MEM") == "3"
        assert await js._issue_type_id(client, "MEM", subtask=True) == "1"


def test_description_names_unassignable_owner_and_links_meeting(monkeypatch):
    monkeypatch.setattr("app.services.calendar_service.app_url", lambda path: f"https://app{path}")
    task = SimpleNamespace(
        description="Check the SIP AUM calculation", deadline="Friday", due_date=None,
        evidence=[{"excerpt": "Archit, check the SIP AUM calculation by Friday", "verified": True}],
    )
    meeting = SimpleNamespace(id="m1", title="Weekly sync", date=datetime.datetime(2026, 10, 7))
    doc = js._description(task, meeting, "Archit")
    text = json.dumps(doc)
    assert doc["type"] == "doc" and "Archit" in text and "Friday" in text
    assert "https://app/meetings/m1?tab=actions" in text
    assert "blockquote" in text and "check the SIP AUM calculation by Friday" in text


def test_project_mapping_falls_back_to_default():
    project = uuid.uuid4()
    connection = SimpleNamespace(project_map={str(project): "OPS"}, default_project_key="MEM")
    assert js.project_key_for(connection, SimpleNamespace(project_id=project)) == "OPS"
    assert js.project_key_for(connection, SimpleNamespace(project_id=uuid.uuid4())) == "MEM"
    assert js.project_key_for(connection, SimpleNamespace(project_id=None)) == "MEM"


class FakeDb:
    """Just enough AsyncSession for apply_issue: one task, linked people."""

    def __init__(self, task, people=None):
        self.task, self.added, self.people = task, [], people or {}

    async def execute(self, query):
        compiled = str(query)
        if "jira_user_links" in compiled:
            account = query.whereclause.right.value
            link = self.people.get(account)
            return SimpleNamespace(scalar_one_or_none=lambda: link and SimpleNamespace(user_id=link.id))
        if "task_comments" in compiled:
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
        return SimpleNamespace(scalar_one_or_none=lambda: self.task)

    async def get(self, _model, key):
        return next((p for p in self.people.values() if p.id == key), None)

    def add(self, row):
        self.added.append(row)


def _task(**kw):
    base = dict(
        id=uuid.uuid4(), status="pending", deleted_at=None, description="Check the SIP AUM calculation",
        owner=None, owner_user_id=None, due_date=None, deadline="Friday", priority=None,
        jira_status=None, jira_synced_at=None,
        jira_snapshot={"summary": "Check the SIP AUM calculation", "assignee": None, "duedate": None, "priority": None, "category": "new"},
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _issue(key="MT-1", summary="Check the SIP AUM calculation", assignee=None, due=None, priority=None, status=("To Do", "new"), comments=()):
    return {"key": key, "fields": {
        "summary": summary, "assignee": assignee, "duedate": due,
        "priority": {"name": priority} if priority else None, "status": _status(*status),
        "comment": {"total": len(comments), "comments": list(comments)},
    }}


async def test_only_fields_changed_in_jira_are_copied():
    archit = SimpleNamespace(id=uuid.uuid4(), name="Archit Gupta", email="archit@example.com")
    task = _task(priority="High", status="in_progress")
    db = FakeDb(task, {"acc-1": archit})
    issue = _issue(summary="Check the SIP AUM calc for Q3", assignee={"accountId": "acc-1", "displayName": "Archit G"},
                   due="2026-10-10", priority=None)
    assert await js.apply_issue(db, issue) == 1
    assert task.description == "Check the SIP AUM calc for Q3"
    assert task.owner_user_id == archit.id and task.owner == "Archit Gupta"
    assert str(task.due_date) == "2026-10-10" and task.deadline is None
    # Priority and status weren't changed in Jira (snapshot None / "new"), so
    # Charcha's High and in_progress stand — MT has no In Progress to mirror.
    assert task.priority == "High" and task.status == "in_progress"
    assert {h.field for h in db.added} == {"description", "owner", "due_date"}
    assert all(h.source == "jira" for h in db.added)


async def test_status_and_priority_from_jira():
    task = _task(status="pending")
    db = FakeDb(task)
    assert await js.apply_issue(db, _issue(priority="Highest", status=("Done", "done"))) == 1
    assert task.status == "done" and task.priority == "High" and task.jira_status == "Done"
    # The same issue again: nothing new, no new history.
    count = len(db.added)
    assert await js.apply_issue(db, _issue(priority="Highest", status=("Done", "done"))) == 0
    assert len(db.added) == count


async def test_first_sight_only_records_a_snapshot():
    task = _task(jira_snapshot=None, status="in_progress")
    db = FakeDb(task)
    assert await js.apply_issue(db, _issue(status=("To Do", "new"))) == 0
    assert task.status == "in_progress" and task.jira_snapshot["category"] == "new"


async def test_jira_comments_arrive_once_with_their_author():
    task = _task()
    db = FakeDb(task)
    comment = {"id": "10001", "author": {"accountId": "acc-9", "displayName": "Vaibhav"}, "created": "2026-10-08T09:00:00.000+0530",
               "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Done, see the sheet"}]}]}}
    assert await js.apply_issue(db, _issue(comments=[comment])) == 1
    added = [row for row in db.added if getattr(row, "jira_comment_id", None)]
    assert len(added) == 1 and added[0].body == "Done, see the sheet" and added[0].author_name == "Vaibhav" and added[0].source == "jira"


def test_adf_text_flattens_paragraphs_and_mentions():
    doc = {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "mention", "attrs": {"text": "@Archit"}}, {"type": "text", "text": " please check"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "line two"}]},
    ]}
    assert js._adf_text(doc).strip() == "@Archit please check\nline two"


def test_snapshot_reads_the_mirrored_fields():
    snap = js._snapshot(_issue(summary="  Ship   it ", assignee={"accountId": "a"}, due="2026-10-10", priority="Low", status=("Done", "done"))["fields"])
    assert snap == {"summary": "Ship it", "assignee": "a", "duedate": "2026-10-10", "priority": "Low", "category": "done"}


class PeopleDb:
    def __init__(self, people, links=()):
        self.people, self.links, self.added = people, {l.user_id: l for l in links}, []

    async def execute(self, query):
        rows = list(self.links.values()) if "jira_user_links" in str(query) else self.people
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))

    def add(self, row):
        self.added.append(row)
        self.links[row.user_id] = row

    async def commit(self):
        pass


async def test_people_match_by_email_then_unique_name_and_respect_manual(monkeypatch):
    jira = [
        {"accountId": "a1", "displayName": "Archit Gupta", "emailAddress": "archit@example.com", "accountType": "atlassian", "active": True},
        {"accountId": "a2", "displayName": "Ravi Kumar", "accountType": "atlassian", "active": True},
        {"accountId": "a3", "displayName": "Sam", "accountType": "atlassian", "active": True},
        {"accountId": "a4", "displayName": "Sam", "accountType": "atlassian", "active": True},
        {"accountId": "a5", "displayName": "Vaibhav", "accountType": "atlassian", "active": True},
    ]

    async def fake_users(_client):
        return jira

    monkeypatch.setattr(js, "jira_users", fake_users)
    archit = SimpleNamespace(id=uuid.uuid4(), name="Archit", email="archit@example.com")
    ravi = SimpleNamespace(id=uuid.uuid4(), name="ravi  kumar", email="ravi@example.com")
    sam = SimpleNamespace(id=uuid.uuid4(), name="Sam", email="sam@example.com")
    vaibhav = SimpleNamespace(id=uuid.uuid4(), name="Vaibhav", email="vaibhav@example.com")
    manual = SimpleNamespace(user_id=vaibhav.id, account_id=None, display_name=None, matched_by="manual")
    db = PeopleDb([archit, ravi, sam, vaibhav], [manual])
    _, newly = await js.match_people(db, client=None)
    assert set(newly) == {archit.id, ravi.id}
    assert db.links[archit.id].account_id == "a1" and db.links[archit.id].matched_by == "email"
    assert db.links[ravi.id].account_id == "a2" and db.links[ravi.id].matched_by == "name"
    assert sam.id not in db.links  # two Jira users called Sam: no guess
    assert db.links[vaibhav.id].account_id is None  # manual "not in Jira" stands


# ---------------------------------------------------------------- Connect with Jira (OAuth)

def test_authorization_url_asks_for_offline_access(monkeypatch):
    from urllib.parse import parse_qs, urlparse

    from app.config import settings

    monkeypatch.setattr(settings, "atlassian_client_id", "cid")
    monkeypatch.setattr(settings, "atlassian_client_secret", "secret")
    monkeypatch.setattr(settings, "public_api_url", "https://charcha.example.com/")
    assert js.oauth_available()
    url = urlparse(js.authorization_url("st"))
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert url.netloc == "auth.atlassian.com"
    assert query["audience"] == "api.atlassian.com" and query["client_id"] == "cid" and query["state"] == "st"
    assert query["redirect_uri"] == "https://charcha.example.com/api/jira/oauth/callback"
    assert set(query["scope"].split()) == {"read:jira-work", "write:jira-work", "read:jira-user", "offline_access"}


def test_state_round_trips_and_rejects_other_purposes():
    from app.services import calendar_service

    user_id = uuid.uuid4()
    assert js.read_state(js.make_state(user_id)) == user_id
    with pytest.raises(js.JiraError):
        js.read_state(calendar_service.make_state(user_id))


class LockingDb:
    def __init__(self, connection):
        self.connection, self.commits = connection, 0

    async def execute(self, _query):
        return SimpleNamespace(scalar_one=lambda: self.connection)

    async def commit(self):
        self.commits += 1


async def test_expired_access_token_is_refreshed_and_rotated(monkeypatch):
    from app.services import secret_box

    connection = SimpleNamespace(
        id=1, auth_type="oauth", cloud_id="cloud-1",
        access_token_encrypted=secret_box.encrypt("old-access"),
        access_token_expires_at=js._now() - datetime.timedelta(minutes=1),
        refresh_token_encrypted=secret_box.encrypt("refresh-1"),
    )
    sent = []

    async def fake_token_request(body):
        sent.append(body)
        return {"access_token": "new-access", "refresh_token": "refresh-2", "expires_in": 3600}

    monkeypatch.setattr(js, "_token_request", fake_token_request)
    db = LockingDb(connection)
    client = await js.open_client(db, connection)
    async with client:
        assert str(client.base_url).rstrip("/") == "https://api.atlassian.com/ex/jira/cloud-1"
        assert client.headers["Authorization"] == "Bearer new-access"
    assert sent == [{"grant_type": "refresh_token", "refresh_token": "refresh-1"}]
    assert secret_box.decrypt(connection.refresh_token_encrypted) == "refresh-2"
    assert db.commits == 1

    # Still fresh: no second refresh.
    async with await js.open_client(db, connection):
        pass
    assert len(sent) == 1


async def test_backfill_gives_old_links_a_snapshot():
    task = _task(jira_issue_key="MT-1", jira_snapshot=None)

    class Db:
        async def execute(self, _query):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [task]))

    client, calls = fake_jira({("POST", "/rest/api/3/search/jql"): {"issues": [_issue(priority="Medium")], "isLast": True}})
    async with client:
        await js._backfill_snapshots(Db(), client)
    assert calls[0][1]["jql"] == 'key in ("MT-1")'
    assert task.jira_snapshot["priority"] == "Medium" and task.jira_status == "To Do"


async def test_confidential_meetings_never_go_to_jira(monkeypatch):
    meeting = SimpleNamespace(id=uuid.uuid4(), confidential=True, title="Org changes", source="capture")
    task = SimpleNamespace(id=uuid.uuid4(), meeting_id=meeting.id, jira_issue_key=None, parent_task_id=None)
    connection = SimpleNamespace(default_project_key="MT")

    async def get_connection(_db):
        return connection

    class Db:
        async def get(self, _model, _key):
            return meeting

    monkeypatch.setattr(js, "get_connection", get_connection)
    with pytest.raises(js.JiraError, match="confidential"):
        await js.create_issue(Db(), task)
