"""Add-the-notetaker-by-link: request lifecycle as the user and the bot see it."""

import datetime
import json
import uuid as uuid_mod
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select

from app.config import settings
from app.database.db import async_session
from app.database.models import CaptureEvent, CaptureRequest, Meeting, ServiceHeartbeat
from app.rate_limit import limiter
from app.services import capture_service
from tests.conftest import TEST_PREFIX, auth_headers

BOT_SECRET = "pytest-capture-secret"
BOT = {"Authorization": f"Bot {BOT_SECRET}"}


def _url() -> str:
    letters = "abcdefghijklmnopqrstuvwxyz"
    raw = uuid_mod.uuid4().int
    code = "".join(letters[(raw >> (5 * i)) % 26] for i in range(10))
    return f"https://meet.google.com/{code[:3]}-{code[3:7]}-{code[7:]}"


@pytest.fixture(autouse=True)
def configured():
    with patch.object(settings, "bot_api_secret", BOT_SECRET), patch.object(limiter, "enabled", False):
        yield


@pytest.fixture(autouse=True)
async def clean_requests(member_user, other_member_user):
    yield
    async with async_session() as db:
        await db.execute(delete(CaptureRequest).where(CaptureRequest.user_id.in_([member_user.id, other_member_user.id])))
        await db.commit()


async def _create(client, user, **body):
    payload = {"meeting_url": _url(), "consent_acknowledged": True, **body}
    return await client.post("/api/capture/requests", json=payload, headers=auth_headers(user))


async def _event(client, request_id, status, *, event_id=None, occurred_at=None):
    return await client.post(
        f"/api/bot/capture-requests/{request_id}/events",
        headers=BOT,
        json={
            "event_id": event_id or uuid_mod.uuid4().hex,
            "status": status,
            "detail": status,
            "occurred_at": (occurred_at or datetime.datetime.now(datetime.UTC)).isoformat(),
        },
    )


async def test_setup_required_without_a_bot_secret(client, member_user):
    with patch.object(settings, "bot_api_secret", ""):
        response = await _create(client, member_user)
    assert response.status_code == 503 and "Setup required" in response.json()["detail"]


async def test_consent_and_supported_links_are_required(client, member_user):
    assert (await _create(client, member_user, consent_acknowledged=False)).status_code == 422
    response = await _create(client, member_user, meeting_url="https://zoom.us/j/123456")
    assert response.status_code == 422 and "Zoom" in response.json()["detail"]


async def test_duplicate_submissions_never_send_two_bots(client, member_user, other_member_user):
    url = _url()
    first = await _create(client, member_user, meeting_url=url, idempotency_key="abcdefgh1")
    assert first.status_code == 201 and first.json()["status"] == "requested"
    # Same idempotency key, then the same link without one: both resolve to the first request.
    again = await _create(client, member_user, meeting_url=url, idempotency_key="abcdefgh1")
    assert again.json()["id"] == first.json()["id"] and again.json()["deduplicated"] is True
    same_link = await _create(client, member_user, meeting_url=url.upper().replace("HTTPS://MEET.GOOGLE.COM", "https://meet.google.com"))
    assert same_link.json()["id"] == first.json()["id"]
    # A colleague pasting the same link joins the same visit: no second bot.
    colleague = await _create(client, other_member_user, meeting_url=url)
    assert colleague.status_code == 201
    assert colleague.json()["id"] == first.json()["id"] and colleague.json()["joined_existing"] is True
    assert colleague.json()["subscriber_count"] == 2

    claimed = (await client.post("/api/bot/capture-requests/claim", headers=BOT, json={"capacity": 5})).json()["jobs"]
    assert [job["capture_request_id"] for job in claimed if job["meet_url"] == url.lower()] == [first.json()["id"]]
    # The notetaker's chat notice names who invited it.
    job = next(job for job in claimed if job["capture_request_id"] == first.json()["id"])
    assert job["requested_by_name"] == (member_user.name or member_user.email.split("@")[0])
    assert "app_url" in job
    # A second poll (another replica, or the next tick) gets nothing new.
    again = (await client.post("/api/bot/capture-requests/claim", headers=BOT, json={"capacity": 5})).json()["jobs"]
    assert first.json()["id"] not in {job["capture_request_id"] for job in again}


