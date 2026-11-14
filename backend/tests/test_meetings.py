import subprocess
import uuid as uuid_mod
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.routes.meetings import _assemble_meeting_audio, _concat_webm_chunks

from app.database.db import async_session
from app.database.models import Decision, Meeting, MeetingTask, Risk, Trace
from tests.conftest import TEST_PREFIX, auth_headers


async def test_ingest_success_writes_meeting_and_success_trace(
    client, member_user, mock_extraction, mock_qdrant_upsert
):
    response = await client.post(
        "/api/meetings/ingest",
        headers=auth_headers(member_user),
        data={
            "meeting_title": f"{TEST_PREFIX}Ingest Success",
            "duration_minutes": "5",
            "transcript": "We decided to use X because it is good.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "A test summary."
    assert len(body["tasks"]) == 1
    assert len(body["decisions"]) == 1
    mock_qdrant_upsert.assert_called_once()

    meeting_id = body["meeting_id"]
    detail = await client.get(f"/api/meetings/{meeting_id}", headers=auth_headers(member_user))
    assert detail.status_code == 200

    async with async_session() as db:
        mid = uuid_mod.UUID(meeting_id)
        await db.execute(Trace.__table__.delete().where(Trace.meeting_id == mid))
        await db.execute(MeetingTask.__table__.delete().where(MeetingTask.meeting_id == mid))
        await db.execute(Decision.__table__.delete().where(Decision.meeting_id == mid))
        await db.execute(Meeting.__table__.delete().where(Meeting.id == mid))
        await db.commit()


async def test_ingest_generates_title_when_title_is_omitted(
    client, member_user, mock_extraction, mock_qdrant_upsert
):
    mock_extraction.return_value["title"] = f"{TEST_PREFIX}Automated Launch Review"
    response = await client.post(
        "/api/meetings/ingest",
        headers=auth_headers(member_user),
        data={"duration_minutes": "8", "transcript": "We reviewed the launch and approved it."},
    )

    assert response.status_code == 200
    assert response.json()["title"] == f"{TEST_PREFIX}Automated Launch Review"
    detail = await client.get(
        f"/api/meetings/{response.json()['meeting_id']}", headers=auth_headers(member_user)
    )
    assert detail.json()["title"] == f"{TEST_PREFIX}Automated Launch Review"


async def test_meeting_title_can_be_edited(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "Original title", "Engineering")
    with patch("app.services.qdrant_service.update_meeting_title") as update_index:
        response = await client.patch(
            f"/api/meetings/{meeting.id}/title",
            headers=auth_headers(member_user),
            json={"title": f"  {TEST_PREFIX}Edited title  "},
        )

    assert response.status_code == 200
    assert response.json()["title"] == f"{TEST_PREFIX}Edited title"
    update_index.assert_called_once_with(str(meeting.id), f"{TEST_PREFIX}Edited title")


async def test_meeting_delete_moves_record_to_recycle_bin_and_removes_vectors(
    client, member_user, make_meeting
):
    meeting = await make_meeting(member_user, "Delete me", "Engineering")
    with patch("app.services.qdrant_service.delete_meeting") as delete_index:
        response = await client.delete(
            f"/api/meetings/{meeting.id}", headers=auth_headers(member_user)
        )

    assert response.status_code == 200
    delete_index.assert_called_once_with(str(meeting.id))
    async with async_session() as db:
        deleted = await db.get(Meeting, meeting.id)
        assert deleted is not None
        assert deleted.deleted_at is not None

    hidden = await client.get(f"/api/meetings/{meeting.id}", headers=auth_headers(member_user))
    assert hidden.status_code == 404

    with patch("app.routes.recycle_bin.rebuild_meeting_index") as rebuild:
        restored = await client.post(
            f"/api/recycle-bin/meeting/{meeting.id}/restore",
            headers=auth_headers(member_user),
        )
    assert restored.status_code == 200
    rebuild.assert_called_once()
    visible = await client.get(f"/api/meetings/{meeting.id}", headers=auth_headers(member_user))
    assert visible.status_code == 200


async def test_meeting_delete_keeps_record_when_vector_cleanup_fails(
    client, member_user, make_meeting
):
    meeting = await make_meeting(member_user, "Delete safely", "Engineering")
    with patch(
        "app.services.qdrant_service.delete_meeting", side_effect=ConnectionError("offline")
    ):
        response = await client.delete(
            f"/api/meetings/{meeting.id}", headers=auth_headers(member_user)
        )

    assert response.status_code == 500
    async with async_session() as db:
        assert await db.get(Meeting, meeting.id) is not None


async def test_detailed_summary_can_be_regenerated(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "Detailed Summary", "Engineering")
    detailed = "Executive overview\nA grounded recap.\n\nDiscussion details\n- The team reviewed scope."
    with (
        patch(
            "app.services.ai_extractor.generate_detailed_summary",
            return_value=(detailed, {"input_tokens": 20, "output_tokens": 30}),
        ) as generate,
        patch("app.services.qdrant_service.upsert_meeting") as reindex,
    ):
        response = await client.post(
            f"/api/meetings/{meeting.id}/summary/regenerate",
            headers=auth_headers(member_user),
        )

    assert response.status_code == 200
    assert response.json()["summary"] == detailed
    generate.assert_called_once_with("test transcript", f"{TEST_PREFIX}Detailed Summary")
    reindex.assert_called_once()

    detail = await client.get(f"/api/meetings/{meeting.id}", headers=auth_headers(member_user))
    assert detail.json()["summary"] == detailed


async def test_detailed_summary_can_be_human_reviewed(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "Reviewed Summary", "Engineering")
    with patch("app.routes.meetings.rebuild_meeting_index") as reindex:
        response = await client.patch(
            f"/api/meetings/{meeting.id}/summary",
            headers=auth_headers(member_user),
            json={"summary": "Archit approved the reviewed launch plan."},
        )

    assert response.status_code == 200
    assert response.json()["summary_verified_at"]
    reindex.assert_called_once()
    detail = await client.get(f"/api/meetings/{meeting.id}", headers=auth_headers(member_user))
    assert detail.json()["summary"] == "Archit approved the reviewed launch plan."
    assert detail.json()["summary_verified_at"]


async def test_decision_and_risk_corrections_are_verified_and_reindexed(
    client, member_user, make_meeting
):
    meeting = await make_meeting(member_user, "Correction Review", "Engineering")
    async with async_session() as db:
        decision = Decision(meeting_id=meeting.id, decision="Wrong decision")
        risk = Risk(meeting_id=meeting.id, description="Wrong risk", severity="Low")
        db.add_all([decision, risk])
        await db.commit()
        await db.refresh(decision)
        await db.refresh(risk)
        decision_id, risk_id = decision.id, risk.id

    with (
        patch("app.routes.decisions.rebuild_meeting_index") as decision_reindex,
        patch("app.routes.meetings.rebuild_meeting_index") as risk_reindex,
    ):
        decision_response = await client.patch(
            f"/api/decisions/{decision_id}",
            headers=auth_headers(member_user),
            json={
                "decision": "Use the reviewed launch plan",
                "reason": "The owner confirmed it",
                "alternatives": ["Delay"],
                "participants": ["Archit"],
            },
        )
        risk_response = await client.patch(
            f"/api/meetings/{meeting.id}/risks/{risk_id}",
            headers=auth_headers(member_user),
            json={"description": "Budget approval may be delayed", "severity": "High"},
        )

    assert decision_response.status_code == 200
    assert decision_response.json()["verified_at"]
    assert risk_response.status_code == 200
    assert risk_response.json()["verified_at"]
    decision_reindex.assert_called_once()
    risk_reindex.assert_called_once()

    detail = await client.get(f"/api/meetings/{meeting.id}", headers=auth_headers(member_user))
    assert detail.json()["decisions"][0]["decision"] == "Use the reviewed launch plan"
    assert detail.json()["risks"][0]["description"] == "Budget approval may be delayed"


async def test_meeting_exports_as_branded_pdf(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "PDF Export", "Engineering")
    response = await client.get(
        f"/api/meetings/{meeting.id}/export.pdf", headers=auth_headers(member_user)
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].endswith('pytest_PDF Export.pdf"')
    assert response.content.startswith(b"%PDF-")
    assert len(response.content) > 2_000


async def test_ingest_missing_transcript_and_audio_is_rejected(client, member_user):
    response = await client.post(
        "/api/meetings/ingest",
        headers=auth_headers(member_user),
        data={"meeting_title": "No content", "duration_minutes": "1"},
    )
    assert response.status_code == 400


async def test_ingest_commits_when_qdrant_is_unavailable(
    client, member_user, mock_extraction, mock_qdrant_upsert
):
    mock_qdrant_upsert.side_effect = ConnectionError("Qdrant is offline")
    response = await client.post(
        "/api/meetings/ingest",
        headers=auth_headers(member_user),
        data={
            "meeting_title": f"{TEST_PREFIX}Index Pending",
            "duration_minutes": "5",
            "transcript": "We completed the meeting even though semantic search was offline.",
        },
    )

    assert response.status_code == 200
    assert response.json()["indexing_status"] == "pending"
    meeting_id = uuid_mod.UUID(response.json()["meeting_id"])

    async with async_session() as db:
        assert await db.get(Meeting, meeting_id) is not None
        await db.execute(Trace.__table__.delete().where(Trace.meeting_id == meeting_id))
        await db.execute(MeetingTask.__table__.delete().where(MeetingTask.meeting_id == meeting_id))
        await db.execute(Decision.__table__.delete().where(Decision.meeting_id == meeting_id))
        await db.execute(Meeting.__table__.delete().where(Meeting.id == meeting_id))
        await db.commit()


async def test_ingest_failure_writes_error_trace_not_500_mask(
    client, member_user, mock_extraction, mock_qdrant_upsert
):
    """Regression test for the MissingGreenlet bug: a downstream failure
    (Sheets here) must surface its real error and still record a trace row,
    not crash while trying to write that trace."""
    async with async_session() as db:
        persisted_user = await db.get(type(member_user), member_user.id)
        persisted_user.google_sheets_spreadsheet_id = "fake-sheet-id"
        await db.commit()
    with patch(
        "app.services.sheets_service.ensure_sheet_tab",
        side_effect=Exception("Sheets API error 404: not found"),
    ):
        response = await client.post(
            "/api/meetings/ingest",
            headers=auth_headers(member_user),
            data={
                "meeting_title": f"{TEST_PREFIX}Ingest Failure",
                "duration_minutes": "5",
                "transcript": "We decided to use X because it is good.",
                "spreadsheet_id": "fake-sheet-id",
                "google_sheets_token": "fake-token",
            },
        )

    assert response.status_code == 500

    async with async_session() as db:
        result = await db.execute(
            select(Trace).where(Trace.meeting_title == f"{TEST_PREFIX}Ingest Failure")
        )
        traces = result.scalars().all()

    assert len(traces) == 1
    assert traces[0].status == "error"
    assert traces[0].meeting_id is None  # rolled-back meeting must not be referenced

    async with async_session() as db:
        await db.execute(Trace.__table__.delete().where(Trace.id == traces[0].id))
        await db.commit()


async def test_list_meetings_department_isolation(client, member_user, other_member_user, make_meeting):
    await make_meeting(member_user, "Eng Meeting", "Engineering")
    await make_meeting(other_member_user, "Sales Meeting", "Sales")

    eng_response = await client.get("/api/meetings", headers=auth_headers(member_user))
    titles = [m["title"] for m in eng_response.json()]
    assert f"{TEST_PREFIX}Eng Meeting" in titles
    assert f"{TEST_PREFIX}Sales Meeting" not in titles

    sales_response = await client.get("/api/meetings", headers=auth_headers(other_member_user))
    titles = [m["title"] for m in sales_response.json()]
    assert f"{TEST_PREFIX}Sales Meeting" in titles
    assert f"{TEST_PREFIX}Eng Meeting" not in titles


async def test_admins_see_everyone_only_in_the_admin_panel(client, admin_user, member_user, other_member_user, make_meeting):
    eng = await make_meeting(member_user, "Eng Meeting Admin Check", "Engineering")
    await make_meeting(other_member_user, "Sales Meeting Admin Check", "Sales")

    # Their own Meetings list holds only meetings they were part of...
    own = [m["title"] for m in (await client.get("/api/meetings", headers=auth_headers(admin_user))).json()]
    assert f"{TEST_PREFIX}Eng Meeting Admin Check" not in own
    # ...the Admin panel lists everyone's...
    listed = (await client.get("/api/admin/meetings?q=Admin%20Check", headers=auth_headers(admin_user))).json()
    titles = [m["title"] for m in listed["meetings"]]
    assert f"{TEST_PREFIX}Eng Meeting Admin Check" in titles and f"{TEST_PREFIX}Sales Meeting Admin Check" in titles
    # ...and any of them opens, flagged as an admin view.
    detail = await client.get(f"/api/meetings/{eng.id}", headers=auth_headers(admin_user))
    assert detail.status_code == 200 and detail.json()["viewing_as_admin"] is True
    # Members can't use the admin list.
    assert (await client.get("/api/admin/meetings", headers=auth_headers(member_user))).status_code == 403


async def test_get_meeting_cross_department_returns_404(client, member_user, other_member_user, make_meeting):
    sales_meeting = await make_meeting(other_member_user, "Private Sales Meeting", "Sales")

    response = await client.get(f"/api/meetings/{sales_meeting.id}", headers=auth_headers(member_user))
    assert response.status_code == 404


async def test_get_related_meetings_calls_qdrant_unscoped_then_filters_by_attendance(client, member_user, make_meeting):
    eng_meeting = await make_meeting(member_user, "Eng Related Meeting", "Engineering")
    past_meeting = await make_meeting(member_user, "Past Meeting", "Engineering")

    with patch("app.services.qdrant_service.find_related_meetings") as mock_related:
        mock_related.return_value = [
            {"meeting_id": str(past_meeting.id), "meeting_title": "Stale indexed title", "meeting_date": "2026-01-01", "score": 0.5}
        ]
        response = await client.get(
            f"/api/meetings/{eng_meeting.id}/related", headers=auth_headers(member_user)
        )

    assert response.status_code == 200
    assert response.json() == [{
        "meeting_id": str(past_meeting.id),
        "meeting_title": past_meeting.title,
        "meeting_date": past_meeting.date.isoformat(),
        "score": 0.5,
    }]
    mock_related.assert_called_once_with("test summary", str(eng_meeting.id), None, 8)


async def test_get_related_meetings_omits_stale_index_entries(client, member_user, make_meeting):
    eng_meeting = await make_meeting(member_user, "Eng Related Meeting", "Engineering")

    with patch("app.services.qdrant_service.find_related_meetings") as mock_related:
        mock_related.return_value = [{
            "meeting_id": str(uuid_mod.uuid4()),
            "meeting_title": "Deleted meeting",
            "meeting_date": "2026-01-01",
            "score": 0.5,
        }]
        response = await client.get(
            f"/api/meetings/{eng_meeting.id}/related", headers=auth_headers(member_user)
        )

    assert response.status_code == 200
    assert response.json() == []


async def test_get_related_meetings_cross_department_returns_404(
    client, member_user, other_member_user, make_meeting
):
    sales_meeting = await make_meeting(other_member_user, "Private Sales Related Meeting", "Sales")

    response = await client.get(
        f"/api/meetings/{sales_meeting.id}/related", headers=auth_headers(member_user)
    )
    assert response.status_code == 404


async def test_ingest_persists_conflict_note_on_decision(
    client, member_user, mock_extraction, mock_qdrant_upsert, mock_contradiction_check
):
    conflict_note = "Contradicts a decision from \"Q1 Planning\" (2026-03-01): use PostgreSQL."
    mock_contradiction_check.return_value = {
        "note": conflict_note,
        "usage": {"input_tokens": 50, "output_tokens": 20, "cache_tokens_read": 0, "cache_tokens_written": 0},
    }

    response = await client.post(
        "/api/meetings/ingest",
        headers=auth_headers(member_user),
        data={
            "meeting_title": f"{TEST_PREFIX}Ingest Conflict",
            "duration_minutes": "5",
            "transcript": "We decided to use X because it is good.",
        },
    )
    assert response.status_code == 200
    meeting_id = response.json()["meeting_id"]
    mock_contradiction_check.assert_called_once()
    args, kwargs = mock_contradiction_check.call_args
    assert args == ("Use X", "Engineering")
    # Never compared against the meeting itself.
    assert meeting_id not in kwargs["meeting_ids"]

    detail = await client.get(f"/api/meetings/{meeting_id}", headers=auth_headers(member_user))
    assert detail.status_code == 200
    decisions = detail.json()["decisions"]
    assert len(decisions) == 1
    assert decisions[0]["conflict_note"] == conflict_note

    async with async_session() as db:
        mid = uuid_mod.UUID(meeting_id)
        await db.execute(Trace.__table__.delete().where(Trace.meeting_id == mid))
        await db.execute(MeetingTask.__table__.delete().where(MeetingTask.meeting_id == mid))
        await db.execute(Decision.__table__.delete().where(Decision.meeting_id == mid))
        await db.execute(Meeting.__table__.delete().where(Meeting.id == mid))
        await db.commit()


async def test_list_meetings_full_text_transcript_search(client, member_user, other_member_user, make_meeting):
    await make_meeting(
        member_user, "Search Target Meeting", "Engineering",
        transcript="We discussed migrating to a serverless database called Neon for cost reasons.",
    )
    await make_meeting(
        member_user, "Unrelated Meeting", "Engineering",
        transcript="We discussed the office snack budget for next quarter.",
    )
    # A same-keyword meeting in a different department must not leak through.
    await make_meeting(
        other_member_user, "Sales Neon Mention", "Sales",
        transcript="Neon signage for the new office lobby.",
    )

    response = await client.get(
        "/api/meetings", params={"q": "serverless database"}, headers=auth_headers(member_user)
    )
    assert response.status_code == 200
    titles = [m["title"] for m in response.json()]
    assert f"{TEST_PREFIX}Search Target Meeting" in titles
    assert f"{TEST_PREFIX}Unrelated Meeting" not in titles
    assert f"{TEST_PREFIX}Sales Neon Mention" not in titles


# --- Meet audio assembly (no DB needed — pure filesystem + ffmpeg) ---
# The extension records the Meet tab and the user's microphone as two
# separate MediaRecorder streams (see src/offscreen.js), uploading each
# chunk to /api/transcribe for text — /api/meetings/ingest later finds those
# staged chunks and reassembles them into one playable file.

def _make_silent_webm(path, seconds: float = 0.3) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
            "-t", str(seconds), "-c:a", "libopus", str(path),
        ],
        check=True, capture_output=True,
    )


