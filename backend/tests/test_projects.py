import uuid
from unittest.mock import patch

from app.database.db import async_session
from app.database.models import MeetingTask, Project
from tests.conftest import auth_headers


async def test_many_meetings_can_be_assigned_to_one_project(client, member_user, make_meeting):
    headers = auth_headers(member_user)
    created = await client.post(
        "/api/projects", headers=headers, json={"name": f"pytest_project_{uuid.uuid4().hex[:8]}"}
    )
    assert created.status_code == 200
    project = created.json()

    first = await make_meeting(member_user, "Project meeting one", "Engineering")
    second = await make_meeting(member_user, "Project meeting two", "Engineering")
    for meeting in (first, second):
        response = await client.patch(
            f"/api/meetings/{meeting.id}/projects",
            headers=headers,
            json={"project_ids": [project["id"]]},
        )
        assert response.status_code == 200

    detail = await client.get(f"/api/projects/{project['id']}", headers=headers)
    assert detail.status_code == 200
    assert {item["id"] for item in detail.json()["meetings"]} == {str(first.id), str(second.id)}

    filtered = await client.get(
        "/api/meetings", params={"project_id": project["id"]}, headers=headers
    )
    assert filtered.status_code == 200
    assert {item["id"] for item in filtered.json()} == {str(first.id), str(second.id)}

    async with async_session() as db:
        existing = await db.get(Project, uuid.UUID(project["id"]))
        if existing:
            await db.delete(existing)
            await db.commit()


async def test_delete_project_preserves_records_and_recoverable_assignment(
    client, member_user, make_meeting
):
    headers = auth_headers(member_user)
    created = await client.post(
        "/api/projects", headers=headers, json={"name": f"pytest_delete_{uuid.uuid4().hex[:8]}"}
    )
    project_id = uuid.UUID(created.json()["id"])
    meeting = await make_meeting(member_user, "Project preservation", "Engineering")
    async with async_session() as db:
        task = MeetingTask(
            meeting_id=meeting.id,
            project_id=project_id,
            description="Preserve this task",
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        task_id = task.id

    with patch("app.routes.projects.rebuild_meeting_index") as rebuild:
        response = await client.delete(f"/api/projects/{project_id}", headers=headers)

    assert response.status_code == 200
    rebuild.assert_called_once_with(rebuild.call_args.args[0], meeting.id)
    async with async_session() as db:
        deleted = await db.get(Project, project_id)
        assert deleted is not None
        assert deleted.deleted_at is not None
        preserved = await db.get(MeetingTask, task_id)
        assert preserved is not None
        assert preserved.project_id == project_id

    with patch("app.routes.recycle_bin.rebuild_meeting_index") as rebuild_restore:
        restored = await client.post(
            f"/api/recycle-bin/project/{project_id}/restore", headers=headers
        )
    assert restored.status_code == 200
    rebuild_restore.assert_called_once()
    detail = await client.get(f"/api/projects/{project_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["tasks"][0]["id"] == str(task_id)

    await client.delete(f"/api/projects/{project_id}", headers=headers)
    permanent = await client.delete(f"/api/recycle-bin/project/{project_id}", headers=headers)
    assert permanent.status_code == 200


async def test_rename_project_reindexes_its_meetings_and_rejects_duplicates(client, member_user, make_meeting):
    headers = auth_headers(member_user)
    suffix = uuid.uuid4().hex[:8]
    project = (await client.post("/api/projects", headers=headers, json={"name": f"pytest_old_{suffix}"})).json()
    other = (await client.post("/api/projects", headers=headers, json={"name": f"pytest_other_{suffix}"})).json()
    meeting = await make_meeting(member_user, "Renamed project meeting", "Engineering")
    await client.patch(f"/api/meetings/{meeting.id}/projects", headers=headers, json={"project_ids": [project["id"]]})

    try:
        with patch("app.routes.projects.rebuild_meeting_index") as rebuild:
            renamed = await client.patch(
                f"/api/projects/{project['id']}", headers=headers, json={"name": f"  pytest_new_{suffix} "}
            )
        assert renamed.status_code == 200
        assert renamed.json()["name"] == f"pytest_new_{suffix}"
        rebuild.assert_called_once_with(rebuild.call_args.args[0], meeting.id)

        detail = await client.get(f"/api/meetings/{meeting.id}", headers=headers)
        assert [p["name"] for p in detail.json()["projects"]] == [f"pytest_new_{suffix}"]

        clash = await client.patch(
            f"/api/projects/{project['id']}", headers=headers, json={"name": f"PYTEST_OTHER_{suffix}"}
        )
        assert clash.status_code == 409
        blank = await client.patch(f"/api/projects/{project['id']}", headers=headers, json={"name": "  "})
        assert blank.status_code == 422
    finally:
        async with async_session() as db:
            for project_id in (project["id"], other["id"]):
                existing = await db.get(Project, uuid.UUID(project_id))
                if existing:
                    await db.delete(existing)
            await db.commit()
