import datetime
import uuid

from app.database.db import async_session
from app.database.models import MeetingAttendee, MeetingTask, User
from tests.conftest import TEST_PREFIX, auth_headers


async def _add_task(meeting, description="Do a thing", owner=None):
    async with async_session() as db:
        task = MeetingTask(meeting_id=meeting.id, description=description, status="pending", owner=owner)
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task


async def test_due_date_set_on_create_and_update(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "Due Date Meeting", "Engineering")

    create_response = await client.post(
        "/api/tasks",
        json={"description": f"{TEST_PREFIX}due date task", "due_date": "2026-09-01"},
        headers=auth_headers(member_user),
    )
    assert create_response.status_code == 200
    task_id = create_response.json()["id"]
    assert create_response.json()["due_date"] == "2026-09-01"

    update_response = await client.patch(
        f"/api/tasks/{task_id}", json={"due_date": "2026-09-05"}, headers=auth_headers(member_user)
    )
    assert update_response.status_code == 200
    assert update_response.json()["due_date"] == "2026-09-05"

    clear_response = await client.patch(
        f"/api/tasks/{task_id}", json={"clear_due_date": True}, headers=auth_headers(member_user)
    )
    assert clear_response.status_code == 200
    assert clear_response.json()["due_date"] is None


async def test_update_records_history(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "History Meeting", "Engineering")
    task = await _add_task(meeting, f"{TEST_PREFIX}history task")

    await client.patch(f"/api/tasks/{task.id}", json={"owner": "Avni"}, headers=auth_headers(member_user))
    await client.patch(f"/api/tasks/{task.id}", json={"status": "done"}, headers=auth_headers(member_user))

    response = await client.get(f"/api/tasks/{task.id}/history", headers=auth_headers(member_user))
    assert response.status_code == 200
    fields_changed = {entry["field"] for entry in response.json()}
    assert "owner" in fields_changed
    assert "status" in fields_changed
    owner_entry = next(e for e in response.json() if e["field"] == "owner")
    assert owner_entry["new_value"] == "Avni"


async def test_history_not_recorded_when_value_unchanged(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "No-op History Meeting", "Engineering")
    task = await _add_task(meeting, f"{TEST_PREFIX}noop task", owner="Avni")

    await client.patch(f"/api/tasks/{task.id}", json={"owner": "Avni"}, headers=auth_headers(member_user))

    response = await client.get(f"/api/tasks/{task.id}/history", headers=auth_headers(member_user))
    assert response.json() == []


async def test_comments_round_trip(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "Comment Meeting", "Engineering")
    task = await _add_task(meeting, f"{TEST_PREFIX}comment task")

    post_response = await client.post(
        f"/api/tasks/{task.id}/comments", json={"body": "Following up on this"}, headers=auth_headers(member_user)
    )
    assert post_response.status_code == 200
    assert post_response.json()["body"] == "Following up on this"

    list_response = await client.get(f"/api/tasks/{task.id}/comments", headers=auth_headers(member_user))
    assert len(list_response.json()) == 1
    assert list_response.json()[0]["author"] == (member_user.name or member_user.email)


async def test_empty_comment_rejected(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "Empty Comment Meeting", "Engineering")
    task = await _add_task(meeting, f"{TEST_PREFIX}empty comment task")

    response = await client.post(
        f"/api/tasks/{task.id}/comments", json={"body": "   "}, headers=auth_headers(member_user)
    )
    assert response.status_code == 400


