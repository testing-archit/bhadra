"""Transactional email: the outbox, password reset/invite, preferences,
the daily cap, and every story rendering."""

import datetime
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, select

from app.config import settings
from app.database.db import async_session
from app.database.models import (
    CalendarConnection,
    CalendarEvent,
    Decision,
    EmailOutbox,
    Meeting,
    MeetingAttendee,
    MeetingInsight,
    MeetingTask,
    Notification,
    PasswordResetToken,
    User,
)
from app.services import attendee_service, email_service, email_stories, followup_service, secret_box
from app.services.password_service import hash_password
from tests.conftest import TEST_PREFIX, auth_headers


async def _outbox(user_id, kind=None) -> list[EmailOutbox]:
    async with async_session() as db:
        query = select(EmailOutbox).where(EmailOutbox.user_id == user_id)
        if kind:
            query = query.where(EmailOutbox.kind == kind)
        return list((await db.execute(query.order_by(EmailOutbox.created_at))).scalars().all())


@pytest.fixture
async def password_user():
    async with async_session() as db:
        user = User(
            email=f"{TEST_PREFIX}pw_{uuid.uuid4().hex[:8]}@example.com", name=f"{TEST_PREFIX}Asha Rao",
            password_hash=hash_password("old-password-1"),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    yield user
    async with async_session() as db:
        await db.execute(delete(User).where(User.id == user.id))
        await db.commit()


# ---------------------------------------------------------------- outbox hook

async def test_notifications_queue_their_email_in_the_same_transaction(member_user):
    async with async_session() as db:
        db.add(Notification(user_id=member_user.id, type="meeting_access", message="Shared", link="/meetings/x"))
        await db.rollback()  # never committed: nothing queued
        db.add(Notification(user_id=member_user.id, type="meeting_access", message="Shared", link="/meetings/y"))
        db.add(Notification(user_id=member_user.id, type="meeting_access", message="Shared again", link="/meetings/y"))  # same event
        db.add(Notification(user_id=member_user.id, type="task_due_soon", message="Due", link="/meetings/z"))  # not emailed
        await db.commit()
    rows = await _outbox(member_user.id)
    assert [(r.kind, r.payload["link"]) for r in rows] == [("meeting_access", "/meetings/y")]


# ---------------------------------------------------------------- passwords

async def test_forgot_password_never_reveals_who_has_an_account(client, password_user):
    unknown = await client.post("/api/auth/password/forgot", json={"email": "nobody-here@example.com"})
    known = await client.post("/api/auth/password/forgot", json={"email": password_user.email.upper()})
    assert unknown.status_code == known.status_code == 200 and unknown.json() == known.json()
    [row] = await _outbox(password_user.id, "password_reset")
    assert row.priority == 0 and row.payload["token"]
    # A second request inside the cooldown doesn't send another email.
    await client.post("/api/auth/password/forgot", json={"email": password_user.email})
    assert len(await _outbox(password_user.id, "password_reset")) == 1


async def test_reset_link_works_once_and_signs_out_old_sessions(client, password_user):
    old_session = auth_headers(password_user)
    assert (await client.get("/api/auth/me", headers=old_session)).status_code == 200
    await client.post("/api/auth/password/forgot", json={"email": password_user.email})
    token = (await _outbox(password_user.id, "password_reset"))[0].payload["token"]

    short = await client.post("/api/auth/password/reset", json={"token": token, "password": "short"})
    assert short.status_code == 422
    reset = await client.post("/api/auth/password/reset", json={"token": token, "password": "new-password-2"})
    assert reset.status_code == 200
    fresh = {"Authorization": f"Bearer {reset.json()['token']}"}
    assert (await client.get("/api/auth/me", headers=fresh)).status_code == 200
    # Sessions from before the reset are signed out, and the link is spent.
    async with async_session() as db:
        user = await db.get(User, password_user.id)
        cutoff = user.sessions_valid_after
    stale = jwt_with_iat(password_user, int(cutoff.timestamp()) - 60)
    assert (await client.get("/api/auth/me", headers=stale)).status_code == 401
    again = await client.post("/api/auth/password/reset", json={"token": token, "password": "another-pass-3"})
    assert again.status_code == 400
    login = await client.post("/api/auth/login", json={"email": password_user.email, "password": "new-password-2"})
    assert login.status_code == 200
    assert len(await _outbox(password_user.id, "password_changed")) == 1


def jwt_with_iat(user, iat: int) -> dict:
    import jwt as pyjwt

    token = pyjwt.encode(
        {"sub": str(user.id), "email": user.email, "iat": iat, "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)},
        settings.jwt_secret, algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


async def test_google_only_accounts_can_set_a_password_by_email(client, member_user):
    await client.post("/api/auth/password/forgot", json={"email": member_user.email})
    assert await _outbox(member_user.id, "password_reset") == []
    [row] = await _outbox(member_user.id, "password_reset_google")
    # The email carries a set-password link, not just "use Google".
    token = row.payload["token"]
    async with async_session() as db:
        rendered = await email_stories.render(db, row, member_user)
    assert "/reset-password?token=" in rendered["html"] and "Set a password" in rendered["html"]
    response = await client.post("/api/auth/password/reset", json={"token": token, "password": "Archit@2005"})
    assert response.status_code == 200
    login = await client.post("/api/auth/login", json={"email": member_user.email, "password": "Archit@2005"})
    assert login.status_code == 200


async def test_change_password_needs_the_current_one(client, password_user):
    wrong = await client.post(
        "/api/auth/password/change", json={"current_password": "nope", "new_password": "brand-new-pass"}, headers=auth_headers(password_user)
    )
    assert wrong.status_code == 400
    ok = await client.post(
        "/api/auth/password/change", json={"current_password": "old-password-1", "new_password": "brand-new-pass"}, headers=auth_headers(password_user)
    )
    assert ok.status_code == 200 and (await _outbox(password_user.id, "password_changed"))[0].payload["how"] == "settings"


async def test_admin_created_accounts_get_an_invite_to_set_their_own_password(client, admin_user):
    email = f"{TEST_PREFIX}new_{uuid.uuid4().hex[:8]}@example.com"
    created = await client.post(
        "/api/admin/accounts", headers=auth_headers(admin_user),
        json={"email": email, "name": "New Person", "password": "admin-typed-1", "role": "member", "status": "active"},
    )
    assert created.status_code == 201, created.text
    user_id = uuid.UUID(created.json()["id"])
    try:
        [invite] = await _outbox(user_id, "invite")
        assert "admin-typed-1" not in str(invite.payload)
        reset = await client.post("/api/auth/password/reset", json={"token": invite.payload["token"], "password": "my-own-pass-1"})
        assert reset.status_code == 200
    finally:
        async with async_session() as db:
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()


async def test_register_sends_a_welcome(client):
    email = f"{TEST_PREFIX}reg_{uuid.uuid4().hex[:8]}@example.com"
    response = await client.post("/api/auth/register", json={"email": email, "password": "password-123", "name": "Reg"})
    assert response.status_code == 200
    async with async_session() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    try:
        assert len(await _outbox(user.id, "welcome")) == 1
    finally:
        async with async_session() as db:
            await db.execute(delete(User).where(User.id == user.id))
            await db.commit()


# ---------------------------------------------------------------- preferences

async def test_preferences_and_one_click_unsubscribe(client, member_user):
    prefs = (await client.get("/api/email/preferences", headers=auth_headers(member_user))).json()
    keys = {c["key"]: c for c in prefs["categories"]}
    assert keys["security"]["can_disable"] is False and "admin" not in keys  # members don't see admin alerts
    updated = await client.put(
        "/api/email/preferences", headers=auth_headers(member_user), json={"categories": {"digest": False, "security": False}}
    )
    states = {c["key"]: c["enabled"] for c in updated.json()["categories"]}
    assert states["digest"] is False and states["security"] is True

    token = email_service.unsubscribe_token(member_user.id, "tasks")
    redirect = await client.get(f"/api/email/unsubscribe?token={token}", follow_redirects=False)
    assert redirect.status_code == 303  # GET changes nothing (mail scanners open links)
    one_click = await client.post(f"/api/email/unsubscribe?token={token}", content="List-Unsubscribe=One-Click",
                                  headers={"content-type": "application/x-www-form-urlencoded"})
    assert one_click.json()["category"] == "tasks"
    assert (await client.post("/api/email/unsubscribe", json={"token": "forged"})).status_code == 400
    # Same secret, same `sub` — but an unsubscribe link must never sign anyone in.
    as_login = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert as_login.status_code == 401
    async with async_session() as db:
        user = await db.get(User, member_user.id)
        assert email_service.wants(user, "tasks_assigned") is False and email_service.wants(user, "password_reset") is True


# ---------------------------------------------------------------- sending

async def test_send_due_respects_preferences_and_the_daily_cap(member_user):
    async with async_session() as db:
        user = await db.get(User, member_user.id)
        user.email_prefs = {"digest": False}
        await db.commit()
        await email_service.enqueue(db, "welcome", member_user.id, dedupe_key=f"w:{uuid.uuid4()}")
        await email_service.enqueue(db, "weekly_digest", member_user.id, {"date": "2026-10-05"}, dedupe_key=f"d:{uuid.uuid4()}")
        await email_service.enqueue(db, "password_reset", member_user.id, {"token": "t"}, dedupe_key=f"p:{uuid.uuid4()}")
        await email_service.enqueue(db, "task_assigned", member_user.id, {"message": "m", "link": "/x"}, dedupe_key=f"t:{uuid.uuid4()}")
        await db.commit()
    post = AsyncMock(return_value="<msg@brevo>")
    # Today's quota for everyday email is used up; password resets still go.
    with patch.object(settings, "brevo_api_key", "k"), patch.object(email_service, "_post", post), \
            patch.object(email_service, "_sent_today", AsyncMock(return_value=settings.email_daily_limit - settings.email_security_reserve)):
        async with async_session() as db:
            await email_service.send_due(db)
    rows = {r.kind: r for r in await _outbox(member_user.id)}
    assert rows["weekly_digest"].status == "skipped"  # switched off: skipped, not held for quota
    assert rows["password_reset"].status == "sent"
    for kind in ("welcome", "task_assigned"):  # held until after midnight UTC
        assert rows[kind].status == "queued" and rows[kind].send_after > datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
    assert [call.args[0] for call in post.call_args_list] == [member_user.email]
    # With quota back, the held ones go — with one-click unsubscribe headers.
    async with async_session() as db:
        for kind in ("welcome", "task_assigned"):
            (await db.get(EmailOutbox, rows[kind].id)).send_after = datetime.datetime.now(datetime.UTC)
        await db.commit()
    with patch.object(settings, "brevo_api_key", "k"), patch.object(email_service, "_post", post), \
            patch.object(email_service, "_sent_today", AsyncMock(return_value=0)):
        async with async_session() as db:
            await email_service.send_due(db)
    rows = {r.kind: r for r in await _outbox(member_user.id)}
    assert rows["welcome"].status == rows["task_assigned"].status == "sent"
    headers = post.call_args_list[-1].args[3]
    assert "List-Unsubscribe" in headers and "One-Click" in headers["List-Unsubscribe-Post"]


async def test_brevo_errors_retry_then_fail(member_user):
    async with async_session() as db:
        await email_service.enqueue(db, "welcome", member_user.id, dedupe_key=f"w:{uuid.uuid4()}")
        await db.commit()
    with patch.object(settings, "brevo_api_key", "k"), patch.object(email_service, "_post", AsyncMock(side_effect=email_service.BrevoError(502, "bad gateway"))):
        async with async_session() as db:
            await email_service.send_due(db)
    [row] = await _outbox(member_user.id, "welcome")
    assert row.status == "queued" and row.attempts == 1 and "502" in row.last_error
    with patch.object(settings, "brevo_api_key", "k"), patch.object(email_service, "_post", AsyncMock(side_effect=email_service.BrevoError(400, "invalid"))):
        async with async_session() as db:
            row = await db.get(EmailOutbox, row.id)
            await email_service.send_one(db, row)
            await db.commit()
    [row] = await _outbox(member_user.id, "welcome")
    assert row.status == "failed"


async def test_nothing_is_dropped_while_brevo_is_not_configured(member_user):
    async with async_session() as db:
        await email_service.enqueue(db, "welcome", member_user.id, dedupe_key=f"w:{uuid.uuid4()}")
        await db.commit()
    with patch.object(settings, "brevo_api_key", ""):
        await email_service.run_once()
    [row] = await _outbox(member_user.id, "welcome")
    assert row.status == "queued"


# ---------------------------------------------------------------- stories

async def test_every_story_renders_with_brand_and_plain_text(member_user, other_member_user, make_meeting):
    now = datetime.datetime.now(datetime.UTC)
    meeting = await make_meeting(member_user, "Acme weekly sync", None)
    async with async_session() as db:
        meeting_row = await db.get(Meeting, meeting.id)
        meeting_row.source = "bot"
        db.add(MeetingInsight(meeting_id=meeting.id, overview="Pricing agreed; SSO is the open thread."))
        db.add(MeetingAttendee(meeting_id=meeting.id, user_id=other_member_user.id, display_name="Priya Sharma", email=other_member_user.email, access="granted"))
        db.add(MeetingAttendee(meeting_id=meeting.id, display_name="Dana Lee", email="dana@acme.example", kind="external"))
        db.add(MeetingTask(meeting_id=meeting.id, description=f"{TEST_PREFIX}Send the quote", owner_user_id=member_user.id,
                           due_date=now.date(), owner=member_user.name))
        db.add(MeetingTask(meeting_id=meeting.id, description=f"{TEST_PREFIX}Share SSO metadata", owner="Dana"))
        db.add(Decision(meeting_id=meeting.id, decision="Annual billing for Acme"))
        db.add(CalendarConnection(user_id=member_user.id, google_email=member_user.email, refresh_token_encrypted=secret_box.encrypt("x")))
        event = CalendarEvent(
            user_id=member_user.id, google_event_id=f"{TEST_PREFIX}{uuid.uuid4().hex}", title="Acme weekly sync",
            start_at=now + datetime.timedelta(minutes=9), end_at=now + datetime.timedelta(minutes=39),
            meeting_url="https://meet.google.com/abc-defg-hij",
            brief={"status": "ready", "text": "### Where things stand\n- Pricing agreed **in principle** [M1]\n- <script>x</script>",
                   "meetings": [{"tag": "M1", "id": str(meeting.id), "title": "Acme weekly sync"}],
                   "open_tasks": [{"description": "Send the quote", "owner": "Archit", "deadline": "Friday"}]},
        )
        db.add(event)
        await db.commit()
        event_id = event.id
    payloads = {
        "password_reset": {"token": "abc"}, "password_reset_google": {}, "password_changed": {"how": "reset", "at": now.isoformat()},
        "invite": {"token": "abc", "invited_by": "Archit"}, "welcome": {},
        "calendar_error": {"message": "Google revoked Charcha's calendar access. Reconnect your calendar.", "link": "/settings#calendar"},
        "notetaker_signed_out": {"message": "m", "link": "/admin?tab=notetaker"},
        "pre_meeting_brief": {"message": "m", "link": f"/dashboard?brief={event_id}"},
        "notes_ready": {"meeting_id": str(meeting.id)},
        "series_review": {"message": "2 tasks sounded finished", "link": f"/meetings/{meeting.id}#series"},
        "tasks_assigned": {"message": "m", "link": f"/meetings/{meeting.id}?tab=actions"},
        "task_assigned": {"message": 'You were assigned: "Ship it"', "link": f"/meetings/{meeting.id}"},
        "meeting_access": {"message": "Priya shared notes", "link": f"/meetings/{meeting.id}"},
        "meeting_access_pending": {"message": "Kiran joined without an invite", "link": f"/meetings/{meeting.id}#people"},
        "daily_reminders": {"date": now.date().isoformat()},
        "weekly_digest": {"date": now.date().isoformat()},
    }
    async with async_session() as db:
        user = await db.get(User, member_user.id)
        # Meeting dated "now" falls in this week, not last; move it back for the digest.
        (await db.get(Meeting, meeting.id)).date = now - datetime.timedelta(days=2)
        await db.commit()
        for kind, payload in payloads.items():
            row = EmailOutbox(kind=kind, user_id=user.id, payload=payload, priority=1, status="queued")
            rendered = await email_stories.render(db, row, user)
            assert rendered is not None, kind
            assert "Wilco" in rendered["html"] and "wilco-apple-touch-icon.png" in rendered["html"], kind
            assert rendered["subject"] and rendered["text"].strip(), kind
            assert "<script>" not in rendered["html"], kind
            switchable = email_service.CATEGORIES[email_service.KINDS[kind][0]][2]
            assert ("/unsubscribe?token=" in rendered["html"]) is switchable, kind
        # The brief's markdown became HTML, and the meeting's tasks reached the notes email.
        brief = await email_stories.render(db, EmailOutbox(kind="pre_meeting_brief", user_id=user.id, payload=payloads["pre_meeting_brief"]), user)
        assert "<strong>in principle</strong>" in brief["html"] and "starts in" in brief["subject"]
        notes = await email_stories.render(db, EmailOutbox(kind="notes_ready", user_id=user.id, payload=payloads["notes_ready"]), user)
        assert "1 task for you" in notes["subject"] and "Annual billing" in notes["html"] and "Dana Lee" in notes["html"]
    async with async_session() as db:
        await db.execute(delete(CalendarEvent).where(CalendarEvent.id == event_id))
        await db.execute(delete(MeetingAttendee).where(MeetingAttendee.meeting_id == meeting.id))
        await db.execute(delete(MeetingInsight).where(MeetingInsight.meeting_id == meeting.id))
        await db.commit()


async def test_notes_ready_goes_to_everyone_with_access_and_replaces_the_tasks_email(member_user, other_member_user, make_meeting):
    meeting = await make_meeting(member_user, "Bot meeting", None)
    async with async_session() as db:
        (await db.get(Meeting, meeting.id)).source = "bot"
        db.add(MeetingAttendee(meeting_id=meeting.id, user_id=other_member_user.id, display_name="O", access="granted"))
        db.add(MeetingTask(meeting_id=meeting.id, description=f"{TEST_PREFIX}t", owner_user_id=other_member_user.id))
        await db.commit()
    assert await followup_service.announce_notes(meeting.id) == 2
    assert await followup_service.announce_notes(meeting.id) == 2  # dedupe: still one email
    await followup_service.notify_task_owners(meeting.id)
    # One email for the meeting: To the recorder, the other person in CC.
    [notes_row] = await _outbox(member_user.id, "notes_ready")
    assert notes_row.payload["cc"] == [str(other_member_user.id)]
    assert await _outbox(other_member_user.id, "notes_ready") == []
    async with async_session() as db:
        people = await email_service._recipients(db, notes_row)
        assert [p.id for p in people] == [member_user.id, other_member_user.id]
        rendered = await email_stories.render(db, notes_row, people[0])
        assert rendered["subject"].startswith("Notes ready:") and "Action items" in rendered["html"]
        assert "/unsubscribe?token=" not in rendered["html"]  # shared: no one-click unsubscribe
    [tasks_row] = await _outbox(other_member_user.id, "tasks_assigned")
    async with async_session() as db:
        user = await db.get(User, other_member_user.id)
        assert await email_stories.render(db, tasks_row, user) is None
    async with async_session() as db:
        await db.execute(delete(MeetingAttendee).where(MeetingAttendee.meeting_id == meeting.id))
        await db.commit()


async def test_people_outside_the_company_get_meeting_email_only_once_shared_in_charcha(
    member_user, other_member_user, make_meeting
):
    """A client with a Charcha account who was on the calendar invite can read
    the meeting, but isn't emailed about it until the recorder, organizer or
    an admin shares it with them in Charcha."""
    meeting = await make_meeting(member_user, "Client call", None)
    async with async_session() as db:
        (await db.get(Meeting, meeting.id)).source = "bot"
        client_user = await db.get(User, other_member_user.id)
        client_user.email = f"{TEST_PREFIX}client_{uuid.uuid4().hex[:8]}@client.example.org"
        db.add(MeetingAttendee(meeting_id=meeting.id, user_id=other_member_user.id, display_name="Client",
                               access="granted", source="calendar"))
        db.add(Notification(user_id=other_member_user.id, type="meeting_access", message="m", link=f"/meetings/{meeting.id}"))
        await db.commit()
    assert await followup_service.announce_notes(meeting.id) == 2
    [notes_row] = await _outbox(member_user.id, "notes_ready")
    [access_row] = await _outbox(other_member_user.id, "meeting_access")
    async with async_session() as db:
        client_user = await db.get(User, other_member_user.id)
        assert [p.id for p in await email_service._recipients(db, notes_row)] == [member_user.id]
        assert await email_stories.render(db, access_row, client_user) is None
        assert "wasn't shared" in access_row.last_error

    # The organizer shares it with them in Charcha: now they're emailed.
    async with async_session() as db:
        await attendee_service.share_with_user(db, await db.get(Meeting, meeting.id), await db.get(User, other_member_user.id))
        await db.commit()
    async with async_session() as db:
        notes_row = await db.get(EmailOutbox, notes_row.id)
        client_user = await db.get(User, other_member_user.id)
        assert [p.id for p in await email_service._recipients(db, notes_row)] == [member_user.id, other_member_user.id]
        assert await email_stories.render(db, await db.get(EmailOutbox, access_row.id), client_user) is not None

    # Company colleagues and the recorder need no share; no domain set: everyone.
    async with async_session() as db:
        assert await email_service.may_email_about_meeting(db, await db.get(User, member_user.id), meeting.id)
        with patch.object(settings, "internal_email_domains", ""):
            await db.execute(delete(MeetingAttendee).where(MeetingAttendee.meeting_id == meeting.id))
            assert await email_service.may_email_about_meeting(db, client_user, meeting.id)
        await db.commit()


async def test_scheduled_emails_once_a_day(member_user):
    nine = datetime.datetime(2026, 10, 5, 3, 40, tzinfo=datetime.UTC)  # Monday 09:10 IST
    with patch.object(email_service, "_now", return_value=nine):
        async with async_session() as db:
            await email_service.schedule_daily(db)
            await email_service.schedule_daily(db)
    kinds = sorted(r.kind for r in await _outbox(member_user.id))
    assert kinds == ["daily_reminders", "weekly_digest"]


async def test_single_emails_and_their_schedule_can_be_chosen(client, member_user):
    headers = auth_headers(member_user)
    prefs = (await client.get("/api/email/preferences", headers=headers)).json()
    notes = next(c for c in prefs["categories"] if c["key"] == "notes")
    assert [e["key"] for e in notes["emails"]] == ["notes_ready", "series_review"]
    assert prefs["schedule"] == {"reminder_days": [0, 1, 2, 3, 4, 5, 6], "digest_day": 0, "hour": 9}
    updated = await client.put("/api/email/preferences", headers=headers, json={
        "kinds": {"series_review": False, "password_reset": False, "made_up": False},
        "schedule": {"reminder_days": [4, 0, 0], "digest_day": 4, "hour": 7},
    })
    assert updated.status_code == 200
    assert updated.json()["schedule"] == {"reminder_days": [0, 4], "digest_day": 4, "hour": 7}
    assert (await client.put("/api/email/preferences", headers=headers, json={"schedule": {"hour": 22}})).status_code == 422
    assert (await client.put("/api/email/preferences", headers=headers, json={"schedule": {"reminder_days": [7]}})).status_code == 422
    async with async_session() as db:
        user = await db.get(User, member_user.id)
        assert email_service.wants(user, "series_review") is False
        assert email_service.wants(user, "notes_ready") is True
        # Security email ignores a per-email switch too.
        assert email_service.wants(user, "password_reset") is True and email_service.wants(user, "password_reset_google") is True

    def at(day: int, hour: int) -> datetime.datetime:  # 2026-10-05 is a Monday; IST = UTC+5:30
        return datetime.datetime(2026, 10, 5 + day, hour, 10, tzinfo=email_service.LOCAL_TZ)

    for moment in (at(0, 9), at(1, 7), at(4, 9)):  # old hour, a day without reminders, wrong hour
        with patch.object(email_service, "_now", return_value=moment):
            async with async_session() as db:
                await email_service.schedule_daily(db)
    assert await _outbox(member_user.id) == []
    with patch.object(email_service, "_now", return_value=at(4, 7)):  # Friday 07:10: reminder and digest
        async with async_session() as db:
            await email_service.schedule_daily(db)
    assert sorted(r.kind for r in await _outbox(member_user.id)) == ["daily_reminders", "weekly_digest"]
