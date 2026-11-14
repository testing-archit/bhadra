from app.dependencies import department_scope, is_admin
from app.database.models import User
from tests.conftest import TEST_PREFIX, auth_headers


def test_is_admin_true_for_configured_email(admin_user):
    assert is_admin(admin_user) is True


def test_is_admin_false_for_regular_user(member_user):
    assert is_admin(member_user) is False


def test_department_scope_admin_sees_everything(admin_user):
    assert department_scope(admin_user) is None


def test_department_scope_member_restricted_to_own_department(member_user):
    assert department_scope(member_user) == "Engineering"


async def test_get_current_user_rejects_missing_bearer_prefix(client):
    response = await client.get("/api/auth/me", headers={"Authorization": "not-a-bearer-token"})
    assert response.status_code == 401


async def test_get_current_user_rejects_garbage_token(client):
    response = await client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401


async def test_get_current_user_rejects_missing_header(client):
    response = await client.get("/api/auth/me")
    assert response.status_code in (401, 422)


async def test_me_endpoint_returns_correct_profile(client, member_user):
    response = await client.get("/api/auth/me", headers=auth_headers(member_user))
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == member_user.email
    assert body["department"] == "Engineering"
    assert body["is_admin"] is False


async def test_update_department(client, member_user):
    response = await client.patch(
        "/api/auth/me", json={"department": "Marketing"}, headers=auth_headers(member_user)
    )
    assert response.status_code == 200
    assert response.json()["department"] == "Marketing"

    # Revert so other tests relying on "Engineering" aren't affected.
    await client.patch(
        "/api/auth/me", json={"department": "Engineering"}, headers=auth_headers(member_user)
    )


async def test_google_sheets_settings_are_user_owned(client, member_user, other_member_user):
    response = await client.put(
        "/api/auth/integrations/google-sheets",
        json={
            "spreadsheet_id": "https://docs.google.com/spreadsheets/d/test_sheet_123/edit",
            "tasks_tab": "Action Items",
            "notes_tab": "Meeting Archive",
        },
        headers=auth_headers(member_user),
    )
    assert response.status_code == 200
    assert response.json() == {
        "spreadsheet_id": "test_sheet_123",
        "tasks_tab": "Action Items",
        "notes_tab": "Meeting Archive",
    }

    own = await client.get(
        "/api/auth/integrations/google-sheets", headers=auth_headers(member_user)
    )
    assert own.status_code == 200
    assert own.json()["spreadsheet_id"] == "test_sheet_123"

    other = await client.get(
        "/api/auth/integrations/google-sheets", headers=auth_headers(other_member_user)
    )
    assert other.status_code == 200
    assert other.json()["spreadsheet_id"] is None


async def test_refresh_token_issues_new_valid_token(client, member_user):
    response = await client.post("/api/auth/refresh", headers=auth_headers(member_user))
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == member_user.email

    # The freshly-issued token must itself work for an authenticated call.
    me_response = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me_response.status_code == 200
    assert me_response.json()["email"] == member_user.email


async def test_refresh_token_rejects_missing_auth(client):
    response = await client.post("/api/auth/refresh")
    assert response.status_code in (401, 422)


# --- Attendee-based meeting visibility ---------------------------------------
# A meeting is readable by the person who recorded it and by the colleagues
# listed on it — not by their whole department.

from app.database.db import async_session  # noqa: E402
from app.database.models import MeetingAttendee, MeetingTask  # noqa: E402


async def _add_attendee(meeting, user=None, name="Guest", email=None):
    async with async_session() as db:
        db.add(
            MeetingAttendee(
                meeting_id=meeting.id,
                user_id=user.id if user else None,
                display_name=(user.name if user else name) or name,
                email=(user.email if user else email),
                kind="internal" if user else "external",
                source="manual",
            )
        )
        await db.commit()