def test_concat_webm_chunks_joins_multiple_chunks(tmp_path):
    chunk_a = tmp_path / "000000_tab.webm"
    chunk_b = tmp_path / "000001_tab.webm"
    _make_silent_webm(chunk_a)
    _make_silent_webm(chunk_b)
    output = tmp_path / "tab_full.webm"

    _concat_webm_chunks([chunk_a, chunk_b], output)

    assert output.exists() and output.stat().st_size > 0


def test_assemble_meeting_audio_tab_only(tmp_path):
    _make_silent_webm(tmp_path / "000000_tab.webm")
    output = tmp_path / "recording.webm"

    _assemble_meeting_audio(tmp_path, output)

    assert output.exists() and output.stat().st_size > 0


def test_assemble_meeting_audio_mixes_tab_and_mic(tmp_path):
    _make_silent_webm(tmp_path / "000000_tab.webm")
    _make_silent_webm(tmp_path / "000000_mic.webm")
    output = tmp_path / "recording.webm"

    _assemble_meeting_audio(tmp_path, output)

    assert output.exists() and output.stat().st_size > 0


def test_assemble_meeting_audio_requires_at_least_one_chunk(tmp_path):
    with pytest.raises(RuntimeError):
        _assemble_meeting_audio(tmp_path, tmp_path / "recording.webm")


