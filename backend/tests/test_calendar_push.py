"""Google Calendar push: a meeting added minutes before it starts is still
picked up, because Google tells Charcha the moment the calendar changes."""

import datetime
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import delete

from app.config import settings
from app.database.db import async_session
from app.database.models import CalendarConnection, CalendarEvent, CaptureRequest
from app.services import calendar_service, secret_box
from tests.conftest import auth_headers


class FakeGoogle:
    """Answers the watch, stop and token calls Google would."""

    def __init__(self, watch_status=200):
        self.watch_status = watch_status
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def post(self, url, json=None, data=None, headers=None):
        self.calls.append((url, json or data or {}))
        request = httpx.Request("POST", url)
        if url == calendar_service.WATCH_URL:
            if self.watch_status != 200:
                return httpx.Response(self.watch_status, json={"error": {"message": "Unauthorized WebHook callback channel"}}, request=request)
            expires = int((datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=7)).timestamp() * 1000)
            return httpx.Response(200, json={"resourceId": "res-" + json["id"][:8], "expiration": str(expires)}, request=request)
        return httpx.Response(204, request=request)


@pytest.fixture(autouse=True)
def _public_url():
    with patch.object(settings, "public_api_url", "https://charcha.example.com"):
        yield


async def _connection(user) -> None:
    async with async_session() as db:
        db.add(CalendarConnection(user_id=user.id, google_email=user.email, refresh_token_encrypted=secret_box.encrypt("x")))
        await db.commit()


async def _sync(user, events, google):
    with patch.object(calendar_service, "access_token", AsyncMock(return_value="t")), \
            patch.object(calendar_service, "fetch_events", AsyncMock(return_value=events)), \
            patch.object(calendar_service.httpx, "AsyncClient", lambda **_: google):
        async with async_session() as db:
            await calendar_service.sync_connection(db, await db.get(CalendarConnection, user.id))


def _meet_event(start: datetime.datetime, code="abc-defg-hij") -> dict:
    return {
        "id": f"pytest_{uuid.uuid4().hex}", "status": "confirmed", "summary": "Last-minute call",
        "start": {"dateTime": start.isoformat()}, "end": {"dateTime": (start + datetime.timedelta(minutes=30)).isoformat()},
        "hangoutLink": f"https://meet.google.com/{code}", "organizer": {"self": True},
    }


async def test_a_channel_is_opened_renewed_and_reported(client, member_user):
    await _connection(member_user)
    google = FakeGoogle()
    await _sync(member_user, [], google)
    async with async_session() as db:
        connection = await db.get(CalendarConnection, member_user.id)
        first = connection.watch_channel_id
        assert first and connection.watch_token and calendar_service.watch_active(connection)
    watch_body = google.calls[0][1]
    assert watch_body["address"] == "https://charcha.example.com/api/calendar/push" and watch_body["type"] == "web_hook"

    # A sync with plenty of time left reuses the channel…
    await _sync(member_user, [], google)
    assert sum(1 for url, _ in google.calls if url == calendar_service.WATCH_URL) == 1
    # …and one close to expiry replaces it, stopping the old one.
    async with async_session() as db:
        connection = await db.get(CalendarConnection, member_user.id)
        connection.watch_expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=2)
        await db.commit()
    await _sync(member_user, [], google)
    async with async_session() as db:
        connection = await db.get(CalendarConnection, member_user.id)
        assert connection.watch_channel_id != first
    assert any(url == calendar_service.STOP_URL and body["id"] == first for url, body in google.calls)
    state = (await client.get("/api/calendar", headers=auth_headers(member_user))).json()
    assert state["connection"]["live_updates"] is True


async def test_a_push_resyncs_at_once_and_a_last_minute_meeting_is_joined(client, member_user):
    await _connection(member_user)
    google = FakeGoogle()
    await _sync(member_user, [], google)
    async with async_session() as db:
        connection = await db.get(CalendarConnection, member_user.id)
        channel, token = connection.watch_channel_id, connection.watch_token

    # Forged or unknown channels are ignored (but still answered 200).
    forged = await client.post("/api/calendar/push", headers={"X-Goog-Channel-ID": channel, "X-Goog-Channel-Token": "nope", "X-Goog-Resource-State": "exists"})
    assert forged.status_code == 200
    async with async_session() as db:
        assert (await db.get(CalendarConnection, member_user.id)).last_synced_at is not None

    # The handshake doesn't trigger a sync; a real change does.
    await client.post("/api/calendar/push", headers={"X-Goog-Channel-ID": channel, "X-Goog-Channel-Token": token, "X-Goog-Resource-State": "sync"})
    async with async_session() as db:
        assert (await db.get(CalendarConnection, member_user.id)).last_synced_at is not None
    calendar_service._wake.clear()
    await client.post("/api/calendar/push", headers={"X-Goog-Channel-ID": channel, "X-Goog-Channel-Token": token, "X-Goog-Resource-State": "exists"})
    assert calendar_service._wake.is_set()
    async with async_session() as db:
        assert (await db.get(CalendarConnection, member_user.id)).last_synced_at is None

    # The loop's next pass reads the meeting someone just added for 50 s from
    # now and queues the notetaker in the same pass.
    code = "pqr-stuv-wxy"
    added = _meet_event(datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=50), code)
    with patch.object(calendar_service, "access_token", AsyncMock(return_value="t")), \
            patch.object(calendar_service, "fetch_events", AsyncMock(return_value=[added])), \
            patch.object(calendar_service.httpx, "AsyncClient", lambda **_: google), \
            patch.object(settings, "gemini_api_key", ""):
        await calendar_service._sync_and_dispatch()
    async with async_session() as db:
        from sqlalchemy import select

        event = (await db.execute(select(CalendarEvent).where(CalendarEvent.google_event_id == added["id"]))).scalar_one()
        assert event.capture_request_id is not None
        await db.execute(delete(CaptureRequest).where(CaptureRequest.id == event.capture_request_id))
        await db.commit()


