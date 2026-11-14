"""Meeting Assistant workspace, end to end through the API against a real
database. Gemini, Deepgram and Qdrant are mocked; nothing calls out."""

import shutil
import subprocess
import uuid as uuid_mod
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.config import settings
from app.database.db import async_session
from app.rate_limit import limiter
from app.database.models import (
    Decision,
    Meeting,
    MeetingAttendee,
    MeetingTask,
    ProcessingStage,
    RecordingSession,
    Risk,
    Trace,
    TranscriptSegment,
)
from app.services import meeting_pipeline
from tests.conftest import TEST_PREFIX, auth_headers

TRANSCRIPT = (
    "[00:00:01] Asha: Budget is 5 lakh, not 50 lakh.\n"
    "[00:00:06] Ravi: I will send the revised deck by Friday.\n"
    "[00:00:12] Asha: Maybe we move the launch, let's think about it."
)


def _extraction(**overrides) -> dict:
    result = {
        "title": f"{TEST_PREFIX}Budget review",
        "tasks": [
            {"task": "Send the revised deck", "assignedTo": "Ravi", "dueDate": "Friday", "resolvedDueDate": "",
             "priority": "Medium", "project": "", "evidence": [{"segment": 1, "excerpt": "send the revised deck"}]},
            {"task": "Unsupported task", "assignedTo": "", "dueDate": "", "resolvedDueDate": "",
             "priority": "Low", "project": "", "evidence": [{"segment": 42, "excerpt": "nothing"}]},
        ],
        "decisions": [
            {"decision": "Budget is 5 lakh", "reason": "", "alternatives": [], "participants": [], "project": "",
             "evidence": [{"segment": 0, "excerpt": "Budget is 5 lakh, not 50 lakh"}]},
        ],
        "risks": [],
        "summary": "Budget confirmed at 5 lakh.",
        "overview": "Short budget review.",
        "key_topics": ["Budget"],
        "open_questions": ["Proposed, not confirmed: Move the launch"],
        "highlights": [],
        "next_steps": [],
        "sections": [{"title": "Budget", "summary": "5 lakh", "evidence": [{"segment": 0, "excerpt": "Budget is 5 lakh"}]}],
        "template_sections": [],
        "follow_up_draft": "Subject: Recap\n\nThanks all.",
        "speaker_activity": [],
        "input_tokens": 10, "output_tokens": 5, "cache_tokens_read": 0, "cache_tokens_written": 0,
        "model": "test-model", "prompt_version": "test", "chunk_count": 1, "template": "general",
    }
    result.update(overrides)
    return result


@pytest.fixture
def no_index():
    with patch("app.services.qdrant_service.upsert_meeting"), patch("app.services.qdrant_service.replace_meeting"), patch(
        "app.services.qdrant_service.delete_meeting"
    ):
        yield


async def _cleanup(meeting_id):
    async with async_session() as db:
        await db.execute(Trace.__table__.delete().where(Trace.meeting_id == meeting_id))
        await db.execute(MeetingTask.__table__.delete().where(MeetingTask.meeting_id == meeting_id))
        await db.execute(Decision.__table__.delete().where(Decision.meeting_id == meeting_id))
        await db.execute(Risk.__table__.delete().where(Risk.meeting_id == meeting_id))
        recordings = (await db.execute(select(RecordingSession).where(RecordingSession.meeting_id == meeting_id))).scalars().all()
        for recording in recordings:
            shutil.rmtree(Path(settings.recordings_dir).resolve() / str(recording.id), ignore_errors=True)
            await db.delete(recording)
        await db.execute(Meeting.__table__.delete().where(Meeting.id == meeting_id))
        await db.commit()


@pytest.fixture
def no_rate_limit():
    # These tests ingest many meetings back to back; the 10/minute limit is
    # covered by the API's own configuration, not exercised here.
    with patch.object(limiter, "enabled", False):
        yield


