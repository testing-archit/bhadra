"""Board grounding, graph validation and retry-safe live caption delivery."""

import time
import uuid
import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import settings
from app.main import app
from app.database.db import async_session
from app.database.models import CaptureRequest, LiveCaption, Meeting, MeetingBoard
from app.routes.boards import BoardUpdate
from app.services.board_service import notes_to_canvas
from tests.conftest import auth_headers
from tests.test_bot_captions import meeting_session


def test_initial_board_uses_existing_meeting_facts_and_source_times():
    meeting = SimpleNamespace(title="Budget", summary="We agreed on a smaller launch.")
    decision = SimpleNamespace(id=uuid.uuid4(), decision="Cut launch spend", reason="Keep runway",
                               evidence=[{"start_ms": 12000, "segment_id": "turn-2"}])
    task = SimpleNamespace(id=uuid.uuid4(), description="Revise the deck", owner="Ravi",
                           deadline="Friday", evidence=[])
    insight = SimpleNamespace(overview=None, open_questions=["Who owns the venue? "])
    nodes, edges = notes_to_canvas(meeting, [task], [decision], [], insight)

    assert {node["kind"] for node in nodes} == {"summary", "decision", "task", "question"}
    grounded = next(node for node in nodes if node["kind"] == "decision")
    assert grounded["source_start_ms"] == 12000
    assert grounded["source_id"] == "turn-2"
    assert grounded["text"] == "Keep runway"
    assert {edge["target"] for edge in edges} == {node["id"] for node in nodes if node["kind"] in {"decision", "task"}}


def test_board_update_rejects_edges_to_missing_nodes():
    with pytest.raises(ValidationError, match="existing nodes"):
        BoardUpdate.model_validate({
            "expected_version": 1, "title": "Plan", "nodes": [],
            "edges": [{"id": "edge-1", "source": "not-here", "target": "also-missing"}],
        })


@pytest.mark.asyncio
async def test_caption_upload_retries_same_sequence_after_network_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(meeting_session.config, "SESSIONS_DIR", tmp_path)
    session = meeting_session.MeetingSession({"capture_request_id": str(uuid.uuid4())})
    session.captions.audio_started_at = time.monotonic() - 60
    session.captions.export = lambda: [{"speaker": "Ravi", "text": "Let's move launch to Friday", "start": 10.0, "end": 13.0}]
    sent = []

    def send(_capture_id, batch):
        sent.append(batch)
        return len(sent) > 1

    monkeypatch.setattr(meeting_session.uploader, "live_captions", send)
    await session.flush_live_captions(force=True)
    await session.flush_live_captions(force=True)
    assert sent[0] == sent[1]
    assert session._caption_seq == 1
    await session.flush_live_captions(force=True)
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_board_access_edit_conflict_and_history(client, member_user, other_member_user):
    async with async_session() as db:
        meeting = Meeting(user_id=member_user.id, title="Budget review", date=datetime.datetime.now(datetime.UTC),
                          transcript="Ravi: Cut launch spend", summary="We cut launch spend.")
        db.add(meeting)
        await db.commit()
        meeting_id = meeting.id
    owner = auth_headers(member_user)
    outsider = auth_headers(other_member_user)
    try:
        denied = await client.get(f"/api/boards/meetings/{meeting_id}", headers=outsider)
        assert denied.status_code == 404
        response = await client.get(f"/api/boards/meetings/{meeting_id}", headers=owner)
        assert response.status_code == 200, response.text
        board = response.json()
        assert [node["title"] for node in board["nodes"]] == ["Meeting in brief"]
        changed = {**board, "nodes": [{**board["nodes"][0], "text": "Confirmed by the team"}]}
        saved = await client.put(f"/api/boards/{board['id']}", headers=owner, json={
            "expected_version": board["version"], "title": board["title"],
            "nodes": changed["nodes"], "edges": changed["edges"],
        })
        assert saved.status_code == 200, saved.text
        assert saved.json()["version"] == 2
        assert saved.json()["nodes"][0]["origin"] == "manual"
        conflict = await client.put(f"/api/boards/{board['id']}", headers=owner, json={
            "expected_version": 1, "title": board["title"],
            "nodes": changed["nodes"], "edges": changed["edges"],
        })
        assert conflict.status_code == 409
        history = await client.get(f"/api/boards/{board['id']}/history", headers=owner)
        assert [row["version"] for row in history.json()] == [2, 1]
    finally:
        async with async_session() as db:
            row = await db.get(Meeting, meeting_id)
            if row:
                await db.delete(row)
                await db.commit()


@pytest.mark.asyncio
async def test_live_caption_ingest_is_idempotent_and_private(client, member_user, other_member_user, monkeypatch):
    monkeypatch.setattr(settings, "bot_api_secret", "test-board-bot-secret")
    async with async_session() as db:
        capture = CaptureRequest(
            user_id=member_user.id, platform="google_meet", meeting_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij", title="Planning", status="capturing",
            consent_acknowledged_at=datetime.datetime.now(datetime.UTC),
        )
        db.add(capture)
        await db.commit()
        capture_id = capture.id
    payload = {"captions": [{"seq": 1, "speaker": "Ravi", "text": "The launch is Friday", "start": 10, "end": 13}]}
    bot_headers = {"Authorization": "Bot test-board-bot-secret"}
    try:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=True), base_url="http://test") as strict_client:
            for _ in range(2):
                result = await strict_client.post(f"/api/bot/capture-requests/{capture_id}/captions", headers=bot_headers, json=payload)
                assert result.status_code == 200, result.text
        async with async_session() as db:
            assert await db.scalar(select(func.count()).select_from(LiveCaption).where(LiveCaption.capture_request_id == capture_id)) == 1
            assert await db.scalar(select(func.count()).select_from(MeetingBoard).where(MeetingBoard.capture_request_id == capture_id)) == 1
        private = await client.get(f"/api/boards/captures/{capture_id}/captions", headers=auth_headers(other_member_user))
        assert private.status_code == 404
        visible = await client.get(f"/api/boards/captures/{capture_id}/captions", headers=auth_headers(member_user))
        assert visible.status_code == 200
        assert visible.json()[0]["text"] == "The launch is Friday"
    finally:
        async with async_session() as db:
            row = await db.get(CaptureRequest, capture_id)
            if row:
                await db.delete(row)
                await db.commit()