async def test_refused_channels_fall_back_to_fast_polling(client, member_user):
    await _connection(member_user)
    await _sync(member_user, [], FakeGoogle(watch_status=401))
    async with async_session() as db:
        connection = await db.get(CalendarConnection, member_user.id)
        assert connection.watch_channel_id is None and "polling every" in connection.watch_error
        # Synced 2 minutes ago without push: due again (60 s poll).
        connection.last_synced_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=2)
        await db.commit()
    picked = []
    with patch.object(calendar_service, "sync_connection", AsyncMock(side_effect=lambda db, c: picked.append(c.user_id))), \
            patch.object(calendar_service, "dispatch_due", AsyncMock()), patch.object(calendar_service, "prepare_briefs", AsyncMock()):
        await calendar_service._sync_and_dispatch()
    assert member_user.id in picked
    state = (await client.get("/api/calendar", headers=auth_headers(member_user))).json()["connection"]
    assert state["live_updates"] is False and state["live_updates_error"]


async def test_live_calendars_wait_for_the_safety_net_interval(member_user):
    await _connection(member_user)
    await _sync(member_user, [], FakeGoogle())
    async with async_session() as db:
        connection = await db.get(CalendarConnection, member_user.id)
        connection.last_synced_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=2)
        await db.commit()
    picked = []
    with patch.object(calendar_service, "sync_connection", AsyncMock(side_effect=lambda db, c: picked.append(c.user_id))), \
            patch.object(calendar_service, "dispatch_due", AsyncMock()), patch.object(calendar_service, "prepare_briefs", AsyncMock()):
        await calendar_service._sync_and_dispatch()
    assert member_user.id not in picked  # push will say when it changes


async def test_schedule_shows_past_and_upcoming_with_notes_links(client, member_user, other_member_user, make_meeting):
    from app.database.models import Meeting, MeetingAttendee

    await _connection(member_user)
    now = datetime.datetime.now(datetime.UTC)
    code, other_code = "abc-defg-hij", "zzz-yyyy-xxx"
    recorded = await make_meeting(member_user, "Recorded sync", None)
    hidden = await make_meeting(other_member_user, "Someone else's private call", None)
    async with async_session() as db:
        for meeting, meet_code, when in ((recorded, code, now - datetime.timedelta(days=2)), (hidden, other_code, now - datetime.timedelta(days=1))):
            row = await db.get(Meeting, meeting.id)
            row.meeting_code, row.date = meet_code, when
        def event(title, start, minutes=30, meet_code=None, platform=None, **extra):
            return CalendarEvent(
                user_id=member_user.id, google_event_id=f"pytest_{uuid.uuid4().hex}", title=title, start_at=start,
                end_at=start + datetime.timedelta(minutes=minutes), meeting_code=meet_code,
                meeting_url=f"https://meet.google.com/{meet_code}" if meet_code else None, unsupported_platform=platform,
                invitees=[{"email": "a@example.com", "name": "Asha"}, {"email": "dana@acme.example", "name": ""}], **extra,
            )
        db.add_all([
            event("Recorded sync", now - datetime.timedelta(days=2, minutes=5), meet_code=code),
            event("Private call", now - datetime.timedelta(days=1, minutes=5), meet_code=other_code),
            event("Vendor call", now - datetime.timedelta(hours=1), platform="Microsoft Teams"),
            event("Happening now", now - datetime.timedelta(minutes=10), meet_code="liv-eeee-now"),
            event("Tomorrow's review", now + datetime.timedelta(days=1), meet_code="tom-orro-wxx"),
            event("Too old", now - datetime.timedelta(days=20), meet_code="old-oooo-old"),
            event("Cancelled", now + datetime.timedelta(hours=2), meet_code="can-cccc-cel", cancelled=True),
        ])
        await db.commit()

    body = (await client.get("/api/calendar/schedule?past_days=14&future_days=7", headers=auth_headers(member_user))).json()
    assert body["connection"]["google_email"] == member_user.email
    by_title = {e["title"]: e for e in body["events"]}
    assert "Too old" not in by_title and "Cancelled" not in by_title
    assert by_title["Recorded sync"]["when"] == "past" and by_title["Recorded sync"]["notes"]["id"] == str(recorded.id)
    # A recording the person can't open is never linked or revealed.
    assert by_title["Private call"]["notes"] is None
    assert by_title["Vendor call"]["platform"] == "Microsoft Teams"
    assert by_title["Happening now"]["when"] == "live"
    assert by_title["Tomorrow's review"]["when"] == "upcoming" and by_title["Tomorrow's review"]["platform"] == "Google Meet"
    assert by_title["Tomorrow's review"]["invitee_names"] == ["Asha", "dana"]
    assert [e["title"] for e in body["events"]] == sorted(by_title, key=lambda t: by_title[t]["start_at"])

    # Without a linked calendar: nothing, and no error.
    assert (await client.get("/api/calendar/schedule", headers=auth_headers(other_member_user))).json() == {"connection": None, "events": []}
