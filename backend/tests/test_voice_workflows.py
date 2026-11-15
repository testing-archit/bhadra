"""Voice action receipts, original evidence and dated catch-up privacy."""
import asyncio
import datetime as dt
import importlib.util
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.database.db import async_session
from app.database.models import CaptureRequest, Decision, Meeting, MeetingInsight, MeetingTask, RecordingSession, TranscriptSegment
from app.services import call_translation, live_conversation, meeting_agent, voice_tasks, jira_service
from tests.conftest import auth_headers


def test_voice_intent_does_not_execute_negated_tasks():
    for command in ("Don't create a Jira ticket", "Do not create a task", "Never create a ticket", "Which Jira tickets are open?"):
        assert not live_conversation.looks_like_task(command)
    assert live_conversation.looks_like_task("Create a Jira ticket: fix the webhook retry bug, assign Vedant")


async def test_authenticated_voice_jira_receipt_and_replay(member_user):
    calls = []
    async def create_issue(db, task):
        if not task.jira_issue_key:
            calls.append(task.id)
            task.jira_issue_key = "ENG-42"
            task.jira_snapshot = {"assignee": "vedant-id"}
            await db.commit()
        return task.jira_issue_key
    async with async_session() as db:
        with patch("app.services.live_assist.parse_task", return_value={"owner": "Vedant", "description": "Fix the webhook retry bug", "deadline": ""}), patch("app.services.jira_service.create_issue", side_effect=create_issue), patch("app.services.jira_service.get_connection", return_value=SimpleNamespace(site_url="https://team.atlassian.net")):
            result, spoken = await voice_tasks.create(db, member_user, "Create a Jira ticket: fix retries, assign Vedant", b"recording-1")
            replay, _ = await voice_tasks.create(db, member_user, "Create a Jira ticket: fix retries, assign Vedant", b"recording-1")
    assert result["jira_issue_key"] == "ENG-42" and result["jira_url"] == "https://team.atlassian.net/browse/ENG-42"
    assert "Assigned to Vedant" in spoken
    assert replay["id"] == result["id"] and len(calls) == 1


async def test_failed_jira_keeps_task_and_does_not_retry_ambiguous_post(member_user):
    async with async_session() as db:
        with patch("app.services.live_assist.parse_task", return_value={"owner": "", "description": "Fix retries", "deadline": ""}), patch("app.services.jira_service.create_issue", side_effect=jira_service.JiraError("timeout")) as send:
            first, message = await voice_tasks.create(db, member_user, "Create a Jira ticket: fix retries", b"recording-2")
            second, replay = await voice_tasks.create(db, member_user, "Create a Jira ticket: fix retries", b"recording-2")
            saved = await db.get(MeetingTask, uuid.UUID(first["id"]))
    assert first["id"] == second["id"] and saved.description == "Fix retries"
    assert "couldn't confirm" in message and "Check" in replay and "Created Jira" not in message
    send.assert_awaited_once()


async def test_concurrent_voice_replays_do_not_duplicate_tasks(member_user):
    async def run():
        async with async_session() as db:
            return await voice_tasks.create(db, member_user, "Create a task: Fix retries", b"recording-concurrent")
    with patch("app.services.live_assist.parse_task", return_value={"owner": "", "description": "Concurrent retries", "deadline": ""}) as parse:
        first, second = await asyncio.gather(run(), run())
    assert first[0]["id"] == second[0]["id"]
    parse.assert_called_once()


async def test_shared_call_does_not_borrow_recorders_jira_authority():
    job = SimpleNamespace(payload={"command": "Create a Jira ticket: fix retries", "tool": "add_task"})
    plan = await meeting_agent.make_plan(job)
    assert plan[0]["tool"] == "clarify" and "/live" in plan[0]["instruction"]


async def test_latest_standup_respects_access_and_dates(client, member_user, other_member_user):
    async with async_session() as db:
        public = Meeting(user_id=member_user.id, title="pytest_standup_voice", template="standup", date=dt.datetime.now(dt.UTC)-dt.timedelta(days=1))
        private = Meeting(user_id=other_member_user.id, title="pytest_secret_standup", template="standup", date=dt.datetime.now(dt.UTC))
        db.add_all([public, private]); await db.flush()
        db.add_all([MeetingInsight(meeting_id=public.id, template_sections=[{"heading": "Plans", "items": [{"person": "Vedant", "text": "Fix retries"}]}]), MeetingInsight(meeting_id=private.id, template_sections=[{"heading": "Updates", "items": [{"person": "Secret", "text": "Private plans"}]}])])
        await db.commit()
    result = await client.get("/api/tts/standup", headers=auth_headers(member_user))
    body = result.json()["standup"]
    assert body["meeting_id"] == str(public.id)
    assert "Vedant: Fix retries" in body["text"] and "Plans stated in this stand-up" in body["text"]
    assert "Private plans" not in body["text"]