async def test_task_links_create_inverse_and_delete(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "Link Meeting", "Engineering")
    task_a = await _add_task(meeting, f"{TEST_PREFIX}task A")
    task_b = await _add_task(meeting, f"{TEST_PREFIX}task B")

    create_response = await client.post(
        f"/api/tasks/{task_a.id}/links",
        json={"linked_task_id": str(task_b.id), "link_type": "blocks"},
        headers=auth_headers(member_user),
    )
    assert create_response.status_code == 200

    a_links = (await client.get(f"/api/tasks/{task_a.id}/links", headers=auth_headers(member_user))).json()
    assert a_links[0]["link_type"] == "blocks"
    assert a_links[0]["linked_task_id"] == str(task_b.id)

    b_links = (await client.get(f"/api/tasks/{task_b.id}/links", headers=auth_headers(member_user))).json()
    assert b_links[0]["link_type"] == "blocked_by"
    assert b_links[0]["linked_task_id"] == str(task_a.id)

    delete_response = await client.delete(
        f"/api/tasks/{task_a.id}/links/{a_links[0]['id']}", headers=auth_headers(member_user)
    )
    assert delete_response.status_code == 200
    assert (await client.get(f"/api/tasks/{task_b.id}/links", headers=auth_headers(member_user))).json() == []


async def test_cannot_link_task_to_itself(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "Self Link Meeting", "Engineering")
    task = await _add_task(meeting, f"{TEST_PREFIX}self link task")

    response = await client.post(
        f"/api/tasks/{task.id}/links",
        json={"linked_task_id": str(task.id), "link_type": "relates_to"},
        headers=auth_headers(member_user),
    )
    assert response.status_code == 400


async def _colleague(user, attendee_of=None) -> str:
    """Give the fixture user a unique name (both fixture users share one,
    which resolves to nobody) and optionally put them in a meeting."""
    name = f"{TEST_PREFIX}Colleague {uuid.uuid4().hex[:6]}"
    async with async_session() as db:
        (await db.get(User, user.id)).name = name
        if attendee_of is not None:
            db.add(MeetingAttendee(meeting_id=attendee_of.id, user_id=user.id, display_name=name, access="granted"))
        await db.commit()
    return name


async def test_assigning_a_colleague_in_the_meeting_notifies_them(client, member_user, other_member_user, make_meeting):
    meeting = await make_meeting(member_user, "Notify Meeting", "Engineering")
    name = await _colleague(other_member_user, attendee_of=meeting)
    task = await _add_task(meeting, f"{TEST_PREFIX}notify task")

    response = await client.patch(f"/api/tasks/{task.id}", json={"owner": name}, headers=auth_headers(member_user))
    assert response.status_code == 200

    notifications = (await client.get("/api/notifications", headers=auth_headers(other_member_user))).json()
    [note] = [n for n in notifications if n["type"] == "task_assigned" and task.description in n["message"]]
    assert note["link"] == f"/meetings/{meeting.id}#task-{task.id}"


async def test_assigning_someone_outside_the_meeting_sends_the_task_only(client, member_user, other_member_user, make_meeting):
    meeting = await make_meeting(member_user, "Private Planning", "Engineering")
    name = await _colleague(other_member_user)
    task = await _add_task(meeting, f"{TEST_PREFIX}outside task")

    await client.patch(f"/api/tasks/{task.id}", json={"owner": name}, headers=auth_headers(member_user))

    notifications = (await client.get("/api/notifications", headers=auth_headers(other_member_user))).json()
    [note] = [n for n in notifications if task.description in n["message"]]
    assert note["link"] == f"/tasks?task={task.id}" and "Private Planning" not in note["message"]
    listed = {t["id"]: t for t in (await client.get("/api/tasks", headers=auth_headers(other_member_user))).json()}
    assert listed[str(task.id)]["meeting_hidden"] is True


async def test_assigning_owner_with_no_matching_user_is_silent(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "No Match Meeting", "Engineering")
    task = await _add_task(meeting, f"{TEST_PREFIX}no match task")

    response = await client.patch(
        f"/api/tasks/{task.id}",
        json={"owner": f"{TEST_PREFIX}NobodyRegistered"},
        headers=auth_headers(member_user),
    )
    assert response.status_code == 200


