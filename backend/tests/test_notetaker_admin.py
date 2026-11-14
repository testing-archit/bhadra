"""Admin → Notetaker: capacity per instance, the org-wide queue, and why
visits failed."""

import datetime
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import delete

from app.config import settings
from app.database.db import async_session
from app.database.models import CaptureRequest, ServiceHeartbeat
from app.services.notetaker_monitor import failure_reason
from tests.conftest import TEST_PREFIX, auth_headers

BOT = {"Authorization": "Bot pytest-monitor-secret"}


@pytest.fixture(autouse=True)
def _bot_secret():
    with patch.object(settings, "bot_api_secret", "pytest-monitor-secret"):
        yield


def _code() -> str:
    raw = uuid.uuid4().hex.translate(str.maketrans("0123456789", "ghijklmnop"))
    return f"{raw[:3]}-{raw[3:7]}-{raw[7:10]}"


@pytest.mark.parametrize(
    ("status", "detail", "reason"),
    [
        ("denied", "Someone in the call denied the notetaker's request to join", "denied"),
        ("denied", "Nobody admitted the notetaker before Meet gave up", "not_admitted"),
        ("denied", "Google Meet blocked the notetaker before the host saw a request (the meeting's access settings don't allow it)", "blocked_by_meet"),
        ("denied", "Google Meet blocked the notetaker before the host saw a request: it joins signed out, and …", "signed_out"),
        ("timed_out", "Every notetaker stayed busy in other meetings for 45 minutes, so this one was skipped.", "queue_timeout"),
        ("timed_out", "No notetaker picked this up within 10 minutes. The notetaker service may be offline.", "offline"),
        ("timed_out", "Nobody let the notetaker in within 10 minutes", "not_admitted"),
        ("failed", "TimeoutError: page.goto", "failed"),
    ],
)
def test_failure_reasons(status, detail, reason):
    assert failure_reason(status, detail) == reason


async def test_overview_shows_instances_queue_and_failures(client, member_user, admin_user):
    instance = f"{TEST_PREFIX}{uuid.uuid4().hex[:6]}"
    now = datetime.datetime.now(datetime.UTC)
    ids = []
    async with async_session() as db:
        for status, detail in (
            ("requested", None),
            ("capturing", "Admitted — recording"),
            ("denied", "Someone in the call denied the notetaker's request to join"),
            ("denied", "Google Meet blocked the notetaker before the host saw a request: it joins signed out"),
        ):
            capture = CaptureRequest(
                user_id=member_user.id, platform="google_meet", meeting_code=_code(), meeting_url="https://meet.google.com/x",
                title=f"{TEST_PREFIX}{status}", status=status, status_detail=detail, consent_acknowledged_at=now,
                # Far enough ahead that no notetaker polling this database
                # (a local dev one, say) claims it mid-test.
                scheduled_start=now + datetime.timedelta(hours=1),
            )
            db.add(capture)
            await db.flush()
            ids.append(capture.id)
        await db.commit()
    try:
        # A notetaker at capacity checks in: claims nothing, reports its size.
        claim = await client.post(
            "/api/bot/capture-requests/claim", headers=BOT,
            json={"capacity": 0, "instance": instance, "max_concurrent": 2, "active": 2, "has_auth": True},
        )
        assert claim.json() == {"jobs": []}

        assert (await client.get("/api/admin/notetaker", headers=auth_headers(member_user))).status_code == 403
        body = (await client.get("/api/admin/notetaker", headers=auth_headers(admin_user))).json()
        assert body["online"] is True
        [mine] = [i for i in body["instances"] if i["name"] == instance]
        assert mine == {**mine, "online": True, "max_concurrent": 2, "active": 2, "free": 0, "signed_in": True}
        assert body["capacity"]["total"] >= 2
        assert f"{TEST_PREFIX}requested" in [v["title"] for v in body["queued"]]
        assert body["queue_length"] == len(body["queued"])
        live = [v for v in body["live"] if v["title"] == f"{TEST_PREFIX}capturing"]
        assert live and live[0]["requested_by"]
        reasons = {g["reason"]: g["count"] for g in body["failures"]["groups"]}
        assert reasons.get("denied", 0) >= 1 and reasons.get("signed_out", 0) >= 1
    finally:
        async with async_session() as db:
            await db.execute(delete(CaptureRequest).where(CaptureRequest.id.in_(ids)))
            await db.execute(delete(ServiceHeartbeat).where(ServiceHeartbeat.name == f"notetaker:{instance}"))
            await db.commit()


async def test_old_bots_without_details_still_heartbeat(client):
    response = await client.post("/api/bot/capture-requests/claim", headers=BOT, json={"capacity": 0})
    assert response.status_code == 200
    async with async_session() as db:
        beat = await db.get(ServiceHeartbeat, "notetaker")
        assert (datetime.datetime.now(datetime.UTC) - beat.last_seen_at).total_seconds() < 30
