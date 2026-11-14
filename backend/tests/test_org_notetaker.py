"""Organisation-wide notetaker: one recording per meeting, invite-based
access with organizer sharing, and linked Google Calendars."""

import datetime
import json
import shutil
import uuid as uuid_mod
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, select

from app.config import settings
from app.database.db import async_session
from app.database.models import (
    CalendarConnection,
    CalendarEvent,
    CaptureRequest,
    CaptureSubscriber,
    Decision,
    Meeting,
    MeetingAttendee,
    MeetingTask,
    Notification,
    RecordingSession,
    Trace,
    User,
)
from app.routes.recordings import _session_dir
from app.services import calendar_service, secret_box
from tests.conftest import TEST_PREFIX, auth_headers

BOT_SECRET = "pytest-org-secret"
BOT = {"Authorization": f"Bot {BOT_SECRET}"}


@pytest.fixture(autouse=True)
def _bot_secret():
    with patch.object(settings, "bot_api_secret", BOT_SECRET):
        yield


def _code() -> str:
    letters = uuid_mod.uuid4().hex
    tr = str.maketrans("0123456789", "ghijklmnop")
    raw = letters.translate(tr)
    return f"{raw[:3]}-{raw[3:7]}-{raw[7:10]}"


@pytest.fixture
async def third_user():
    """A colleague with a unique name, so Meet captions can match them."""
    async with async_session() as db:
        user = User(
            email=f"{TEST_PREFIX}{uuid_mod.uuid4().hex[:8]}@example.com",
            name=f"{TEST_PREFIX}Kiran {uuid_mod.uuid4().hex[:6]}",
            google_sub=f"{TEST_PREFIX}{uuid_mod.uuid4()}",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    yield user
    async with async_session() as db:
        await db.execute(delete(User).where(User.id == user.id))
        await db.commit()


async def _cleanup_meeting(meeting_id: uuid_mod.UUID) -> None:
    async with async_session() as db:
        for recording in (await db.execute(select(RecordingSession).where(RecordingSession.meeting_id == meeting_id))).scalars():
            shutil.rmtree(_session_dir(recording.id), ignore_errors=True)
        for table in (RecordingSession, MeetingAttendee, Trace, MeetingTask, Decision):
            await db.execute(table.__table__.delete().where(table.meeting_id == meeting_id))
        await db.execute(Meeting.__table__.delete().where(Meeting.id == meeting_id))
        await db.commit()


async def test_invitees_get_access_and_uninvited_people_wait_for_the_organizer(
    client, member_user, other_member_user, third_user, admin_user, mock_extraction, mock_qdrant_upsert
):
    metadata = {
        "event_id": f"{TEST_PREFIX}{uuid_mod.uuid4().hex}",
        "event_start": "2026-10-07T10:00:00+05:30",
        "title": f"{TEST_PREFIX}Access rules",
        "organizer_email": member_user.email,
        "attendees": [{"email": other_member_user.email, "name": "Invited colleague"}],
        # The third colleague talked in the call but was never invited.
        "captions": [
            {"speaker": "Invited colleague", "text": "hello", "start": 1, "end": 2},
            {"speaker": third_user.name, "text": "I dropped in", "start": 3, "end": 5},
        ],
        "duration_seconds": 300,
    }
    response = await client.post("/api/bot/ingest", headers=BOT, data={"metadata": json.dumps(metadata)})
    assert response.status_code == 200, response.text
    meeting_id = uuid_mod.UUID(response.json()["meeting_id"])
    try:
        # Invited → can read. Present but uninvited → can't, yet.
        assert (await client.get(f"/api/meetings/{meeting_id}", headers=auth_headers(other_member_user))).status_code == 200
        assert (await client.get(f"/api/meetings/{meeting_id}", headers=auth_headers(third_user))).status_code == 404
        listed = await client.get("/api/meetings", headers=auth_headers(third_user))
        assert str(meeting_id) not in {m["id"] for m in listed.json()}

        detail = (await client.get(f"/api/meetings/{meeting_id}", headers=auth_headers(member_user))).json()
        assert detail["can_manage_access"] is True and detail["viewing_as_admin"] is False
        pending = [row for row in detail["attendees"] if row["user_id"] == str(third_user.id)]
        assert len(pending) == 1 and pending[0]["access"] == "pending"

        # An invited colleague who isn't the organizer can't hand out access.
        denied = await client.post(
            f"/api/meetings/{meeting_id}/attendees/{pending[0]['id']}/access",
            json={"access": "granted"},
            headers=auth_headers(other_member_user),
        )
        assert denied.status_code == 403

        # The organizer shares it; now they can read it.
        granted = await client.post(
            f"/api/meetings/{meeting_id}/attendees/{pending[0]['id']}/access",
            json={"access": "granted"},
            headers=auth_headers(member_user),
        )
        assert granted.status_code == 200
        assert (await client.get(f"/api/meetings/{meeting_id}", headers=auth_headers(third_user))).status_code == 200

        # A Charcha admin can open it (flagged) without it entering their own lists.
        admin_view = (await client.get(f"/api/meetings/{meeting_id}", headers=auth_headers(admin_user))).json()
        assert admin_view["viewing_as_admin"] is True and admin_view["can_manage_access"] is True
    finally:
        await _cleanup_meeting(meeting_id)


async def test_bot_invite_joins_a_visit_a_colleague_already_queued(client, member_user, other_member_user):
    code = _code()
    pasted = await client.post(
        "/api/capture/requests",
        headers=auth_headers(member_user),
        json={"meeting_url": f"https://meet.google.com/{code}", "consent_acknowledged": True},
    )
    assert pasted.status_code == 201
    invite = await client.post(
        "/api/bot/invites",
        headers=BOT,
        json={
            "meet_url": f"https://meet.google.com/{code}",
            "title": "Client review",
            "organizer_email": other_member_user.email,
            "attendees": [{"email": other_member_user.email, "name": ""}],
        },
    )
    body = invite.json()
    assert body["status"] == "queued" and body["joined_existing"] is True
    assert body["capture_request_id"] == pasted.json()["id"]
    async with async_session() as db:
        subscribers = (
            await db.execute(select(CaptureSubscriber.user_id).where(CaptureSubscriber.capture_request_id == uuid_mod.UUID(body["capture_request_id"])))
        ).scalars().all()
    assert set(subscribers) == {member_user.id, other_member_user.id}


def test_calendar_events_are_parsed_like_people_expect():
    base = {
        "id": "evt1",
        "status": "confirmed",
        "summary": "Weekly sync",
        "start": {"dateTime": "2026-10-07T10:00:00+05:30"},
        "end": {"dateTime": "2026-10-07T10:30:00+05:30"},
        "organizer": {"email": "lead@example.com"},
        "conferenceData": {"entryPoints": [{"entryPointType": "video", "uri": "https://meet.google.com/abc-defg-hij"}]},
        "attendees": [
            {"email": "me@example.com", "self": True, "responseStatus": "accepted"},
            {"email": "client@outside.example", "displayName": "Client"},
            {"email": "room@resource.calendar.google.com", "resource": True},
        ],
    }
    parsed = calendar_service.parse_event(base, "me@example.com")
    assert parsed["meeting_code"] == "abc-defg-hij" and parsed["is_organizer"] is False
    assert [item["email"] for item in parsed["invitees"]] == ["me@example.com", "client@outside.example"]

    declined = {**base, "attendees": [{"email": "me@example.com", "self": True, "responseStatus": "declined"}]}
    assert calendar_service.parse_event(declined, "me@example.com") is None
    assert calendar_service.parse_event({**base, "status": "cancelled"}, "me@example.com") is None
    all_day = {**base, "start": {"date": "2026-10-07"}, "end": {"date": "2026-10-08"}}
    assert calendar_service.parse_event(all_day, "me@example.com") is None

    zoom = {k: v for k, v in base.items() if k != "conferenceData"} | {"location": "https://us02web.zoom.us/j/123"}
    assert calendar_service.parse_event(zoom, "me@example.com")["unsupported_platform"] == "Zoom"

    solo = {k: v for k, v in base.items() if k != "attendees"} | {"organizer": {"email": "me@example.com", "self": True}}
    parsed = calendar_service.parse_event(solo, "me@example.com")
    assert parsed["is_organizer"] is True and parsed["invitees"][0]["email"] == "me@example.com"


async def _link_calendar(user: User, code: str, *, auto_join: str = "all", is_organizer: bool = False, invitees=None) -> uuid_mod.UUID:
    now = datetime.datetime.now(datetime.UTC)
    async with async_session() as db:
        db.add(CalendarConnection(user_id=user.id, google_email=user.email, refresh_token_encrypted=secret_box.encrypt("x"), auto_join=auto_join))
        event = CalendarEvent(
            user_id=user.id,
            google_event_id=f"{TEST_PREFIX}{uuid_mod.uuid4().hex}",
            title=f"{TEST_PREFIX}Linked meeting",
            start_at=now - datetime.timedelta(seconds=10),
            end_at=now + datetime.timedelta(minutes=30),
            meeting_url=f"https://meet.google.com/{code}",
            meeting_code=code,
            is_organizer=is_organizer,
            invitees=invitees or [{"email": user.email, "name": ""}],
        )
        db.add(event)
        await db.commit()
        return event.id


async def test_a_meeting_on_several_calendars_is_recorded_once(member_user, other_member_user):
    code = _code()
    first = await _link_calendar(member_user, code)
    second = await _link_calendar(other_member_user, code)
    async with async_session() as db:
        assert await calendar_service.dispatch_due(db) >= 2
        events = [await db.get(CalendarEvent, first), await db.get(CalendarEvent, second)]
        assert events[0].capture_request_id is not None
        assert events[0].capture_request_id == events[1].capture_request_id
        captures = (await db.execute(select(CaptureRequest).where(CaptureRequest.meeting_code == code))).scalars().all()
        assert len(captures) == 1 and captures[0].source == "calendar"
        invited = {item["email"] for item in captures[0].invitees}
        assert {member_user.email, other_member_user.email} <= invited
        # Running again (the loop ticks every few seconds) changes nothing.
        await calendar_service.dispatch_due(db)
        assert len((await db.execute(select(CaptureRequest).where(CaptureRequest.meeting_code == code))).scalars().all()) == 1


async def test_rules_and_per_meeting_switches_decide_what_gets_recorded(member_user):
    code = _code()
    event_id = await _link_calendar(member_user, code, auto_join="organized", is_organizer=False)
    async with async_session() as db:
        await calendar_service.dispatch_due(db)
        event = await db.get(CalendarEvent, event_id)
        assert event.capture_request_id is None  # not my meeting, rule says skip
        await calendar_service.apply_override(db, event, True)
        await calendar_service.dispatch_due(db)
        event = await db.get(CalendarEvent, event_id)
        capture_id = event.capture_request_id
        assert capture_id is not None
        # Switched back off before the bot joined: the visit is cancelled.
        await calendar_service.apply_override(db, event, False)
        capture = await db.get(CaptureRequest, capture_id)
        await db.refresh(capture)
        assert capture.status == "cancelled"


async def test_calendar_endpoints(client, member_user):
    with patch.object(settings, "google_client_id", "client-id"), patch.object(settings, "google_client_secret", "secret"):
        state = (await client.get("/api/calendar", headers=auth_headers(member_user))).json()
        assert state == {"configured": True, "connection": None}
        url = (await client.post("/api/calendar/connect", headers=auth_headers(member_user))).json()["url"]
        assert "calendar.events.readonly" in url and "access_type=offline" in url
        # A tampered state never links anyone's calendar.
        bad = await client.get("/api/calendar/callback?state=nope&code=x", follow_redirects=False)
        assert bad.status_code == 303 and "calendar=error" in bad.headers["location"]

    code = _code()
    await _link_calendar(member_user, code)
    events = (await client.get("/api/calendar/events", headers=auth_headers(member_user))).json()
    assert len(events) == 1 and events[0]["will_record"] is True
    switched = await client.patch(f"/api/calendar/events/{events[0]['id']}", json={"record": False}, headers=auth_headers(member_user))
    assert switched.json()["will_record"] is False
    assert (await client.delete("/api/calendar", headers=auth_headers(member_user))).json() == {"ok": True}
    assert (await client.get("/api/calendar/events", headers=auth_headers(member_user))).json() == []


async def test_a_series_nobody_admits_the_notetaker_to_is_skipped_until_switched_on(member_user):
    # Production, 2026-10: daily series where the notetaker waited in the
    # lobby every morning and nobody ever let it in.
    code = _code()
    series = f"gcal:{TEST_PREFIX}{uuid_mod.uuid4().hex}"
    event_id = await _link_calendar(member_user, code)
    now = datetime.datetime.now(datetime.UTC)
    async with async_session() as db:
        event = await db.get(CalendarEvent, event_id)
        event.recurring_event_id = series.removeprefix("gcal:")
        for days in (3, 2, 1):
            db.add(CaptureRequest(
                user_id=member_user.id, platform="google_meet", meeting_url=f"https://meet.google.com/{code}",
                meeting_code=code, status="timed_out", status_detail="Not admitted within 10 minutes",
                consent_acknowledged_at=now, source="calendar", series_key=series,
                created_at=now - datetime.timedelta(days=days),
            ))
        await db.commit()

        await calendar_service.dispatch_due(db)
        await calendar_service.dispatch_due(db)
        event = await db.get(CalendarEvent, event_id)
        assert event.capture_request_id is None
        told = (await db.execute(select(Notification).where(
            Notification.user_id == member_user.id, Notification.type == "notetaker_skipped"
        ))).scalars().all()
        assert len(told) == 1  # once, not every tick

        await calendar_service.apply_override(db, event, True)
        await calendar_service.dispatch_due(db)
        event = await db.get(CalendarEvent, event_id)
        assert event.capture_request_id is not None
        await db.execute(delete(Notification).where(Notification.type == "notetaker_skipped", Notification.user_id == member_user.id))
        await db.commit()