async def test_mark_notification_read(client, member_user, other_member_user, make_meeting):
    meeting = await make_meeting(member_user, "Mark Read Meeting", "Engineering")
    name = await _colleague(other_member_user, attendee_of=meeting)
    task = await _add_task(meeting, f"{TEST_PREFIX}mark read task")
    await client.patch(f"/api/tasks/{task.id}", json={"owner": name}, headers=auth_headers(member_user))

    before = (await client.get("/api/notifications/unread-count", headers=auth_headers(other_member_user))).json()
    assert before["count"] >= 1

    notifications = (await client.get("/api/notifications", headers=auth_headers(other_member_user))).json()
    target = next(n for n in notifications if not n["read"])
    mark_response = await client.patch(f"/api/notifications/{target['id']}", headers=auth_headers(other_member_user))
    assert mark_response.status_code == 200
    assert mark_response.json()["read"] is True


async def test_task_list_says_whose_task_it_is(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "Ownership Meeting", "Engineering")
    mine = await _add_task(meeting, f"{TEST_PREFIX}mine", owner=member_user.email)
    waiting = await _add_task(meeting, f"{TEST_PREFIX}theirs", owner="Somebody Else")
    unassigned = await _add_task(meeting, f"{TEST_PREFIX}nobody")

    listed = {t["id"]: t for t in (await client.get("/api/tasks", headers=auth_headers(member_user))).json()}
    assert (listed[str(mine.id)]["mine"], listed[str(mine.id)]["delegated"]) == (True, False)
    # From a meeting they recorded, owned by someone else: they're waiting on it.
    assert (listed[str(waiting.id)]["mine"], listed[str(waiting.id)]["delegated"]) == (False, True)
    assert (listed[str(unassigned.id)]["mine"], listed[str(unassigned.id)]["delegated"]) == (False, False)
    assert listed[str(mine.id)]["created_at"]


async def test_bulk_delete_moves_only_readable_tasks(client, member_user, other_member_user, make_meeting):
    meeting = await make_meeting(member_user, "Bulk Delete Meeting", "Engineering")
    others = await make_meeting(other_member_user, "Someone Else's Meeting", "Engineering")
    first = await _add_task(meeting, f"{TEST_PREFIX}first")
    second = await _add_task(meeting, f"{TEST_PREFIX}second")
    foreign = await _add_task(others, f"{TEST_PREFIX}foreign")

    response = await client.post(
        "/api/tasks/delete", json={"ids": [str(first.id), str(second.id), str(foreign.id)]}, headers=auth_headers(member_user)
    )
    assert response.status_code == 200
    assert sorted(response.json()["deleted"]) == sorted([str(first.id), str(second.id)])
    assert list(response.json()["failed"]) == [str(foreign.id)]
    async with async_session() as db:
        assert (await db.get(MeetingTask, first.id)).deleted_at is not None
        assert (await db.get(MeetingTask, foreign.id)).deleted_at is None


async def test_reassigning_a_task_moves_it_off_the_previous_owner(client, member_user, other_member_user, make_meeting):
    meeting = await make_meeting(member_user, "Reassign Meeting", "Engineering")
    async with async_session() as db:
        task = MeetingTask(meeting_id=meeting.id, description=f"{TEST_PREFIX}reassigned", status="pending",
                           owner=member_user.name, owner_user_id=member_user.id)
        db.add(task)
        await db.commit()
        await db.refresh(task)

    # Handed to someone with no matching account: no longer anyone's task.
    response = await client.patch(f"/api/tasks/{task.id}", json={"owner": "Satyendra Nobody"}, headers=auth_headers(member_user))
    assert response.status_code == 200
    async with async_session() as db:
        assert (await db.get(MeetingTask, task.id)).owner_user_id is None
    listed = {t["id"]: t for t in (await client.get("/api/tasks", headers=auth_headers(member_user))).json()}
    assert listed[str(task.id)]["mine"] is False

    # Handed to a colleague by email: it becomes theirs.
    await client.patch(f"/api/tasks/{task.id}", json={"owner": other_member_user.email}, headers=auth_headers(member_user))
    async with async_session() as db:
        assert (await db.get(MeetingTask, task.id)).owner_user_id == other_member_user.id