@pytest.fixture
async def ingested(client, member_user, no_index, no_rate_limit):
    created = []

    async def _ingest(extraction=None, side_effect=None, transcript=TRANSCRIPT, attendees=None):
        with patch("app.services.ai_extractor.extract_from_transcript") as mock:
            if side_effect is not None:
                mock.side_effect = side_effect
            else:
                mock.return_value = extraction or _extraction()
            data = {"meeting_title": f"{TEST_PREFIX}Assistant", "transcript": transcript, "source": "paste"}
            if attendees is not None:
                import json

                data["attendees"] = json.dumps(attendees)
            response = await client.post("/api/meetings/ingest", headers=auth_headers(member_user), data=data)
        assert response.status_code == 200, response.text
        meeting_id = uuid_mod.UUID(response.json()["meeting_id"])
        created.append(meeting_id)
        return response.json(), mock

    yield _ingest
    for meeting_id in created:
        await _cleanup(meeting_id)


async def test_ingest_stores_timestamped_segments_and_grounded_items(client, member_user, ingested):
    body, mock = await ingested()
    meeting_id = body["meeting_id"]
    # The model was shown citable segment ids.
    assert [s.seq for s in mock.call_args.kwargs["segments"]] == [0, 1, 2]

    transcript = (await client.get(f"/api/meetings/{meeting_id}/transcript", headers=auth_headers(member_user))).json()
    assert transcript["total"] == 3
    assert transcript["segments"][1]["start_ms"] == 6000
    assert transcript["segments"][1]["speaker"] == "Ravi"

    detail = (await client.get(f"/api/meetings/{meeting_id}", headers=auth_headers(member_user))).json()
    tasks = {t["description"]: t for t in detail["tasks"]}
    assert tasks["Send the revised deck"]["evidence"][0]["verified"] is True
    assert tasks["Send the revised deck"]["evidence"][0]["start_ms"] == 6000
    # A citation to a segment that doesn't exist is rejected, and flagged.
    assert tasks["Unsupported task"]["evidence"] == []
    assert tasks["Unsupported task"]["ai_flags"] == ["evidence_missing"]
    assert tasks["Unsupported task"]["owner"] is None
    assert detail["insights"]["follow_up_draft"].startswith("Subject: Recap")
    assert detail["source"] == "paste"

    stages = (await client.get(f"/api/meetings/{meeting_id}/processing", headers=auth_headers(member_user))).json()
    by_stage = {s["stage"]: s["status"] for s in stages["stages"]}
    assert by_stage["extraction"] == "succeeded"
    assert by_stage["transcription"] == "skipped"


async def test_owner_resolves_only_to_an_unambiguous_attendee(client, member_user, other_member_user, ingested):
    async with async_session() as db:
        other = await db.get(type(other_member_user), other_member_user.id)
        other.name = f"{TEST_PREFIX}Ravi Kumar"
        await db.commit()
    extraction = _extraction()
    extraction["tasks"][0]["assignedTo"] = f"{TEST_PREFIX}Ravi Kumar"
    body, _ = await ingested(extraction, attendees=[{"user_id": str(other_member_user.id), "name": f"{TEST_PREFIX}Ravi Kumar"}])
    detail = (await client.get(f"/api/meetings/{body['meeting_id']}", headers=auth_headers(member_user))).json()
    task = next(t for t in detail["tasks"] if t["description"] == "Send the revised deck")
    assert task["owner_user_id"] == str(other_member_user.id)


async def test_extraction_failure_keeps_a_usable_transcript_and_retry_does_not_retranscribe(client, member_user, ingested):
    body, _ = await ingested(side_effect=RuntimeError("Gemini is down"))
    meeting_id = body["meeting_id"]
    assert body["extraction_status"] == "failed"
    assert body["tasks"] == []

    transcript = (await client.get(f"/api/meetings/{meeting_id}/transcript", headers=auth_headers(member_user))).json()
    assert transcript["total"] == 3
    stages = {s["stage"]: s for s in (await client.get(f"/api/meetings/{meeting_id}/processing", headers=auth_headers(member_user))).json()["stages"]}
    assert stages["extraction"]["status"] == "failed"
    assert "Gemini is down" in stages["extraction"]["last_error"]

    # Transcription can't be "retried" for a pasted transcript — nothing to pay for twice.
    response = await client.post(f"/api/meetings/{meeting_id}/processing/transcription/retry", headers=auth_headers(member_user))
    assert response.status_code == 409

    with patch("app.services.ai_extractor.extract_from_transcript", return_value=_extraction()):
        response = await client.post(f"/api/meetings/{meeting_id}/processing/extraction/retry", headers=auth_headers(member_user))
    assert response.status_code == 202
    detail = (await client.get(f"/api/meetings/{meeting_id}", headers=auth_headers(member_user))).json()
    assert len(detail["tasks"]) == 2
    stages = {s["stage"]: s for s in (await client.get(f"/api/meetings/{meeting_id}/processing", headers=auth_headers(member_user))).json()["stages"]}
    assert stages["extraction"]["status"] == "succeeded"
    assert stages["extraction"]["attempts"] == 1  # the retry's run; the failure was recorded at ingest


