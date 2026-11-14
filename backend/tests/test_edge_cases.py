"""Edge cases around linked calendars and the notetaker: moved and overrunning
meetings, overlapping meetings, organizers without an account, and the
notetaker losing its Google login."""

import datetime
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, select

from app.config import settings
from app.database.db import async_session
from app.database.models import (
    CalendarConnection,
    CalendarEvent,
    CaptureRequest,
    Decision,
    Meeting,
    MeetingAttendee,
    MeetingTask,
    Notification,
    Trace,
)
from app.services import calendar_service, secret_box
from tests.conftest import TEST_PREFIX, auth_headers

BOT = {"Authorization": "Bot pytest-edge-secret"}


@pytest.fixture(autouse=True)
def _bot_secret():
    with patch.object(settings, "bot_api_secret", "pytest-edge-secret"):
        yield


def _code() -> str:
    raw = uuid.uuid4().hex.translate(str.maketrans("0123456789", "ghijklmnop"))
    return f"{raw[:3]}-{raw[3:7]}-{raw[7:10]}"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


async def _linked_event(user, code: str, *, start: datetime.datetime, minutes: int = 30) -> tuple[uuid.UUID, str]:
    google_id = f"{TEST_PREFIX}{uuid.uuid4().hex}"
    async with async_session() as db:
        if await db.get(CalendarConnection, user.id) is None:
            db.add(CalendarConnection(user_id=user.id, google_email=user.email, refresh_token_encrypted=secret_box.encrypt("x")))
        event = CalendarEvent(
            user_id=user.id, google_event_id=google_id, title=f"{TEST_PREFIX}Sync", start_at=start,
            end_at=start + datetime.timedelta(minutes=minutes), meeting_url=f"https://meet.google.com/{code}",
            meeting_code=code, is_organizer=True, invitees=[{"email": user.email, "name": ""}],
        )
        db.add(event)
        await db.commit()
        return event.id, google_id


def _google_event(google_id: str, code: str, start: datetime.datetime, minutes: int = 30) -> dict:
    return {
        "id": google_id, "status": "confirmed", "summary": f"{TEST_PREFIX}Sync",
        "start": {"dateTime": start.isoformat()}, "end": {"dateTime": (start + datetime.timedelta(minutes=minutes)).isoformat()},
        "hangoutLink": f"https://meet.google.com/{code}", "organizer": {"self": True},
    }


async def _sync(user, events: list[dict]) -> None:
    with patch.object(calendar_service, "access_token", AsyncMock(return_value="t")), patch.object(
        calendar_service, "fetch_events", AsyncMock(return_value=events)
    ):
        async with async_session() as db:
            connection = await db.get(CalendarConnection, user.id)
            await calendar_service.sync_connection(db, connection)


async def _capture_for(event_id) -> CaptureRequest | None:
    async with async_session() as db:
        event = await db.get(CalendarEvent, event_id)
        return await db.get(CaptureRequest, event.capture_request_id) if event.capture_request_id else None


async def test_meeting_moved_later_while_queued_waits_for_its_new_time(client, member_user):
    code = _code()
    # Queued well before its start, so no notetaker sharing this database can
    # claim it between dispatch and the move.
    start = _now() + datetime.timedelta(minutes=8)
    event_id, google_id = await _linked_event(member_user, code, start=start)
    with patch.object(settings, "calendar_join_lead_seconds", 600):
        async with async_session() as db:
            await calendar_service.dispatch_due(db)
    capture = await _capture_for(event_id)
    assert capture is not None and capture.status == "requested"

    later = start + datetime.timedelta(hours=2)
    await _sync(member_user, [_google_event(google_id, code, later)])
    capture = await _capture_for(event_id)
    assert capture.status == "requested" and capture.scheduled_start == later
    # Notetakers with free slots don't take it before its new time.
    jobs = (await client.post("/api/bot/capture-requests/claim", headers=BOT, json={"capacity": 10})).json()["jobs"]
    assert str(capture.id) not in [job["capture_request_id"] for job in jobs]
    # Free those claimed jobs from other tests' leftovers back to the queue.
    async with async_session() as db:
        for job in jobs:
            row = await db.get(CaptureRequest, uuid.UUID(job["capture_request_id"]))
            row.status = "cancelled"
        await db.execute(delete(CaptureRequest).where(CaptureRequest.id == capture.id))
        await db.commit()