async def test_status_follows_bot_evidence_only_forward(client, member_user):
    created = (await _create(client, member_user)).json()
    request_id = created["id"]
    status = (await client.get("/api/capture/status", headers=auth_headers(member_user))).json()
    await client.post("/api/bot/capture-requests/claim", headers=BOT, json={"capacity": 5})
    status = (await client.get("/api/capture/status", headers=auth_headers(member_user))).json()
    assert status["configured"] is True and status["online"] is True

    t0 = datetime.datetime.now(datetime.UTC)
    assert (await _event(client, request_id, "waiting_for_admission", event_id="evt-wait-0001", occurred_at=t0)).json()["applied"] is True
    duplicate = (await _event(client, request_id, "waiting_for_admission", event_id="evt-wait-0001", occurred_at=t0)).json()
    assert duplicate["duplicate"] is True
    assert (await _event(client, request_id, "capturing", occurred_at=t0 + datetime.timedelta(seconds=5))).json()["applied"] is True
    # A delayed "joining" event must not move a recording request backwards.
    late = (await _event(client, request_id, "joining", occurred_at=t0 - datetime.timedelta(seconds=30))).json()
    assert late["applied"] is False and late["status"] == "capturing"

    stop = (await client.post(f"/api/capture/requests/{request_id}/stop", headers=auth_headers(member_user))).json()
    assert stop["stop_requested"] is True and stop["status"] == "capturing"
    assert (await client.get(f"/api/bot/capture-requests/{request_id}", headers=BOT)).json()["stop_requested"] is True
    await _event(client, request_id, "stopped")
    # Nothing moves a finished request back to "capturing".
    assert (await _event(client, request_id, "capturing")).json()["applied"] is False
    async with async_session() as db:
        events = (await db.execute(select(CaptureEvent).where(CaptureEvent.capture_request_id == uuid_mod.UUID(request_id)))).scalars().all()
    assert len(events) == 5  # every distinct event is kept for the record, applied or not


async def test_stopping_an_unclaimed_request_cancels_it(client, member_user):
    created = (await _create(client, member_user)).json()
    stopped = (await client.post(f"/api/capture/requests/{created['id']}/stop", headers=auth_headers(member_user))).json()
    assert stopped["status"] == "cancelled"


async def _set_notetaker_seen(seconds_ago: int | None) -> None:
    async with async_session() as db:
        await db.execute(delete(ServiceHeartbeat).where(ServiceHeartbeat.name == "notetaker"))
        if seconds_ago is not None:
            db.add(ServiceHeartbeat(name="notetaker", last_seen_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=seconds_ago)))
        await db.commit()


async def _age_request(request_id: str, minutes: int) -> None:
    async with async_session() as db:
        row = await db.get(CaptureRequest, uuid_mod.UUID(request_id))
        row.created_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=minutes)
        await db.commit()


@pytest.fixture
def sweep_on_every_read():
    """Status reads normally sweep timeouts at most every 30 s per process."""
    with patch.object(capture_service, "EXPIRY_SWEEP_SECONDS", 0):
        yield


async def test_status_reads_sweep_timeouts_at_most_every_30_seconds(client, member_user):
    await _set_notetaker_seen(None)
    created = (await _create(client, member_user)).json()  # creating always sweeps
    await _age_request(created["id"], 60)
    with patch.object(capture_service, "_last_sweep", capture_service.time.monotonic()):
        fetched = (await client.get(f"/api/capture/requests/{created['id']}", headers=auth_headers(member_user))).json()
        assert fetched["status"] == "requested"  # swept moments ago: not yet
    with patch.object(capture_service, "_last_sweep", 0.0):
        fetched = (await client.get(f"/api/capture/requests/{created['id']}", headers=auth_headers(member_user))).json()
        assert fetched["status"] == "timed_out"


@pytest.mark.usefixtures("sweep_on_every_read")
async def test_unclaimed_requests_time_out_when_the_notetaker_is_offline(client, member_user):
    await _set_notetaker_seen(None)
    created = (await _create(client, member_user)).json()
    await _age_request(created["id"], 60)
    fetched = (await client.get(f"/api/capture/requests/{created['id']}", headers=auth_headers(member_user))).json()
    assert fetched["status"] == "timed_out" and "offline" in fetched["status_detail"]


@pytest.mark.usefixtures("sweep_on_every_read")
async def test_requests_wait_in_the_queue_while_notetakers_are_busy(client, member_user):
    # Online but at capacity: a 20-minute-old request is still waiting, not lost.
    await _set_notetaker_seen(5)
    created = (await _create(client, member_user)).json()
    await _age_request(created["id"], 20)
    fetched = (await client.get(f"/api/capture/requests/{created['id']}", headers=auth_headers(member_user))).json()
    assert fetched["status"] == "requested"
    # ...until the queue window passes.
    await _age_request(created["id"], settings.capture_queue_timeout_minutes + 5)
    await _set_notetaker_seen(5)
    fetched = (await client.get(f"/api/capture/requests/{created['id']}", headers=auth_headers(member_user))).json()
    assert fetched["status"] == "timed_out" and "busy" in fetched["status_detail"]


