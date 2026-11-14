"""Post-meeting follow-ups: each task owner with a Charcha account is told
what they were given, once."""

import json
import uuid
from unittest.mock import patch

from sqlalchemy import select

from app.database.db import async_session
from app.database.models import Decision, Meeting, MeetingAttendee, MeetingTask, Notification, Trace, User
from app.services import followup_service
from tests.conftest import TEST_PREFIX, auth_headers


async def _notes(user_id) -> list[Notification]:
    async with async_session() as db:
        return list(
            (
                await db.execute(
                    select(Notification).where(Notification.user_id == user_id, Notification.type == "tasks_assigned")
                )
            ).scalars().all()
        )


async def test_each_resolved_owner_is_told_once(member_user, other_member_user, admin_user, make_meeting):
    meeting = await make_meeting(member_user, "Launch plan", None)
    async with async_session() as db:
        db.add(MeetingAttendee(meeting_id=meeting.id, user_id=other_member_user.id, display_name="O", access="granted"))
        # Heard in the call but not on the invite: can't open the meeting yet.
        db.add(MeetingAttendee(meeting_id=meeting.id, user_id=admin_user.id, display_name="A", access="pending"))
        for owner, status in (
            (other_member_user.id, "pending"),
            (other_member_user.id, "in_progress"),
            (other_member_user.id, "done"),  # finished already: not counted
            (admin_user.id, "pending"),
            (None, "pending"),  # owner said aloud but not matched to anyone
        ):
            db.add(MeetingTask(meeting_id=meeting.id, owner_user_id=owner, description=TEST_PREFIX + "t", status=status))
        await db.commit()

    assert await followup_service.notify_task_owners(meeting.id) == 1
    assert await followup_service.notify_task_owners(meeting.id) == 0  # reprocessing repeats nothing

    [note] = await _notes(other_member_user.id)
    assert note.message == f'You were given 2 tasks in "{meeting.title}"'
    assert note.link == f"/meetings/{meeting.id}?tab=actions"
    # Not in the meeting (pending; being an admin doesn't count): told nothing.
    assert await _notes(admin_user.id) == []
    assert await _notes(member_user.id) == []


async def test_a_task_for_someone_not_in_the_meeting_is_held_for_the_recorder(member_user, other_member_user, make_meeting):
    meeting = await make_meeting(member_user, "Ops review", None)
    async with async_session() as db:
        db.add(MeetingAttendee(meeting_id=meeting.id, user_id=other_member_user.id, display_name="O", access="pending"))
        db.add(MeetingTask(meeting_id=meeting.id, owner_user_id=other_member_user.id, description=TEST_PREFIX + "t"))
        await db.commit()
    await followup_service.notify_task_owners(meeting.id)
    await followup_service.notify_task_owners(meeting.id)
    assert await _notes(other_member_user.id) == []
    async with async_session() as db:
        held = (await db.execute(
            select(Notification).where(Notification.user_id == member_user.id, Notification.type == "tasks_held")
        )).scalars().all()
    [note] = held  # once per meeting
    assert note.link == f"/meetings/{meeting.id}?tab=actions" and "1 task" in note.message


async def test_ingest_notifies_the_named_owner(client, member_user, other_member_user, mock_extraction, mock_qdrant_upsert):
    # Both fixture users share a name, which (correctly) resolves to nobody.
    name = f"{TEST_PREFIX}Meera {uuid.uuid4().hex[:6]}"
    async with async_session() as db:
        (await db.get(User, other_member_user.id)).name = name
        await db.commit()
    mock_extraction.return_value["tasks"] = [
        {"task": "Ship the pricing page", "assignedTo": name, "dueDate": "", "priority": "", "project": ""}
    ]
    response = await client.post(
        "/api/meetings/ingest",
        headers=auth_headers(member_user),
        data={
            "meeting_title": f"{TEST_PREFIX}Pricing sync",
            "duration_minutes": "5",
            "transcript": "Please ship the pricing page.",
            "attendees": json.dumps([{"email": other_member_user.email, "name": name}]),
        },
    )
    assert response.status_code == 200
    meeting_id = uuid.UUID(response.json()["meeting_id"])
    try:
        [note] = await _notes(other_member_user.id)
        assert note.message == f'You were given 1 task in "{TEST_PREFIX}Pricing sync"'
    finally:
        async with async_session() as db:
            for table in (Trace, MeetingTask, Decision):
                await db.execute(table.__table__.delete().where(table.meeting_id == meeting_id))
            await db.execute(Meeting.__table__.delete().where(Meeting.id == meeting_id))
            await db.commit()


async def test_failed_extraction_sends_nothing(client, member_user, mock_extraction, mock_qdrant_upsert):
    mock_extraction.side_effect = RuntimeError("model down")
    with patch("app.services.followup_service.notify_task_owners") as notify:
        response = await client.post(
            "/api/meetings/ingest",
            headers=auth_headers(member_user),
            data={"meeting_title": f"{TEST_PREFIX}No notes", "duration_minutes": "1", "transcript": "hello"},
        )
    notify.assert_not_called()
    meeting_id = response.json().get("meeting_id")
    if meeting_id:
        async with async_session() as db:
            mid = uuid.UUID(meeting_id)
            await db.execute(Trace.__table__.delete().where(Trace.meeting_id == mid))
            await db.execute(Meeting.__table__.delete().where(Meeting.id == mid))
            await db.commit()