async def test_original_quote_checks_evidence_and_access(client, member_user, other_member_user, make_meeting, tmp_path):
    meeting = await make_meeting(member_user, "Quote test", None)
    private = await make_meeting(other_member_user, "Private source", None)
    async with async_session() as db:
        segment = TranscriptSegment(meeting_id=meeting.id, seq=1, speaker_key="0", speaker_label="Vedant", text="Use exponential retries", original_text="Exponential retries use karo", start_ms=100, end_ms=1100)
        outsider = TranscriptSegment(meeting_id=private.id, seq=1, speaker_key="1", text="Secret deal", original_text="Secret deal", start_ms=0, end_ms=1000)
        db.add_all([segment, outsider]); await db.flush()
        decision = Decision(meeting_id=meeting.id, decision="Use retries", evidence=[{"segment_id": str(segment.id), "verified": True, "excerpt": "exponential retries"}, {"segment_id": str(outsider.id), "verified": True, "excerpt": "Secret deal"}])
        recording = RecordingSession(user_id=member_user.id, meeting_id=meeting.id, title="Quote", status="processed")
        db.add_all([decision, recording]); await db.commit()
    with patch.object(settings, "recordings_dir", str(tmp_path)):
        from app.routes.recordings import _session_dir
        directory = _session_dir(recording.id); directory.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "libopus", str(directory / "recording.webm")], check=True)
        response = await client.get(f"/api/decisions/{decision.id}/source", headers=auth_headers(member_user))
        lines = response.json()["lines"]
        assert len(lines) == 1 and lines[0]["speaker"] == "Vedant" and lines[0]["audio_available"]
        assert lines[0]["original_text"] == "Exponential retries use karo"
        audio = await client.get(f"/api/decisions/{decision.id}/source/{segment.id}/audio", headers=auth_headers(member_user))
        assert audio.status_code == 200 and audio.headers["content-type"] == "audio/mpeg" and len(audio.content) > 100
        assert (await client.get(f"/api/decisions/{decision.id}/source", headers=auth_headers(other_member_user))).status_code == 404
        assert (await client.get(f"/api/decisions/{decision.id}/source/{outsider.id}/audio", headers=auth_headers(member_user))).status_code == 404
        async with async_session() as db:
            line = await db.get(TranscriptSegment, segment.id); line.text = "The plan was cancelled"; await db.commit()
        assert (await client.get(f"/api/decisions/{decision.id}/source", headers=auth_headers(member_user))).json()["lines"] == []