async def test_extended_meeting_keeps_the_notetaker_until_the_new_end(client, member_user):
    code = _code()
    start = _now() - datetime.timedelta(minutes=20)
    event_id, google_id = await _linked_event(member_user, code, start=start, minutes=30)
    async with async_session() as db:
        await calendar_service.dispatch_due(db)
        event = await db.get(CalendarEvent, event_id)
        capture = await db.get(CaptureRequest, event.capture_request_id)
        capture.status = "capturing"
        await db.commit()
        capture_id = capture.id

    await _sync(member_user, [_google_event(google_id, code, start, minutes=90)])
    state = (await client.get(f"/api/bot/capture-requests/{capture_id}", headers=BOT)).json()
    assert datetime.datetime.fromisoformat(state["scheduled_end"]) == start + datetime.timedelta(minutes=90)

    # Past the original calendar end and still recording: still on Home.
    async with async_session() as db:
        event = await db.get(CalendarEvent, event_id)
        event.end_at = _now() - datetime.timedelta(minutes=5)
        await db.commit()
    events = (await client.get("/api/calendar/events", headers=auth_headers(member_user))).json()
    assert str(event_id) in [e["id"] for e in events]
    async with async_session() as db:
        await db.execute(delete(CaptureRequest).where(CaptureRequest.id == capture_id))
        await db.commit()


async def test_finished_visit_is_queued_again_when_the_meeting_moves_into_the_future(member_user):
    code = _code()
    start = _now() - datetime.timedelta(minutes=5)
    event_id, google_id = await _linked_event(member_user, code, start=start)
    async with async_session() as db:
        await calendar_service.dispatch_due(db)
        event = await db.get(CalendarEvent, event_id)
        capture = await db.get(CaptureRequest, event.capture_request_id)
        capture.status = "completed"  # nobody came at the old time
        event.brief, event.brief_generated_at = {"status": "ready"}, _now()
        await db.commit()
        capture_id = capture.id

    tomorrow = start + datetime.timedelta(days=1)
    await _sync(member_user, [_google_event(google_id, code, tomorrow)])
    async with async_session() as db:
        event = await db.get(CalendarEvent, event_id)
        assert event.capture_request_id is None  # dispatch_due queues it again near the new time
        assert event.brief is None and event.brief_generated_at is None
        await db.execute(delete(CaptureRequest).where(CaptureRequest.id == capture_id))
        await db.commit()


async def test_same_person_in_two_overlapping_meetings_gets_both_recorded(member_user):
    first_code, second_code = _code(), _code()
    start = _now() - datetime.timedelta(seconds=10)
    first, _ = await _linked_event(member_user, first_code, start=start)
    second, _ = await _linked_event(member_user, second_code, start=start + datetime.timedelta(seconds=5))
    async with async_session() as db:
        await calendar_service.dispatch_due(db)
    one, two = await _capture_for(first), await _capture_for(second)
    assert one is not None and two is not None and one.id != two.id
    assert {one.meeting_code, two.meeting_code} == {first_code, second_code}
    async with async_session() as db:
        await db.execute(delete(CaptureRequest).where(CaptureRequest.id.in_([one.id, two.id])))
        await db.commit()


async def test_organizer_without_an_account_falls_back_to_the_first_internal_invitee(
    client, member_user, other_member_user, mock_extraction, mock_qdrant_upsert
):
    code = _code()
    outsider = f"{TEST_PREFIX}{uuid.uuid4().hex[:6]}@client.example"
    invite = (await client.post(
        "/api/bot/invites", headers=BOT,
        json={
            "meet_url": f"https://meet.google.com/{code}", "title": f"{TEST_PREFIX}Client call", "organizer_email": outsider,
            "attendees": [{"email": outsider, "name": "Client"}, {"email": member_user.email, "name": ""}, {"email": other_member_user.email, "name": ""}],
        },
    )).json()
    assert invite["status"] == "queued"
    capture_id = invite["capture_request_id"]
    async with async_session() as db:
        assert (await db.get(CaptureRequest, uuid.UUID(capture_id))).user_id == member_user.id

    metadata = {
        "event_id": f"capture-{capture_id}", "event_start": _now().isoformat(), "title": f"{TEST_PREFIX}Client call",
        "organizer_email": outsider,
        "attendees": [{"email": outsider, "name": "Client"}, {"email": member_user.email, "name": ""}, {"email": other_member_user.email, "name": ""}],
        "captions": [{"speaker": "Client", "text": "Let's start", "start": 1, "end": 2}],
        "duration_seconds": 120, "capture_request_id": capture_id,
    }
    response = await client.post("/api/bot/ingest", headers=BOT, data={"metadata": json.dumps(metadata)})
    assert response.status_code == 200, response.text
    meeting_id = uuid.UUID(response.json()["meeting_id"])
    try:
        async with async_session() as db:
            meeting = await db.get(Meeting, meeting_id)
            assert meeting.user_id == member_user.id and meeting.organizer_user_id is None
        # The other internal invitee can read it; the outside organizer is recorded as a guest.
        assert (await client.get(f"/api/meetings/{meeting_id}", headers=auth_headers(other_member_user))).status_code == 200
        detail = (await client.get(f"/api/meetings/{meeting_id}", headers=auth_headers(member_user))).json()
        guest = [a for a in detail["attendees"] if a["email"] == outsider]
        assert guest and guest[0]["access"] == "none"
    finally:
        async with async_session() as db:
            for table in (MeetingAttendee, Trace, MeetingTask, Decision):
                await db.execute(table.__table__.delete().where(table.meeting_id == meeting_id))
            await db.execute(delete(CaptureRequest).where(CaptureRequest.id == uuid.UUID(capture_id)))
            await db.execute(Meeting.__table__.delete().where(Meeting.id == meeting_id))
            await db.commit()