async def test_corrections_make_insights_stale_and_regeneration_preserves_reviewed_items(client, member_user, ingested):
    body, _ = await ingested()
    meeting_id = body["meeting_id"]
    headers = auth_headers(member_user)
    transcript = (await client.get(f"/api/meetings/{meeting_id}/transcript", headers=headers)).json()
    segment = transcript["segments"][1]

    response = await client.patch(
        f"/api/meetings/{meeting_id}/transcript/segments/{segment['id']}",
        json={"text": "I will send the revised deck by Thursday."}, headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["insights_stale"] is True
    assert response.json()["original_text"] == "I will send the revised deck by Friday."
    history = (await client.get(f"/api/meetings/{meeting_id}/transcript/history", headers=headers)).json()
    assert history[0]["old_value"].endswith("Friday.") and history[0]["new_value"].endswith("Thursday.")

    # Approve one task by editing it; leave the other untouched.
    detail = (await client.get(f"/api/meetings/{meeting_id}", headers=headers)).json()
    kept = next(t for t in detail["tasks"] if t["description"] == "Send the revised deck")
    await client.patch(f"/api/tasks/{kept['id']}", json={"deadline": "Thursday"}, headers=headers)

    regenerated = _extraction(tasks=[
        {"task": "Send the revised deck", "assignedTo": "Ravi", "dueDate": "Thursday", "resolvedDueDate": "", "priority": "Medium", "project": "",
         "evidence": [{"segment": 1, "excerpt": "by Thursday"}]},
        {"task": "Book the venue", "assignedTo": "", "dueDate": "", "resolvedDueDate": "", "priority": "Low", "project": "",
         "evidence": [{"segment": 2, "excerpt": "move the launch"}]},
    ])
    with patch("app.services.ai_extractor.extract_from_transcript", return_value=regenerated) as mock:
        response = await client.post(f"/api/meetings/{meeting_id}/insights/regenerate", json={"template": "client_call"}, headers=headers)
    assert response.status_code == 200, response.text
    # The corrected text is what the model saw.
    assert "Thursday" in mock.call_args.args[0]
    assert mock.call_args.kwargs["template"] == "client_call"

    detail = (await client.get(f"/api/meetings/{meeting_id}", headers=headers)).json()
    descriptions = sorted(t["description"] for t in detail["tasks"])
    # The reviewed task survived untouched (no duplicate), the unreviewed
    # "Unsupported task" was replaced, and the new item was added.
    assert descriptions == ["Book the venue", "Send the revised deck"]
    assert next(t for t in detail["tasks"] if t["description"] == "Send the revised deck")["id"] == kept["id"]
    assert detail["insights_stale"] is False
    assert detail["template"] == "client_call"


async def test_speaker_rename_and_revert(client, member_user, ingested):
    body, _ = await ingested(transcript="Speaker 1: hello there\nSpeaker 2: hi")
    meeting_id = body["meeting_id"]
    headers = auth_headers(member_user)
    response = await client.put(f"/api/meetings/{meeting_id}/transcript/speakers", json={"names": {"0": "Asha"}}, headers=headers)
    assert response.json()["changed"] == 1
    transcript = (await client.get(f"/api/meetings/{meeting_id}/transcript?speaker=0", headers=headers)).json()
    assert transcript["matched"] == 1 and transcript["segments"][0]["speaker"] == "Asha"
    response = await client.put(f"/api/meetings/{meeting_id}/transcript/speakers", json={"names": {"9": "Nobody"}}, headers=headers)
    assert response.status_code == 422

    segment_id = transcript["segments"][0]["id"]
    await client.patch(f"/api/meetings/{meeting_id}/transcript/segments/{segment_id}", json={"text": "hello everyone"}, headers=headers)
    reverted = (await client.post(f"/api/meetings/{meeting_id}/transcript/segments/{segment_id}/revert", headers=headers)).json()
    assert reverted["text"] == "hello there" and reverted["edited"] is False


async def test_exports(client, member_user, ingested):
    body, _ = await ingested(transcript="Asha: no timestamps here")
    headers = auth_headers(member_user)
    response = await client.get(f"/api/meetings/{body['meeting_id']}/transcript/export?format=srt", headers=headers)
    assert response.status_code == 409
    response = await client.get(f"/api/meetings/{body['meeting_id']}/transcript/export?format=json", headers=headers)
    assert response.status_code == 200 and response.json()["segments"][0]["speaker"] == "Asha"
    assert "attachment" in response.headers["content-disposition"]


async def test_comments_and_bookmarks(client, member_user, ingested):
    body, _ = await ingested()
    meeting_id = body["meeting_id"]
    headers = auth_headers(member_user)
    segment = (await client.get(f"/api/meetings/{meeting_id}/transcript", headers=headers)).json()["segments"][1]
    comment = await client.post(f"/api/meetings/{meeting_id}/comments", json={"body": "Is Friday realistic?", "segment_id": segment["id"]}, headers=headers)
    assert comment.status_code == 201 and comment.json()["start_ms"] == 6000
    bookmark = await client.post(f"/api/meetings/{meeting_id}/bookmarks", json={"label": "Deck promise", "segment_id": segment["id"]}, headers=headers)
    assert bookmark.status_code == 201 and bookmark.json()["start_ms"] == 6000
    bad = await client.post(f"/api/meetings/{meeting_id}/bookmarks", json={"label": "x", "start_ms": 5000, "end_ms": 1000}, headers=headers)
    assert bad.status_code == 422
    foreign = await client.post(f"/api/meetings/{meeting_id}/comments", json={"body": "x", "segment_id": str(uuid_mod.uuid4())}, headers=headers)
    assert foreign.status_code == 422
    assert len((await client.get(f"/api/meetings/{meeting_id}/comments", headers=headers)).json()) == 1


async def test_non_attendee_cannot_reach_anything(client, member_user, other_member_user, ingested):
    body, _ = await ingested()
    meeting_id = body["meeting_id"]
    outsider = auth_headers(other_member_user)
    for method, path, kwargs in [
        ("get", f"/api/meetings/{meeting_id}/transcript", {}),
        ("get", f"/api/meetings/{meeting_id}/transcript/export?format=txt", {}),
        ("get", f"/api/meetings/{meeting_id}/transcript/history", {}),
        ("get", f"/api/meetings/{meeting_id}/processing", {}),
        ("get", f"/api/meetings/{meeting_id}/analytics", {}),
        ("get", f"/api/meetings/{meeting_id}/comments", {}),
        ("get", f"/api/meetings/{meeting_id}/bookmarks", {}),
        ("get", f"/api/meetings/{meeting_id}/insights/runs", {}),
        ("post", f"/api/meetings/{meeting_id}/comments", {"json": {"body": "hi"}}),
        ("post", f"/api/meetings/{meeting_id}/insights/regenerate", {"json": {}}),
        ("post", f"/api/meetings/{meeting_id}/processing/indexing/retry", {}),
        ("put", f"/api/meetings/{meeting_id}/transcript/speakers", {"json": {"names": {}}}),
    ]:
        response = await getattr(client, method)(path, headers=outsider, **kwargs)
        assert response.status_code == 404, (path, response.status_code)

    with patch("app.services.memory_retriever.answer_query_for_meetings") as answer:
        response = await client.post("/api/chat", json={"query": "budget?", "meeting_ids": [meeting_id, str(uuid_mod.uuid4())]}, headers=outsider)
    assert response.status_code == 404
    answer.assert_not_called()
    listed = (await client.get("/api/meetings?q=lakh", headers=outsider)).json()
    assert meeting_id not in {m["id"] for m in listed}

    # Gaining attendee access grants it immediately; losing it revokes it immediately.
    async with async_session() as db:
        row = MeetingAttendee(meeting_id=uuid_mod.UUID(meeting_id), user_id=other_member_user.id, display_name="x", kind="internal")
        db.add(row)
        await db.commit()
    assert (await client.get(f"/api/meetings/{meeting_id}/transcript", headers=outsider)).status_code == 200
    async with async_session() as db:
        await db.delete(await db.get(MeetingAttendee, row.id))
        await db.commit()
    assert (await client.get(f"/api/meetings/{meeting_id}/transcript", headers=outsider)).status_code == 404


async def test_multi_meeting_chat_rechecks_scope(client, member_user, ingested):
    first, _ = await ingested()
    second, _ = await ingested()
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_tokens_read": 0, "cache_tokens_written": 0}
    with patch("app.services.memory_retriever.generate_text", return_value=("5 lakh [M1:S0] vs [M2:S0]", usage)):
        response = await client.post(
            "/api/chat", json={"query": "budget?", "meeting_ids": [first["meeting_id"], second["meeting_id"]]},
            headers=auth_headers(member_user),
        )
    assert response.status_code == 200, response.text
    sources = response.json()["sources"]
    assert {s["meeting_id"] for s in sources} == {first["meeting_id"], second["meeting_id"]}
    assert all(s["segments"][0]["seq"] == 0 for s in sources)

    # Deleting one meeting drops it from the stored conversation's sources.
    conversation_id = response.json()["conversation_id"]
    await client.delete(f"/api/meetings/{second['meeting_id']}", headers=auth_headers(member_user))
    stored = (await client.get(f"/api/chat/conversations/{conversation_id}", headers=auth_headers(member_user))).json()
    assert {s["meeting_id"] for s in stored["messages"][1]["sources"]} == {first["meeting_id"]}


async def test_deleted_meeting_is_not_resurrected_by_a_late_job(client, member_user, ingested):
    body, _ = await ingested()
    meeting_id = uuid_mod.UUID(body["meeting_id"])
    await client.delete(f"/api/meetings/{meeting_id}", headers=auth_headers(member_user))
    async with async_session() as db:
        before = len((await db.execute(select(MeetingTask).where(MeetingTask.meeting_id == meeting_id))).scalars().all())
    with patch("app.services.ai_extractor.extract_from_transcript", return_value=_extraction()) as mock:
        assert await meeting_pipeline.extract(meeting_id, None) is False
    mock.assert_not_called()
    async with async_session() as db:
        after = len((await db.execute(select(MeetingTask).where(MeetingTask.meeting_id == meeting_id))).scalars().all())
    assert after == before


async def test_analytics_are_deterministic(client, member_user, ingested):
    body, _ = await ingested()
    analytics = (await client.get(f"/api/meetings/{body['meeting_id']}/analytics", headers=auth_headers(member_user))).json()
    assert analytics["tasks"]["total"] == 2
    assert analytics["decisions"] == 1
    # Pasted lines have start times but no end time for the last line, so
    # participation falls back to word counts rather than inventing a duration.
    assert analytics["talk_time"]["basis"] == "words"
    assert analytics["usage"]["estimated_cost_usd"] is None  # no rates configured


# --- uploads ------------------------------------------------------------------------


def _make_wav(path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(path)],
        check=True, capture_output=True,
    )


