"""Recurring meetings: series links, auto notes style, carry-over review."""

import datetime
import uuid as uuid_mod
from unittest.mock import patch

from sqlalchemy import delete

from app.database.db import async_session
from app.database.models import Meeting, MeetingTask
from app.services import series_service
from tests.conftest import TEST_PREFIX, auth_headers


async def _meeting(user, title, days_ago, series_key, transcript="", template="standup"):
    async with async_session() as db:
        meeting = Meeting(
            user_id=user.id, title=TEST_PREFIX + title, transcript=transcript, summary="s", duration_minutes=15,
            date=datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days_ago),
            series_key=series_key, template=template,
        )
        db.add(meeting)
        await db.commit()
        await db.refresh(meeting)
        return meeting


async def test_series_inherit_style_and_review_previous_open_tasks(client, member_user, other_member_user):
    key = f"gcal:{TEST_PREFIX}{uuid_mod.uuid4().hex}"
    yesterday = await _meeting(member_user, "Sync day 1", 1, key)
    async with async_session() as db:
        done_task = MeetingTask(meeting_id=yesterday.id, description="Give Ravi staging DB access", owner="Archit", status="pending")
        quiet_task = MeetingTask(meeting_id=yesterday.id, description="Draft pricing page copy", owner="Asha", status="pending")
        db.add_all([done_task, quiet_task])
        await db.commit()
        await db.refresh(done_task)
        await db.refresh(quiet_task)
    today = await _meeting(member_user, "Sync day 2", 0, key, transcript="Archit: Ravi, staging access de diya hai, done.\nRavi: haan mil gaya.")
    try:
        async with async_session() as db:
            # Nobody chose a style: the series' previous one is reused, no AI call.
            assert await series_service.resolve_template(db, key, "anything") == "standup"

        fake = series_service._Review(items=[
            series_service._ReviewItem(number=1, status="done", note="Archit gave the access.", excerpt="staging access de diya hai, done"),
            series_service._ReviewItem(number=2, status="not_mentioned"),
        ])
        with patch("app.services.series_service.generate_structured", return_value=(fake, {})), \
             patch.object(series_service.settings, "gemini_api_key", "x"):
            await series_service.review_carry_over(today.id)

        series = (await client.get(f"/api/meetings/{today.id}/series", headers=auth_headers(member_user))).json()
        assert [o["current"] for o in series["occurrences"]] == [True, False]
        statuses = {item["description"]: item["status"] for item in series["review"]["items"]}
        # Newest-first ordering of the previous tasks decides the numbering.
        assert set(statuses.values()) == {"done", "not_mentioned"}
        assert all(item["current_status"] == "pending" for item in series["review"]["items"])

        # Someone without access to the series meetings sees nothing of them.
        assert (await client.get(f"/api/meetings/{today.id}/series", headers=auth_headers(other_member_user))).status_code == 404
    finally:
        async with async_session() as db:
            await db.execute(delete(MeetingTask).where(MeetingTask.meeting_id.in_([yesterday.id, today.id])))
            await db.execute(delete(Meeting).where(Meeting.id.in_([yesterday.id, today.id])))
            await db.commit()


async def test_meeting_type_detection_uses_the_fast_model(member_user):
    with patch("app.services.series_service.generate_structured", return_value=(series_service._MeetingType(type="client_call"), {})) as call, \
         patch.object(series_service.settings, "gemini_api_key", "x"):
        async with async_session() as db:
            assert await series_service.resolve_template(db, None, "Client: we need the export by Friday") == "client_call"
    assert call.call_args.kwargs["model"] == series_service.settings.gemini_fast_model
    assert call.call_args.kwargs["feature"] == "meeting_type"