async def test_admins_are_told_once_when_the_notetaker_is_signed_out(client, member_user, admin_user):
    async with async_session() as db:
        await db.execute(delete(Notification).where(Notification.type == "notetaker_signed_out"))
        captures = []
        for _ in range(2):
            capture = CaptureRequest(
                user_id=member_user.id, platform="google_meet", meeting_code=_code(), meeting_url="https://meet.google.com/x",
                status="joining", consent_acknowledged_at=_now(),
            )
            db.add(capture)
            captures.append(capture)
        await db.commit()
    detail = (
        "Google Meet blocked the notetaker before the host saw a request: it joins signed out, and this meeting only "
        "lets signed-in Google accounts ask to join."
    )
    try:
        for capture in captures:
            body = {"event_id": uuid.uuid4().hex, "status": "denied", "detail": detail, "occurred_at": _now().isoformat()}
            assert (await client.post(f"/api/bot/capture-requests/{capture.id}/events", headers=BOT, json=body)).json()["applied"]
        async with async_session() as db:
            alerts = (
                await db.execute(select(Notification).where(Notification.user_id == admin_user.id, Notification.type == "notetaker_signed_out"))
            ).scalars().all()
            member_alerts = (
                await db.execute(select(Notification).where(Notification.user_id == member_user.id, Notification.type == "notetaker_signed_out"))
            ).scalars().all()
        assert len(alerts) == 1 and alerts[0].link == "/admin?tab=notetaker"
        assert member_alerts == []
    finally:
        async with async_session() as db:
            await db.execute(delete(CaptureRequest).where(CaptureRequest.id.in_([c.id for c in captures])))
            await db.commit()


async def test_a_visit_that_recorded_nothing_is_closed_with_a_reason(client, member_user):
    code = _code()
    created = (await client.post(
        "/api/capture/requests", headers=auth_headers(member_user),
        json={"meeting_url": f"https://meet.google.com/{code}", "consent_acknowledged": True},
    )).json()
    async with async_session() as db:
        capture = await db.get(CaptureRequest, uuid.UUID(created["id"]))
        capture.status = "stopped"  # left after someone pressed Stop
        await db.commit()
    metadata = {
        "event_id": f"capture-{created['id']}", "event_start": _now().isoformat(), "title": "", "attendees": [],
        "captions": [], "duration_seconds": 13, "capture_request_id": created["id"],
    }
    response = await client.post("/api/bot/ingest", headers=BOT, data={"metadata": json.dumps(metadata)})
    assert response.status_code == 422
    async with async_session() as db:
        capture = await db.get(CaptureRequest, uuid.UUID(created["id"]))
        assert capture.status == "failed" and "Nothing was said" in capture.status_detail and "13 s" in capture.status_detail
        await db.delete(capture)
        await db.commit()


async def test_a_recording_that_never_arrives_stops_showing_as_processing(member_user):
    from app.services import capture_service

    async with async_session() as db:
        capture = CaptureRequest(
            user_id=member_user.id, platform="google_meet", meeting_code=_code(), meeting_url="https://meet.google.com/x",
            status="stopped", consent_acknowledged_at=_now(),
        )
        db.add(capture)
        await db.commit()
        capture.updated_at = _now() - datetime.timedelta(minutes=31)
        await db.commit()
        await capture_service.expire_unclaimed(db)
        await db.commit()
        await db.refresh(capture)
        assert capture.status == "failed" and "never reached Charcha" in capture.status_detail
        await db.delete(capture)
        await db.commit()
