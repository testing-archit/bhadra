"""Automatic pre-meeting briefs for linked-calendar meetings."""

import datetime
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.config import settings
from app.database.db import async_session
from app.database.models import CalendarConnection, CalendarEvent, Meeting, MeetingAttendee, MeetingTask, Notification
from app.services import calendar_service, secret_box
from tests.conftest import TEST_PREFIX, auth_headers

USAGE = {"input_tokens": 10, "output_tokens": 5, "cache_tokens_read": 0, "cache_tokens_written": 0}


@pytest.fixture(autouse=True)
def _gemini_key():
    with patch.object(settings, "gemini_api_key", "test-key"):
        yield


async def _attend(meeting: Meeting, *, user_id=None, email=None, name="Someone") -> None:
    async with async_session() as db:
        db.add(
            MeetingAttendee(
                meeting_id=meeting.id, user_id=user_id, email=email, display_name=name,
                kind="internal" if user_id else "external", access="granted",
            )
        )
        await db.commit()


async def _task(meeting: Meeting, description: str, status: str = "pending") -> None:
    async with async_session() as db:
        db.add(MeetingTask(meeting_id=meeting.id, description=TEST_PREFIX + description, status=status))
        await db.commit()


async def _event(user, *, invitees, minutes_ahead: float = 5, recurring_event_id=None, title="Weekly sync") -> uuid.UUID:
    now = datetime.datetime.now(datetime.UTC)
    async with async_session() as db:
        if await db.get(CalendarConnection, user.id) is None:
            db.add(CalendarConnection(user_id=user.id, google_email=user.email, refresh_token_encrypted=secret_box.encrypt("x")))
        event = CalendarEvent(
            user_id=user.id,
            google_event_id=f"{TEST_PREFIX}{uuid.uuid4().hex}",
            recurring_event_id=recurring_event_id,
            title=TEST_PREFIX + title,
            start_at=now + datetime.timedelta(minutes=minutes_ahead),
            end_at=now + datetime.timedelta(minutes=minutes_ahead + 30),
            # A Teams call: briefs don't need the notetaker.
            unsupported_platform="Microsoft Teams",
            invitees=invitees,
        )
        db.add(event)
        await db.commit()
        return event.id


async def test_brief_is_written_once_from_shared_meetings_and_notifies(member_user, other_member_user, make_meeting):
    earlier = await make_meeting(member_user, "Pricing review", None)
    await _attend(earlier, user_id=other_member_user.id)
    await _task(earlier, "Send revised quote")
    await _task(earlier, "Already shipped", status="done")
    event_id = await _event(member_user, invitees=[{"email": member_user.email}, {"email": other_member_user.email}])
    far_id = await _event(member_user, invitees=[{"email": other_member_user.email}], minutes_ahead=90)

    with patch("app.services.prep_service.generate_text", return_value=("- Quote pending [M1] [M7]", USAGE)) as generate:
        async with async_session() as db:
            await calendar_service.prepare_briefs(db)
            await calendar_service.prepare_briefs(db)  # the loop ticks again
    generate.assert_called_once()
    assert generate.call_args.kwargs["feature"] == "pre_meeting_brief"

    async with async_session() as db:
        event = await db.get(CalendarEvent, event_id)
        assert event.brief["status"] == "ready"
        assert event.brief["text"] == "- Quote pending [M1]"  # unresolvable [M7] dropped
        assert [m["id"] for m in event.brief["meetings"]] == [str(earlier.id)]
        assert [t["description"] for t in event.brief["open_tasks"]] == [f"{TEST_PREFIX}Send revised quote"]
        assert (await db.get(CalendarEvent, far_id)).brief_generated_at is None
        notes = (
            await db.execute(select(Notification).where(Notification.user_id == member_user.id, Notification.type == "pre_meeting_brief"))
        ).scalars().all()
        assert len(notes) == 1 and notes[0].link == f"/dashboard?brief={event_id}"


async def test_brief_never_uses_meetings_the_person_cannot_read(member_user, other_member_user, make_meeting):
    # The colleague's private meeting with a third party: not visible to member_user.
    private = await make_meeting(other_member_user, "Private one-to-one", None)
    await _attend(private, user_id=other_member_user.id)
    event_id = await _event(member_user, invitees=[{"email": other_member_user.email}])

    with patch("app.services.prep_service.generate_text") as generate:
        async with async_session() as db:
            await calendar_service.prepare_briefs(db)
    generate.assert_not_called()
    async with async_session() as db:
        event = await db.get(CalendarEvent, event_id)
        assert event.brief["status"] == "empty" and event.brief_generated_at is not None


async def test_external_guests_and_the_previous_occurrence_are_included(member_user, make_meeting):
    client_email = f"{TEST_PREFIX}{uuid.uuid4().hex[:6]}@client.example"
    with_client = await make_meeting(member_user, "Client kickoff", None)
    await _attend(with_client, email=client_email.upper(), name="Client")
    series = f"gcal:{TEST_PREFIX}{uuid.uuid4().hex}"
    previous = await make_meeting(member_user, "Sync #3", None)
    async with async_session() as db:
        (await db.get(Meeting, previous.id)).series_key = series
        await db.commit()
    await _task(previous, "Carry this over")
    event_id = await _event(
        member_user, invitees=[{"email": member_user.email}, {"email": client_email}], recurring_event_id=series.removeprefix("gcal:")
    )

    with patch("app.services.prep_service.generate_text", return_value=("ok", USAGE)) as generate:
        async with async_session() as db:
            await calendar_service.prepare_briefs(db)
    assert "previous occurrence" in generate.call_args.args[1]
    async with async_session() as db:
        brief = (await db.get(CalendarEvent, event_id)).brief
    ids = [m["id"] for m in brief["meetings"]]
    assert ids[0] == str(previous.id) and str(with_client.id) in ids
    assert brief["meetings"][0]["previous_occurrence"] is True
    assert brief["open_tasks"][0]["description"] == f"{TEST_PREFIX}Carry this over"


async def test_failed_brief_is_stored_not_retried_and_shown(client, member_user, other_member_user, make_meeting):
    earlier = await make_meeting(member_user, "Roadmap", None)
    await _attend(earlier, user_id=other_member_user.id)
    await _event(member_user, invitees=[{"email": other_member_user.email}])
    with patch("app.services.prep_service.generate_text", side_effect=RuntimeError("quota")) as generate:
        async with async_session() as db:
            await calendar_service.prepare_briefs(db)
            await calendar_service.prepare_briefs(db)
    assert generate.call_count == 1
    events = (await client.get("/api/calendar/events", headers=auth_headers(member_user))).json()
    assert events[0]["brief"]["status"] == "failed" and "quota" in events[0]["brief"]["error"]


async def test_prep_endpoint_still_works_and_is_billed(client, member_user, other_member_user, make_meeting):
    earlier = await make_meeting(member_user, "Hiring plan", None)
    await _attend(earlier, user_id=other_member_user.id)
    with patch("app.services.prep_service.generate_text", return_value=("- Plan [M1]", USAGE)) as generate:
        response = await client.post(
            "/api/meetings/prep", json={"attendee_user_ids": [str(other_member_user.id)]}, headers=auth_headers(member_user)
        )
    body = response.json()
    assert response.status_code == 200 and body["brief"] == "- Plan [M1]"
    assert body["meetings"][0]["tag"] == "M1"
    assert generate.call_args.kwargs["feature"] == "meeting_prep"