def running_class():
    spec = importlib.util.spec_from_file_location("bot_call_translation", Path(__file__).parents[1] / "bot/call_translation.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.RunningTranslations


async def test_running_translation_is_incremental_bounded_and_cancellable():
    state = running_class()()
    captions = [{"speaker": "Vedant", "text": "Retries fixed", "start": 2, "end": 5}]
    assert "shared meeting chat" in state.command("translate to Tamil", captions)
    assert state.command("what did we decide", captions) is None
    translate, send = AsyncMock(return_value="தமிழ் சுருக்கம்"), AsyncMock(return_value=True)
    await state.flush(captions, 20, translate, send, lambda: False)
    assert translate.call_args.args[0] == "ta-IN" and "Tamil" in send.call_args.args[0]
    state.last_poll = 0
    await state.flush(captions, 40, translate, send, lambda: False)
    translate.assert_awaited_once()
    state.command("translate to Hindi", captions); state.command("translate to English", captions)
    assert "three languages" in state.command("translate to Telugu", captions)
    state.command("stop translations", captions)
    assert not state.languages
    state.command("translate to Tamil", captions)
    async def stop_during_request(*args):
        state.command("stop translating", captions)
        return "must not post"
    await state.flush(captions, 20, stop_during_request, send, lambda: False)
    send.assert_awaited_once()


async def test_running_translation_does_not_read_paused_speech():
    state = running_class()(); state.command("translate to Tamil", [])
    translate, send = AsyncMock(), AsyncMock()
    await state.flush([{"text": "private", "end": 4}], 20, translate, send, lambda: True)
    translate.assert_not_called(); send.assert_not_called()


async def test_translation_endpoint_is_bot_only(client, member_user):
    async with async_session() as db:
        capture = CaptureRequest(user_id=member_user.id, platform="google_meet", meeting_url="https://meet.google.com/aaa-bbbb-ccc", meeting_code=uuid.uuid4().hex[:12], status="capturing", consent_acknowledged_at=dt.datetime.now(dt.UTC))
        db.add(capture); await db.commit()
    path = f"/api/bot/capture-requests/{capture.id}/translations"
    body = {"language": "ta-IN", "captions": [{"speaker": "Vedant", "text": "Fix retries", "start": 1}]}
    with patch.object(settings, "bot_api_secret", "test-bot"):
        assert (await client.post(path, json=body, headers=auth_headers(member_user))).status_code == 401
    with patch.object(settings, "bot_api_secret", "test-bot"), patch.object(call_translation, "summarize", return_value="சுருக்கம்") as translate:
        response = await client.post(path, json=body, headers={"Authorization": "Bot test-bot"})
        assert response.status_code == 200 and response.json()["text"] == "சுருக்கம்"
        assert translate.call_args.args[1] == "ta-IN"
        assert (await client.post(path, json={**body, "language": "xx"}, headers={"Authorization": "Bot test-bot"})).status_code == 422
        translate.assert_called_once()


async def test_live_route_returns_jira_receipt_without_a_fictional_llm_reply(client, member_user):
    heard = {"turns": [{"text": "Create a Jira ticket: fix webhook retries, assign Vedant"}], "language": "en-IN"}
    task = {"id": str(uuid.uuid4()), "description": "Fix webhook retries", "owner": "Vedant", "deadline": None, "jira_issue_key": "ENG-9", "jira_url": "https://team.atlassian.net/browse/ENG-9"}
    with patch.object(settings, "gnani_api_key", "test"), patch("app.services.transcriber.transcribe_audio_detailed", return_value=heard), patch("app.services.voice_tasks.create", return_value=(task, "Created Jira ticket ENG-9. Assigned to Vedant.")), patch("app.services.live_conversation.reply") as reply, patch("app.services.tts_service.synthesize", return_value=b"ID3"):
        response = await client.post("/api/live/turn", files={"audio": ("turn.webm", b"voice-jira", "audio/webm")}, headers=auth_headers(member_user))
    assert response.status_code == 200
    assert response.json()["task_added"]["jira_issue_key"] == "ENG-9"
    assert response.json()["reply"] == "Created Jira ticket ENG-9. Assigned to Vedant."
    reply.assert_not_called()


async def test_unparsed_voice_request_requires_review_before_jira(member_user):
    command = "Create a Jira ticket: fix retries, assign Vedant"
    with patch("app.services.live_assist.parse_task", return_value={"owner": "", "description": command, "deadline": ""}), patch("app.services.jira_service.create_issue") as send:
        async with async_session() as db:
            _, spoken = await voice_tasks.create(db, member_user, command, b"unparsed-voice")
    assert "review" in spoken
    send.assert_not_called()


def test_translation_uses_fast_model_and_billed_feature():
    with patch("app.services.gemini_service.generate_text", return_value=("தமிழ் சுருக்கம்", {})) as model:
        assert call_translation.summarize([{"text": "Retry using backoff", "speaker": "Vedant", "start": 2}], "ta-IN") == "தமிழ் சுருக்கம்"
    assert model.call_args.kwargs["feature"] == "live_translation"
    assert model.call_args.kwargs["model"] == settings.gemini_fast_model
    assert "Tamil" in model.call_args.args[0]


def test_jira_requires_an_explicit_external_ticket_instruction():
    for command in ("Create a Jira ticket: fix retries", "Please raise an issue in Jira for retries", "Make a task on Jira to fix retries", "Jira pe ticket bana do: fix retries"):
        assert voice_tasks.requests_jira(command), command
        assert live_conversation.looks_like_task(command), command
    for command in ("Add a task to review Jira permissions", "Create a reminder to check Jira", "Create a task: inspect the Jira webhook", "What Jira tickets are open?"):
        assert not voice_tasks.requests_jira(command), command


async def test_failing_translation_does_not_starve_other_languages():
    state = running_class()()
    captions = [{"speaker": "Vedant", "text": "Fix retries", "start": 1, "end": 3}]
    state.command("translate to Tamil", []); state.command("translate to Hindi", [])
    async def translate(language, captions):
        if language == "ta-IN":
            raise RuntimeError("temporary provider failure")
        return "हिन्दी सारांश"
    send = AsyncMock(return_value=True)
    await state.flush(captions, 20, translate, send, lambda: False)
    assert "Hindi" in send.call_args.args[0]
    assert state.languages["tamil"] == 0 and state.languages["hindi"] == 3
