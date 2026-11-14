from app.database.db import async_session
from app.database.models import Decision, MeetingTask
from tests.conftest import TEST_PREFIX, auth_headers


async def _add_task(meeting, description="Do a thing", status="pending"):
    async with async_session() as db:
        task = MeetingTask(meeting_id=meeting.id, description=description, status=status)
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task


async def _add_decision(meeting, decision="Use X", conflict_note=None):
    async with async_session() as db:
        d = Decision(meeting_id=meeting.id, decision=decision, conflict_note=conflict_note)
        db.add(d)
        await db.commit()
        await db.refresh(d)
        return d


async def test_digest_department_isolation(client, member_user, other_member_user, make_meeting):
    eng_meeting = await make_meeting(member_user, "Eng Digest Meeting", "Engineering")
    await make_meeting(other_member_user, "Sales Digest Meeting", "Sales")

    response = await client.get("/api/digest", headers=auth_headers(member_user))
    assert response.status_code == 200
    body = response.json()

    titles = [m["title"] for m in body["meetings"]]
    assert f"{TEST_PREFIX}Eng Digest Meeting" in titles
    assert f"{TEST_PREFIX}Sales Digest Meeting" not in titles
    assert eng_meeting.id  # sanity: fixture actually created it


async def test_digest_counts_tasks_and_decisions(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "Digest Counts Meeting", "Engineering")
    await _add_task(meeting, f"{TEST_PREFIX}completed task", status="done")
    await _add_task(meeting, f"{TEST_PREFIX}pending task", status="pending")
    await _add_decision(meeting, f"{TEST_PREFIX}a decision")

    response = await client.get("/api/digest", headers=auth_headers(member_user))
    assert response.status_code == 200
    body = response.json()

    this_meeting = next(m for m in body["meetings"] if m["id"] == str(meeting.id))
    assert this_meeting["task_count"] == 2
    assert this_meeting["decision_count"] == 1
    assert body["tasks_completed"] >= 1
    assert body["decisions_made"] >= 1


async def test_digest_counts_contradictions(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "Digest Conflict Meeting", "Engineering")
    await _add_decision(meeting, f"{TEST_PREFIX}reversed decision", conflict_note="Contradicts an earlier one.")

    response = await client.get("/api/digest", headers=auth_headers(member_user))
    assert response.status_code == 200
    body = response.json()

    assert body["contradictions_found"] >= 1
    flagged = [d for d in body["decisions"] if d["meeting_id"] == str(meeting.id)]
    assert len(flagged) == 1
    assert flagged[0]["conflict_note"] == "Contradicts an earlier one."


async def test_digest_for_admins_covers_only_their_meetings(client, admin_user, member_user, make_meeting):
    await make_meeting(admin_user, "Admin's Own Digest Check", "Engineering")
    await make_meeting(member_user, "Eng Digest Admin Check", "Engineering")

    response = await client.get("/api/digest", headers=auth_headers(admin_user))
    assert response.status_code == 200
    titles = [m["title"] for m in response.json()["meetings"]]
    assert f"{TEST_PREFIX}Admin's Own Digest Check" in titles
    assert f"{TEST_PREFIX}Eng Digest Admin Check" not in titles
