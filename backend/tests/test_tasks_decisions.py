from app.database.db import async_session
from app.database.models import Decision, MeetingTask
from tests.conftest import TEST_PREFIX, auth_headers


async def _add_task(meeting, description="Do a thing"):
    async with async_session() as db:
        task = MeetingTask(meeting_id=meeting.id, description=description, status="pending")
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task


async def _add_decision(meeting, decision="Use X"):
    async with async_session() as db:
        d = Decision(meeting_id=meeting.id, decision=decision)
        db.add(d)
        await db.commit()
        await db.refresh(d)
        return d


async def test_list_tasks_department_isolation(client, member_user, other_member_user, make_meeting):
    eng_meeting = await make_meeting(member_user, "Eng Task Meeting", "Engineering")
    sales_meeting = await make_meeting(other_member_user, "Sales Task Meeting", "Sales")
    await _add_task(eng_meeting, f"{TEST_PREFIX}eng task")
    await _add_task(sales_meeting, f"{TEST_PREFIX}sales task")

    response = await client.get("/api/tasks", headers=auth_headers(member_user))
    descriptions = [t["description"] for t in response.json()]
    assert f"{TEST_PREFIX}eng task" in descriptions
    assert f"{TEST_PREFIX}sales task" not in descriptions


async def test_update_task_status_cross_department_denied(client, member_user, other_member_user, make_meeting):
    sales_meeting = await make_meeting(other_member_user, "Sales Task Meeting 2", "Sales")
    task = await _add_task(sales_meeting, f"{TEST_PREFIX}sales task 2")

    response = await client.patch(
        f"/api/tasks/{task.id}", json={"status": "done"}, headers=auth_headers(member_user)
    )
    assert response.status_code == 404


async def test_update_task_status_same_department_allowed(client, member_user, make_meeting):
    eng_meeting = await make_meeting(member_user, "Eng Task Meeting 2", "Engineering")
    task = await _add_task(eng_meeting, f"{TEST_PREFIX}eng task 2")

    response = await client.patch(
        f"/api/tasks/{task.id}", json={"status": "done"}, headers=auth_headers(member_user)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "done"


async def test_update_task_full_fields(client, member_user, make_meeting):
    eng_meeting = await make_meeting(member_user, "Eng Task Meeting 3", "Engineering")
    task = await _add_task(eng_meeting, f"{TEST_PREFIX}eng task 3")

    response = await client.patch(
        f"/api/tasks/{task.id}",
        json={
            "description": f"{TEST_PREFIX}rewritten description",
            "owner": "Someone Else",
            "deadline": "Next Monday",
            "priority": "High",
            "status": "in_progress",
        },
        headers=auth_headers(member_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["description"] == f"{TEST_PREFIX}rewritten description"
    assert body["owner"] == "Someone Else"
    assert body["deadline"] == "Next Monday"
    assert body["priority"] == "High"
    assert body["status"] == "in_progress"


async def test_create_task_manual(client, member_user):
    response = await client.post(
        "/api/tasks",
        json={"description": f"{TEST_PREFIX}manual task", "owner": "Someone", "priority": "High"},
        headers=auth_headers(member_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["description"] == f"{TEST_PREFIX}manual task"
    assert body["owner"] == "Someone"
    assert body["priority"] == "High"
    assert body["status"] == "pending"
    assert body["meeting_title"] == "Manually Added Tasks"

    listed = await client.get("/api/tasks", headers=auth_headers(member_user))
    descriptions = [t["description"] for t in listed.json()]
    assert f"{TEST_PREFIX}manual task" in descriptions


async def test_create_task_reuses_manual_meeting(client, member_user):
    first = await client.post(
        "/api/tasks", json={"description": f"{TEST_PREFIX}task one"}, headers=auth_headers(member_user)
    )
    second = await client.post(
        "/api/tasks", json={"description": f"{TEST_PREFIX}task two"}, headers=auth_headers(member_user)
    )
    assert first.json()["meeting_id"] == second.json()["meeting_id"]


async def test_create_task_requires_description(client, member_user):
    response = await client.post("/api/tasks", json={"description": "   "}, headers=auth_headers(member_user))
    assert response.status_code == 400


async def test_delete_task(client, member_user, make_meeting):
    eng_meeting = await make_meeting(member_user, "Eng Task Meeting Delete", "Engineering")
    task = await _add_task(eng_meeting, f"{TEST_PREFIX}task to delete")

    response = await client.delete(f"/api/tasks/{task.id}", headers=auth_headers(member_user))
    assert response.status_code == 200
    assert response.json()["ok"] is True

    listed = await client.get("/api/tasks", headers=auth_headers(member_user))
    descriptions = [t["description"] for t in listed.json()]
    assert f"{TEST_PREFIX}task to delete" not in descriptions


async def test_delete_task_cross_department_denied(client, member_user, other_member_user, make_meeting):
    sales_meeting = await make_meeting(other_member_user, "Sales Task Meeting Delete", "Sales")
    task = await _add_task(sales_meeting, f"{TEST_PREFIX}sales task to delete")

    response = await client.delete(f"/api/tasks/{task.id}", headers=auth_headers(member_user))
    assert response.status_code == 404


async def test_list_decisions_department_isolation(client, member_user, other_member_user, make_meeting):
    eng_meeting = await make_meeting(member_user, "Eng Decision Meeting", "Engineering")
    sales_meeting = await make_meeting(other_member_user, "Sales Decision Meeting", "Sales")
    await _add_decision(eng_meeting, f"{TEST_PREFIX}eng decision")
    await _add_decision(sales_meeting, f"{TEST_PREFIX}sales decision")

    response = await client.get("/api/decisions", headers=auth_headers(member_user))
    decisions = [d["decision"] for d in response.json()]
    assert f"{TEST_PREFIX}eng decision" in decisions
    assert f"{TEST_PREFIX}sales decision" not in decisions


async def test_get_decision_cross_department_returns_404(client, member_user, other_member_user, make_meeting):
    sales_meeting = await make_meeting(other_member_user, "Sales Decision Meeting 2", "Sales")
    d = await _add_decision(sales_meeting, f"{TEST_PREFIX}sales decision 2")

    response = await client.get(f"/api/decisions/{d.id}", headers=auth_headers(member_user))
    assert response.status_code == 404


async def test_an_edit_is_kept_when_search_indexing_fails(client, member_user, make_meeting):
    """Search is derived data: Pinecone/Qdrant being down must not fail or
    roll back the edit — the indexing stage is marked failed to retry."""
    from unittest.mock import patch

    from sqlalchemy import select

    from app.database.models import ProcessingStage
    from app.services import qdrant_service

    meeting = await make_meeting(member_user, "Index Down Meeting", "Engineering")
    task = await _add_task(meeting, f"{TEST_PREFIX}edit me")
    with patch.object(qdrant_service, "replace_meeting", side_effect=ConnectionError("vector store down")):
        response = await client.patch(f"/api/tasks/{task.id}", json={"status": "done"}, headers=auth_headers(member_user))
    assert response.status_code == 200
    async with async_session() as db:
        assert (await db.get(MeetingTask, task.id)).status == "done"
        stage = (await db.execute(select(ProcessingStage).where(
            ProcessingStage.meeting_id == meeting.id, ProcessingStage.stage == "indexing"))).scalar_one()
        assert stage.status == "failed" and "vector store down" in (stage.last_error or "")