async def test_upload_requires_consent_and_real_media(client, member_user, tmp_path):
    headers = auth_headers(member_user)
    fake = tmp_path / "notes.mp3"
    fake.write_text("this is not audio")
    response = await client.post(
        "/api/meetings/upload", headers=headers,
        files={"file": ("notes.mp3", fake.read_bytes(), "audio/mpeg")}, data={"consent_acknowledged": "false"},
    )
    assert response.status_code == 422
    response = await client.post(
        "/api/meetings/upload", headers=headers,
        files={"file": ("notes.mp3", fake.read_bytes(), "audio/mpeg")}, data={"consent_acknowledged": "true"},
    )
    assert response.status_code == 415


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
async def test_upload_processes_in_the_background_and_is_idempotent(client, member_user, tmp_path, no_index, no_rate_limit):
    wav = tmp_path / "standup.wav"
    _make_wav(wav)
    headers = auth_headers(member_user)
    key = uuid_mod.uuid4().hex
    with patch.object(settings, "fixture_mode", True), patch.object(settings, "deepgram_api_key", ""), patch(
        "app.services.ai_extractor.extract_from_transcript", return_value=_extraction(title=f"{TEST_PREFIX}Standup")
    ):
        response = await client.post(
            "/api/meetings/upload", headers=headers,
            files={"file": ("standup.wav", wav.read_bytes(), "audio/wav")},
            data={"consent_acknowledged": "true", "idempotency_key": key, "template": "standup"},
        )
        assert response.status_code == 202, response.text
        meeting_id = response.json()["meeting_id"]
        again = await client.post(
            "/api/meetings/upload", headers=headers,
            files={"file": ("standup.wav", wav.read_bytes(), "audio/wav")},
            data={"consent_acknowledged": "true", "idempotency_key": key},
        )
    try:
        assert again.json() == {"meeting_id": meeting_id, "status": "duplicate", "deduplicated": True}
        stages = {s["stage"]: s["status"] for s in (await client.get(f"/api/meetings/{meeting_id}/processing", headers=headers)).json()["stages"]}
        assert stages == {"transcription": "succeeded", "extraction": "succeeded", "indexing": "succeeded", "audio": "succeeded"}
        transcript = (await client.get(f"/api/meetings/{meeting_id}/transcript", headers=headers)).json()
        assert transcript["has_timestamps"] is True and transcript["has_recording"] is True
        assert "[Development fixture]" in transcript["segments"][0]["text"]
        detail = (await client.get(f"/api/meetings/{meeting_id}", headers=headers)).json()
        assert detail["title"] == f"{TEST_PREFIX}Standup"  # no title given, so the AI title is adopted
        assert detail["template"] == "standup" and detail["recording"] is not None
        async with async_session() as db:
            assert (await db.execute(select(ProcessingStage).where(ProcessingStage.meeting_id == uuid_mod.UUID(meeting_id)))).scalars().all()
            segments = (await db.execute(select(TranscriptSegment).where(TranscriptSegment.meeting_id == uuid_mod.UUID(meeting_id)))).scalars().all()
            assert len(segments) == 2
    finally:
        await _cleanup(uuid_mod.UUID(meeting_id))