async def test_stop_keeps_the_notetaker_for_colleagues_who_still_want_it(client, member_user, other_member_user):
    url = _url()
    first = (await _create(client, member_user, meeting_url=url)).json()
    await _create(client, other_member_user, meeting_url=url)
    claimed = (await client.post("/api/bot/capture-requests/claim", headers=BOT, json={"capacity": 5})).json()["jobs"]
    assert first["id"] in {job["capture_request_id"] for job in claimed}

    # The colleague stops: the requester still wants it, so the bot stays.
    stopped = (await client.post(f"/api/capture/requests/{first['id']}/stop", headers=auth_headers(other_member_user))).json()
    assert stopped["kept_for_others"] is True and stopped["stop_requested"] is False
    # The last subscriber stops: now it leaves.
    stopped = (await client.post(f"/api/capture/requests/{first['id']}/stop", headers=auth_headers(member_user))).json()
    assert stopped["kept_for_others"] is False and stopped["stop_requested"] is True


async def test_extension_lookup_shows_a_colleagues_notetaker(client, member_user, other_member_user):
    url = _url()
    first = (await _create(client, member_user, meeting_url=url)).json()
    code = url.rsplit("/", 1)[-1].lower()
    seen = (await client.get(f"/api/capture/meet/{code}", headers=auth_headers(other_member_user))).json()["capture"]
    assert seen["id"] == first["id"] and seen["subscribed"] is False and seen["requested_by_you"] is False


async def test_other_users_cannot_see_or_stop_a_request(client, member_user, other_member_user):
    created = (await _create(client, member_user)).json()
    assert (await client.get(f"/api/capture/requests/{created['id']}", headers=auth_headers(other_member_user))).status_code == 404
    assert (await client.post(f"/api/capture/requests/{created['id']}/stop", headers=auth_headers(other_member_user))).status_code == 404


async def test_bot_ingest_links_the_meeting_and_completes_the_request(client, member_user, mock_extraction):
    created = (await _create(client, member_user, title=f"{TEST_PREFIX}Live capture", template="sales")).json()
    job = next(
        j for j in (await client.post("/api/bot/capture-requests/claim", headers=BOT, json={"capacity": 10})).json()["jobs"]
        if j["capture_request_id"] == created["id"]
    )
    await _event(client, created["id"], "capturing")
    await _event(client, created["id"], "stopped")
    metadata = {
        "event_id": job["event_id"], "event_start": job["event_start"], "title": f"{TEST_PREFIX}Live capture",
        "organizer_email": "someone-else@outside.example", "attendees": [],
        "captions": [{"speaker": "Asha", "text": "Budget is five lakh", "start": 0, "end": 2}],
        "capture_request_id": created["id"],
    }
    with patch("app.services.qdrant_service.upsert_meeting"):
        response = await client.post("/api/bot/ingest", headers=BOT, data={"metadata": json.dumps(metadata)})
    assert response.status_code == 200, response.text
    meeting_id = response.json()["meeting_id"]
    try:
        fetched = (await client.get(f"/api/capture/requests/{created['id']}", headers=auth_headers(member_user))).json()
        assert fetched["status"] == "completed" and fetched["meeting_id"] == meeting_id
        detail = (await client.get(f"/api/meetings/{meeting_id}", headers=auth_headers(member_user))).json()
        # Filed under the person who asked, not the (external) organizer.
        assert detail["source"] == "capture" and detail["template"] == "sales"
        assert mock_extraction.call_args.kwargs["template"] == "sales"
    finally:
        async with async_session() as db:
            from app.database.models import Decision, MeetingTask, Trace

            mid = uuid_mod.UUID(meeting_id)
            for model in (Trace, MeetingTask, Decision):
                await db.execute(delete(model).where(model.meeting_id == mid))
            await db.execute(delete(Meeting).where(Meeting.id == mid))
            await db.commit()


TEAMS_URL = "https://teams.microsoft.com/meet/29384756102345?p=AbC123"


async def test_a_teams_link_goes_only_to_a_notetaker_that_can_join_it(client, member_user, other_member_user):
    first = await _create(client, member_user, meeting_url=TEAMS_URL)
    assert first.status_code == 201
    assert first.json()["platform"] == "microsoft_teams"
    assert first.json()["meeting_code"] == "teams-29384756102345"
    # A second person asking for the same meeting shares the one visit.
    second = await _create(client, other_member_user, meeting_url=TEAMS_URL)
    assert second.status_code == 201 and second.json()["id"] == first.json()["id"] and second.json()["joined_existing"]

    # A notetaker from before Teams sends no platforms, and must not get it.
    old = await client.post("/api/bot/capture-requests/claim", headers=BOT, json={"capacity": 10})
    assert first.json()["id"] not in {job["capture_request_id"] for job in old.json()["jobs"]}
    new = await client.post(
        "/api/bot/capture-requests/claim",
        headers=BOT,
        json={"capacity": 10, "platforms": ["google_meet", "microsoft_teams"]},
    )
    job = next(job for job in new.json()["jobs"] if job["capture_request_id"] == first.json()["id"])
    assert job["meet_url"] == TEAMS_URL and job["meeting_code"] == "teams-29384756102345"
