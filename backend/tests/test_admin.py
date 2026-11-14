import uuid

from app.database.db import async_session
from app.database.models import Decision, Team, Trace, User
from tests.conftest import TEST_PREFIX, auth_headers


async def _add_trace(user, meeting_title, input_tokens=100, output_tokens=20, whisper=1):
    async with async_session() as db:
        trace = Trace(
            user_id=user.id,
            meeting_id=None,
            meeting_title=meeting_title,
            duration_minutes=5,
            transcription_requests=whisper,
            ai_input_tokens=input_tokens,
            ai_output_tokens=output_tokens,
            ai_cache_hits=0,
            tasks_found=1,
            decisions_found=0,
            status="success",
        )
        db.add(trace)
        await db.commit()
        await db.refresh(trace)
        return trace


async def _add_decision(meeting, decision="Use X", conflict_note=None):
    async with async_session() as db:
        d = Decision(meeting_id=meeting.id, decision=decision, conflict_note=conflict_note)
        db.add(d)
        await db.commit()
        await db.refresh(d)
        return d


async def test_usage_summary_forbidden_for_non_admin(client, member_user):
    response = await client.get("/api/admin/usage-summary", headers=auth_headers(member_user))
    assert response.status_code == 403


async def test_usage_summary_grouped_by_department(client, admin_user, member_user, other_member_user):
    eng_trace = await _add_trace(member_user, f"{TEST_PREFIX}Eng Cost Meeting", input_tokens=1000, output_tokens=200)
    sales_trace = await _add_trace(other_member_user, f"{TEST_PREFIX}Sales Cost Meeting", input_tokens=500, output_tokens=100)

    response = await client.get("/api/admin/usage-summary", headers=auth_headers(admin_user))
    assert response.status_code == 200
    body = response.json()

    by_department = {d["department"]: d for d in body["by_department"]}
    assert "Engineering" in by_department
    assert "Sales" in by_department
    assert by_department["Engineering"]["ai_input_tokens"] >= 1000
    assert by_department["Sales"]["ai_input_tokens"] >= 500

    async with async_session() as db:
        await db.execute(Trace.__table__.delete().where(Trace.id.in_([eng_trace.id, sales_trace.id])))
        await db.commit()


async def test_decision_churn_forbidden_for_non_admin(client, member_user):
    response = await client.get("/api/admin/decision-churn", headers=auth_headers(member_user))
    assert response.status_code == 403


async def test_decision_churn_grouped_by_department_and_month(
    client, admin_user, member_user, other_member_user, make_meeting
):
    eng_meeting = await make_meeting(member_user, "Eng Churn Meeting", "Engineering")
    sales_meeting = await make_meeting(other_member_user, "Sales Churn Meeting", "Sales")

    await _add_decision(eng_meeting, f"{TEST_PREFIX}eng decision reversed", conflict_note="Contradicts an earlier decision.")
    await _add_decision(eng_meeting, f"{TEST_PREFIX}eng decision stable")
    await _add_decision(sales_meeting, f"{TEST_PREFIX}sales decision stable")

    response = await client.get("/api/admin/decision-churn", headers=auth_headers(admin_user))
    assert response.status_code == 200
    body = response.json()

    assert body["total_decisions"] >= 3
    assert body["conflicted_decisions"] >= 1
    assert 0 <= body["churn_rate"] <= 1

    by_department = {d["department"]: d for d in body["by_department"]}
    assert by_department["Engineering"]["total_decisions"] >= 2
    assert by_department["Engineering"]["conflicted_decisions"] >= 1
    assert by_department["Engineering"]["churn_rate"] > 0
    assert by_department["Sales"]["total_decisions"] >= 1
    assert by_department["Sales"]["conflicted_decisions"] == 0
    assert by_department["Sales"]["churn_rate"] == 0

    assert len(body["by_month"]) >= 1
    assert all("month" in m and "churn_rate" in m for m in body["by_month"])


async def test_admin_can_create_team_and_account_then_suspend_it(client, admin_user):
    team_response = await client.post(
        "/api/admin/teams",
        json={"name": f"{TEST_PREFIX}Product Ops", "description": "Product operations"},
        headers=auth_headers(admin_user),
    )
    assert team_response.status_code == 201
    team_id = team_response.json()["id"]

    email = f"{TEST_PREFIX}managed@example.com"
    account_response = await client.post(
        "/api/admin/accounts",
        json={
            "email": email, "name": "Managed User", "password": "Temporary@123",
            "role": "team_admin", "team_id": team_id, "department": "Product",
        },
        headers=auth_headers(admin_user),
    )
    assert account_response.status_code == 201
    account_id = account_response.json()["id"]

    updated = await client.patch(
        f"/api/admin/accounts/{account_id}",
        json={"status": "suspended"}, headers=auth_headers(admin_user),
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "suspended"

    audit = await client.get("/api/admin/audit-events", headers=auth_headers(admin_user))
    assert audit.status_code == 200
    assert any(event["target_id"] == account_id for event in audit.json())

    async with async_session() as db:
        user = await db.get(User, uuid.UUID(account_id))
        if user:
            await db.delete(user)
        team = await db.get(Team, uuid.UUID(team_id))
        if team:
            await db.delete(team)
        await db.commit()


async def test_non_admin_cannot_manage_accounts(client, member_user):
    response = await client.get("/api/admin/accounts", headers=auth_headers(member_user))
    assert response.status_code == 403


async def test_configured_super_admin_cannot_be_suspended(client, admin_user):
    response = await client.patch(
        f"/api/admin/accounts/{admin_user.id}",
        json={"status": "suspended"}, headers=auth_headers(admin_user),
    )
    assert response.status_code == 422