# --- Regression: a retried ingest must not create a second meeting -----------


async def test_ingest_is_idempotent_per_client_meeting_id(
    client, member_user, mock_extraction, mock_qdrant_upsert
):
    """The MV3 service worker can be evicted while /ingest is in flight; the
    extension then recovers the record after five minutes and finalizes again.
    Without idempotency that produces the meeting, its tasks, its decisions and
    its Sheets rows twice."""
    client_id = f"meeting_{uuid_mod.uuid4().hex[:12]}"
    payload = {
        "meeting_title": f"{TEST_PREFIX}Idempotent Meeting",
        "duration_minutes": "5",
        "transcript": "We agreed to ship on Friday.",
        "client_meeting_id": client_id,
    }

    first = await client.post("/api/meetings/ingest", data=payload, headers=auth_headers(member_user))
    assert first.status_code == 200
    second = await client.post("/api/meetings/ingest", data=payload, headers=auth_headers(member_user))
    assert second.status_code == 200

    assert first.json()["meeting_id"] == second.json()["meeting_id"]
    assert second.json().get("deduplicated") is True

    async with async_session() as db:
        rows = (
            await db.execute(
                select(Meeting).where(
                    Meeting.user_id == member_user.id, Meeting.client_meeting_id == client_id
                )
            )
        ).scalars().all()
    assert len(rows) == 1

    await client.delete(f"/api/meetings/{first.json()['meeting_id']}", headers=auth_headers(member_user))