async def test_an_empty_regeneration_keeps_the_existing_notes(client, member_user, ingested):
    # Production, 2026-10-10: a regeneration came back with no items and
    # silently erased a meeting's 24 checked tasks and decisions.
    task = {"assignedTo": "", "dueDate": "", "resolvedDueDate": "", "priority": "Low", "project": ""}
    body, _ = await ingested(extraction=_extraction(tasks=[
        {**task, "task": "Send the revised deck", "evidence": [{"segment": 1, "excerpt": "send the revised deck"}]},
        {**task, "task": "Confirm the budget", "evidence": [{"segment": 0, "excerpt": "Budget is 5 lakh"}]},
        {**task, "task": "Think about the launch", "evidence": [{"segment": 2, "excerpt": "move the launch"}]},
    ]))
    meeting_id = body["meeting_id"]
    headers = auth_headers(member_user)
    before = sorted(t["description"] for t in (await client.get(f"/api/meetings/{meeting_id}", headers=headers)).json()["tasks"])
    assert len(before) == 3

    empty = _extraction(tasks=[], decisions=[], risks=[], template_sections=[])
    with patch("app.services.ai_extractor.extract_from_transcript", return_value=empty):
        response = await client.post(f"/api/meetings/{meeting_id}/insights/regenerate", json={}, headers=headers)
    assert response.status_code == 409 and "kept" in response.json()["detail"]
    detail = (await client.get(f"/api/meetings/{meeting_id}", headers=headers)).json()
    assert sorted(t["description"] for t in detail["tasks"]) == before
    assert len(detail["decisions"]) == 1