async def _add_task(meeting, description, owner=None, owner_user_id=None):
    async with async_session() as db:
        task = MeetingTask(
            meeting_id=meeting.id, description=description, owner=owner, owner_user_id=owner_user_id, status="pending"
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task


async def test_meeting_is_hidden_from_someone_who_did_not_attend(
    client, member_user, other_member_user, make_meeting
):
    meeting = await make_meeting(member_user, "Attendee Hidden Meeting", "Engineering")

    detail = await client.get(
        f"/api/meetings/{meeting.id}", headers=auth_headers(other_member_user)
    )
    assert detail.status_code == 404

    listing = await client.get("/api/meetings", headers=auth_headers(other_member_user))
    assert listing.status_code == 200
    assert str(meeting.id) not in {item["id"] for item in listing.json()}


async def test_same_department_alone_no_longer_grants_access(
    client, member_user, other_member_user, make_meeting
):
    """The old rule was department-wide. Put both users in one department and
    confirm that on its own it grants nothing."""
    async with async_session() as db:
        subject = await db.get(User, other_member_user.id)
        original_department = subject.department
        subject.department = member_user.department
        await db.commit()
    try:
        meeting = await make_meeting(member_user, "Same Dept No Access", member_user.department)
        response = await client.get(
            f"/api/meetings/{meeting.id}", headers=auth_headers(other_member_user)
        )
        assert response.status_code == 404
    finally:
        async with async_session() as db:
            subject = await db.get(User, other_member_user.id)
            subject.department = original_department
            await db.commit()


async def test_listed_attendee_can_read_the_meeting(
    client, member_user, other_member_user, make_meeting
):
    meeting = await make_meeting(member_user, "Attendee Allowed Meeting", "Engineering")
    await _add_attendee(meeting, user=other_member_user)

    detail = await client.get(
        f"/api/meetings/{meeting.id}", headers=auth_headers(other_member_user)
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == str(meeting.id)

    listing = await client.get("/api/meetings", headers=auth_headers(other_member_user))
    assert str(meeting.id) in {item["id"] for item in listing.json()}


async def test_external_attendee_row_grants_nothing(
    client, member_user, other_member_user, make_meeting
):
    """An external guest is recorded on the meeting but has no account. The row
    must never be mistaken for an access grant."""
    meeting = await make_meeting(member_user, "External Guest Meeting", "Engineering")
    await _add_attendee(meeting, name="Client Contact", email=other_member_user.email)

    response = await client.get(
        f"/api/meetings/{meeting.id}", headers=auth_headers(other_member_user)
    )
    assert response.status_code == 404


async def test_admin_reads_a_meeting_they_did_not_attend(
    client, admin_user, other_member_user, make_meeting
):
    meeting = await make_meeting(other_member_user, "Admin Override Meeting", "Sales")
    response = await client.get(f"/api/meetings/{meeting.id}", headers=auth_headers(admin_user))
    assert response.status_code == 200


async def test_setting_attendees_matches_names_to_accounts_and_keeps_the_owner(
    client, member_user, other_member_user, make_meeting
):
    meeting = await make_meeting(member_user, "Set Attendees Meeting", "Engineering")

    response = await client.put(
        f"/api/meetings/{meeting.id}/attendees",
        json={
            "attendees": [
                {"user_id": str(other_member_user.id)},
                {"name": "Outside Counsel", "email": "counsel@lawfirm.example"},
            ]
        },
        headers=auth_headers(member_user),
    )
    assert response.status_code == 200
    body = response.json()
    by_kind = {item["kind"] for item in body}
    assert by_kind == {"internal", "external"}
    # The recorder is re-added automatically and cannot be dropped.
    assert str(member_user.id) in {item["user_id"] for item in body if item["user_id"]}
    assert str(other_member_user.id) in {item["user_id"] for item in body if item["user_id"]}

    assert (
        await client.get(f"/api/meetings/{meeting.id}", headers=auth_headers(other_member_user))
    ).status_code == 200


async def test_email_resolves_an_attendee_to_their_account(
    client, member_user, other_member_user, make_meeting
):
    meeting = await make_meeting(member_user, "Email Match Meeting", "Engineering")
    response = await client.put(
        f"/api/meetings/{meeting.id}/attendees",
        json={"attendees": [{"name": "Whoever", "email": other_member_user.email}]},
        headers=auth_headers(member_user),
    )
    assert response.status_code == 200
    assert str(other_member_user.id) in {item["user_id"] for item in response.json() if item["user_id"]}
    assert (
        await client.get(f"/api/meetings/{meeting.id}", headers=auth_headers(other_member_user))
    ).status_code == 200


async def test_a_non_attendee_cannot_add_themselves(
    client, member_user, other_member_user, make_meeting
):
    meeting = await make_meeting(member_user, "No Self Add Meeting", "Engineering")
    response = await client.put(
        f"/api/meetings/{meeting.id}/attendees",
        json={"attendees": [{"user_id": str(other_member_user.id)}]},
        headers=auth_headers(other_member_user),
    )
    assert response.status_code == 404


async def test_a_task_for_someone_not_in_the_meeting_waits_until_sent(
    client, member_user, other_member_user, make_meeting
):
    """Two people decide something about a third and give them a task: the
    third person sees nothing — not the task, not a name match — until the
    recorder sends it, and then only the task, never the meeting."""
    meeting = await make_meeting(other_member_user, "Org Changes", "Sales")
    held = await _add_task(meeting, f"{TEST_PREFIX}take over the payments work", owner=member_user.name, owner_user_id=member_user.id)
    await _add_task(meeting, f"{TEST_PREFIX}named only", owner=member_user.email)

    def mine(response):
        return {item["description"]: item for item in response.json()}

    listed = mine(await client.get("/api/tasks", headers=auth_headers(member_user)))
    assert f"{TEST_PREFIX}take over the payments work" not in listed
    assert f"{TEST_PREFIX}named only" not in listed

    recorder_view = await client.get(f"/api/meetings/{meeting.id}", headers=auth_headers(other_member_user))
    assert {t["id"]: t["owner_access"] for t in recorder_view.json()["tasks"]}[str(held.id)] == "held"

    # Only the recorder or organizer decides.
    refused = await client.post(f"/api/tasks/{held.id}/owner-access", json={"action": "send"}, headers=auth_headers(member_user))
    assert refused.status_code == 404
    sent = await client.post(f"/api/tasks/{held.id}/owner-access", json={"action": "send"}, headers=auth_headers(other_member_user))
    assert sent.status_code == 200 and sent.json()["owner_access"] == "shared"

    listed = mine(await client.get("/api/tasks", headers=auth_headers(member_user)))
    task = listed[f"{TEST_PREFIX}take over the payments work"]
    assert task["meeting_hidden"] is True and task["meeting_title"] == "A meeting you weren't in"
    assert f"{TEST_PREFIX}named only" not in listed
    detail = await client.get(f"/api/meetings/{meeting.id}", headers=auth_headers(member_user))
    assert detail.status_code == 404


async def test_confidential_meetings_are_closed_to_admins_who_were_not_in_them(
    client, admin_user, member_user, make_meeting
):
    meeting = await make_meeting(member_user, "Compensation Review", "Sales")
    assert (await client.get(f"/api/meetings/{meeting.id}", headers=auth_headers(admin_user))).status_code == 200

    marked = await client.post(f"/api/meetings/{meeting.id}/confidential", json={"confidential": True}, headers=auth_headers(member_user))
    assert marked.status_code == 200 and marked.json()["confidential"] is True

    assert (await client.get(f"/api/meetings/{meeting.id}", headers=auth_headers(admin_user))).status_code == 404
    listing = await client.get("/api/admin/meetings", params={"q": "Compensation"}, headers=auth_headers(admin_user))
    assert str(meeting.id) not in {row["id"] for row in listing.json()["meetings"]}
    listing = await client.get("/api/admin/meetings", headers=auth_headers(admin_user))
    row = next(row for row in listing.json()["meetings"] if row["id"] == str(meeting.id))
    assert row["title"] == "Confidential meeting" and row["can_open"] is False
    link = await client.post(f"/api/meetings/{meeting.id}/share-link", headers=auth_headers(member_user))
    assert link.status_code == 409

    # An admin can't unmark (or reach) it; the recorder can.
    assert (await client.post(f"/api/meetings/{meeting.id}/confidential", json={"confidential": False}, headers=auth_headers(admin_user))).status_code == 404
    assert (await client.post(f"/api/meetings/{meeting.id}/confidential", json={"confidential": False}, headers=auth_headers(member_user))).status_code == 200
    assert (await client.get(f"/api/meetings/{meeting.id}", headers=auth_headers(admin_user))).status_code == 200


async def test_decisions_from_unattended_meetings_are_hidden(
    client, member_user, other_member_user, make_meeting
):
    from app.database.models import Decision

    meeting = await make_meeting(other_member_user, "Hidden Decision Meeting", "Sales")
    async with async_session() as db:
        decision = Decision(meeting_id=meeting.id, decision=f"{TEST_PREFIX}secret call")
        db.add(decision)
        await db.commit()
        await db.refresh(decision)

    listing = await client.get("/api/decisions", headers=auth_headers(member_user))
    assert str(decision.id) not in {item["id"] for item in listing.json()}
    detail = await client.get(f"/api/decisions/{decision.id}", headers=auth_headers(member_user))
    assert detail.status_code == 404


async def test_directory_is_available_to_every_signed_in_user(client, member_user):
    response = await client.get("/api/auth/directory", headers=auth_headers(member_user))
    assert response.status_code == 200
    emails = {item["email"] for item in response.json()}
    assert member_user.email in emails


async def test_attendee_can_play_the_meetings_recording(
    client, member_user, other_member_user, make_meeting, tmp_path, monkeypatch
):
    """Regression: recording audio was owner-only, so an attendee could open
    the meeting page but its audio player 404'd. They can already read the
    transcript — the audio is not the secret."""
    from app.config import settings
    from app.database.models import RecordingSession

    monkeypatch.setattr(settings, "recordings_dir", str(tmp_path))
    meeting = await make_meeting(member_user, "Shared Recording Meeting", "Engineering")
    await _add_attendee(meeting, user=other_member_user)

    async with async_session() as db:
        recording = RecordingSession(
            user_id=member_user.id,
            meeting_id=meeting.id,
            title=meeting.title,
            status="processed",
            mime_type="audio/webm",
        )
        db.add(recording)
        await db.commit()
        await db.refresh(recording)

    directory = tmp_path / str(recording.id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "recording.webm").write_bytes(b"fake-audio")

    try:
        allowed = await client.get(
            f"/api/recordings/{recording.id}/audio", headers=auth_headers(other_member_user)
        )
        assert allowed.status_code == 200
    finally:
        async with async_session() as db:
            row = await db.get(RecordingSession, recording.id)
            if row:
                await db.delete(row)
                await db.commit()


async def test_non_attendee_cannot_play_a_recording(
    client, member_user, other_member_user, make_meeting, tmp_path, monkeypatch
):
    from app.config import settings
    from app.database.models import RecordingSession

    monkeypatch.setattr(settings, "recordings_dir", str(tmp_path))
    meeting = await make_meeting(member_user, "Private Recording Meeting", "Engineering")

    async with async_session() as db:
        recording = RecordingSession(
            user_id=member_user.id,
            meeting_id=meeting.id,
            title=meeting.title,
            status="processed",
            mime_type="audio/webm",
        )
        db.add(recording)
        await db.commit()
        await db.refresh(recording)

    directory = tmp_path / str(recording.id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "recording.webm").write_bytes(b"fake-audio")

    try:
        denied = await client.get(
            f"/api/recordings/{recording.id}/audio", headers=auth_headers(other_member_user)
        )
        assert denied.status_code == 404
    finally:
        async with async_session() as db:
            row = await db.get(RecordingSession, recording.id)
            if row:
                await db.delete(row)
                await db.commit()


async def test_being_added_to_a_meeting_notifies_you(
    client, member_user, other_member_user, make_meeting
):
    meeting = await make_meeting(member_user, "Notify On Add Meeting", "Engineering")
    response = await client.put(
        f"/api/meetings/{meeting.id}/attendees",
        json={"attendees": [{"user_id": str(other_member_user.id)}]},
        headers=auth_headers(member_user),
    )
    assert response.status_code == 200

    notifications = await client.get("/api/notifications", headers=auth_headers(other_member_user))
    assert notifications.status_code == 200
    assert any(
        item["type"] == "meeting_access" and str(meeting.id) in (item["link"] or "")
        for item in notifications.json()
    )


async def test_meetings_can_be_filtered_by_attendee(
    client, member_user, other_member_user, make_meeting
):
    with_them = await make_meeting(member_user, "Filter With Them", "Engineering")
    without_them = await make_meeting(member_user, "Filter Without Them", "Engineering")
    await _add_attendee(with_them, user=other_member_user)

    response = await client.get(
        f"/api/meetings?attendee_id={other_member_user.id}", headers=auth_headers(member_user)
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert str(with_them.id) in ids
    assert str(without_them.id) not in ids


async def test_attendee_filter_cannot_widen_access(
    client, member_user, other_member_user, make_meeting
):
    """The filter narrows what you can already see. Asking for someone else's
    meetings by their id must not hand them over."""
    theirs = await make_meeting(other_member_user, "Their Private Meeting", "Sales")
    await _add_attendee(theirs, user=other_member_user)

    response = await client.get(
        f"/api/meetings?attendee_id={other_member_user.id}", headers=auth_headers(member_user)
    )
    assert response.status_code == 200
    assert str(theirs.id) not in {item["id"] for item in response.json()}


async def test_saving_the_attendee_list_again_does_not_renotify(
    client, member_user, other_member_user, make_meeting
):
    """Regression: a replace deleted every row before reading who already had
    access, so each save told every attendee "you were added" again."""
    meeting = await make_meeting(member_user, "Resave Attendees Meeting", "Engineering")
    body = {"attendees": [{"user_id": str(other_member_user.id)}]}
    first = await client.put(f"/api/meetings/{meeting.id}/attendees", json=body, headers=auth_headers(member_user))
    assert first.status_code == 200
    second = await client.put(f"/api/meetings/{meeting.id}/attendees", json=body, headers=auth_headers(member_user))
    assert second.status_code == 200

    notifications = (await client.get("/api/notifications", headers=auth_headers(other_member_user))).json()
    added = [n for n in notifications if n["type"] == "meeting_access" and str(meeting.id) in (n["link"] or "")]
    assert len(added) == 1


async def test_an_attendee_cannot_grant_access_by_linking_a_recording(
    client, member_user, other_member_user, admin_user, make_meeting
):
    """Regression: linking a recording merges its attendees into the meeting
    (granted), so any reader could share someone else's meeting this way."""
    from app.database.models import RecordingSession

    meeting = await make_meeting(member_user, "Link Recording Access Meeting", "Engineering")
    await _add_attendee(meeting, user=other_member_user)
    async with async_session() as db:
        recording = RecordingSession(
            user_id=other_member_user.id,
            title="Smuggled",
            status="recorded",
            attendees=[{"user_id": str(admin_user.id), "name": "Someone", "email": None, "kind": "internal"}],
        )
        db.add(recording)
        await db.commit()
        await db.refresh(recording)
    try:
        response = await client.post(
            f"/api/recordings/{recording.id}/link",
            json={"meeting_id": str(meeting.id)},
            headers=auth_headers(other_member_user),
        )
        assert response.status_code == 403
        async with async_session() as db:
            from sqlalchemy import select

            granted = (await db.execute(
                select(MeetingAttendee).where(MeetingAttendee.meeting_id == meeting.id, MeetingAttendee.user_id == admin_user.id)
            )).scalar_one_or_none()
        assert granted is None
    finally:
        async with async_session() as db:
            row = await db.get(RecordingSession, recording.id)
            if row:
                await db.delete(row)
                await db.commit()


async def test_an_attendee_cannot_restore_a_meeting_its_recorder_deleted(
    client, member_user, other_member_user, make_meeting
):
    from unittest.mock import patch

    meeting = await make_meeting(member_user, "Restore Permission Meeting", "Engineering")
    await _add_attendee(meeting, user=other_member_user)
    with patch("app.routes.meetings.qdrant_service.delete_meeting"):
        deleted = await client.delete(f"/api/meetings/{meeting.id}", headers=auth_headers(member_user))
    assert deleted.status_code == 200

    with patch("app.routes.recycle_bin.rebuild_meeting_index"):
        denied = await client.post(
            f"/api/recycle-bin/meeting/{meeting.id}/restore", headers=auth_headers(other_member_user)
        )
    assert denied.status_code == 403
