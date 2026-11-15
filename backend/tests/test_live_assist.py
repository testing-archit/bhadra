from unittest.mock import patch

from app.config import settings
from app.services import live_assist

BOT_SECRET = "pytest-live-secret"
BOT = {"Authorization": f"Bot {BOT_SECRET}"}

CAPTIONS = [
    {"speaker": "Archit", "text": "Vedant, Friday tak read-back feature bana dena.", "start": 12.0},
    {"speaker": "Vedant", "text": "Haan, ho jayega.", "start": 75.5},
]


def test_transcript_is_timestamped_and_named():
    assert live_assist.format_transcript(CAPTIONS) == (
        "[00:12] Archit: Vedant, Friday tak read-back feature bana dena.\n[01:15] Vedant: Haan, ho jayega."
    )


def test_answers_are_plain_text_and_never_start_with_charcha():
    assert live_assist._clean("**Wilco:** ## Vedant builds it by Friday.") == "Vedant builds it by Friday."
    assert live_assist._clean("Charcha: Vedant builds it by Friday.") == "Vedant builds it by Friday."


def test_no_captions_yet_answers_without_calling_gemini():
    with patch("app.services.gemini_service.generate_text") as generate:
        assert "haven't heard enough" in live_assist.answer("what did we decide?", [])
    generate.assert_not_called()


async def test_live_answer_route_needs_the_bot_secret_and_uses_only_the_call(client):
    with patch.object(settings, "bot_api_secret", BOT_SECRET):
        await _ask_route(client)


async def _ask_route(client):
    unauthorized = await client.post("/api/bot/live-answer", json={"question": "recap"})
    assert unauthorized.status_code in (401, 403)
    with patch.object(settings, "gemini_api_key", "test"), patch(
        "app.services.gemini_service.generate_text", return_value=("- Vedant: read-back by Friday", {})
    ) as generate:
        response = await client.post("/api/bot/live-answer", headers=BOT, json={"question": "recap", "captions": CAPTIONS})
    assert response.status_code == 200
    assert response.json()["answer"] == "- Vedant: read-back by Friday"
    prompt = generate.call_args.args[1]
    assert "Friday tak read-back" in prompt and "Question: recap" in prompt and "speakers heard: Archit, Vedant" in prompt


def test_task_parsing_falls_back_to_the_typed_text_without_ai():
    with patch.object(settings, "gemini_api_key", ""):
        task = live_assist.parse_task("Vedant to send the invoice by Friday")
    assert task == {"owner": "", "description": "Vedant to send the invoice by Friday", "deadline": ""}
    assert live_assist.task_confirmation(task).startswith("Added: Vedant to send the invoice")


def test_task_parsing_reads_owner_and_deadline():
    reply = '{"owner": "Vedant", "description": "Send the invoice", "deadline": "Friday"}'
    with patch.object(settings, "gemini_api_key", "test"), patch("app.services.gemini_service.generate_text", return_value=(reply, {})):
        task = live_assist.parse_task("Vedant to send the invoice by Friday")
    assert task == {"owner": "Vedant", "description": "Send the invoice", "deadline": "Friday"}
    assert live_assist.task_confirmation(task) == "Added for Vedant: Send the invoice (by Friday). It'll be in the notes as a task."


async def test_live_tasks_are_held_then_created_on_the_meeting(client, member_user, make_meeting):
    import datetime
    import uuid

    from sqlalchemy import select

    from app.database.db import async_session
    from app.database.models import CaptureRequest, MeetingTask
    from app.routes.bot import _attach_live_tasks

    async with async_session() as db:
        capture = CaptureRequest(
            user_id=member_user.id, platform="google_meet", meeting_url=f"https://meet.google.com/{uuid.uuid4().hex[:3]}-test-abc",
            meeting_code=f"live-{uuid.uuid4().hex[:8]}", consent_acknowledged_at=datetime.datetime.now(datetime.UTC),
        )
        db.add(capture)
        await db.commit()
        capture_id = capture.id
    try:
        with patch.object(settings, "bot_api_secret", BOT_SECRET), patch.object(settings, "gemini_api_key", ""):
            response = await client.post("/api/bot/live-task", headers=BOT, json={"capture_request_id": str(capture_id), "text": "Priya to call the supplier"})
        assert response.status_code == 200
        assert response.json()["reply"].startswith("Added: Priya to call the supplier")

        meeting = await make_meeting(member_user, "Supplier sync", None)
        async with async_session() as db:
            capture = await db.get(CaptureRequest, capture_id)
            await _attach_live_tasks(db, capture, meeting.id)
            await db.commit()
            tasks = (await db.scalars(select(MeetingTask).where(MeetingTask.meeting_id == meeting.id))).all()
            assert [(t.description, t.origin) for t in tasks] == [("Priya to call the supplier", "live")]
            assert (await db.get(CaptureRequest, capture_id)).live_tasks is None
    finally:
        async with async_session() as db:
            await db.delete(await db.get(CaptureRequest, capture_id))
            await db.commit()


async def test_bot_speak_returns_timbre_audio(client):
    async def fake_synthesize(text, language=None):
        return b"ID3audio"

    with patch.object(settings, "bot_api_secret", BOT_SECRET), patch("app.services.tts_service.synthesize", fake_synthesize):
        response = await client.post("/api/bot/speak", headers=BOT, json={"text": "Vedant sends the invoice by Friday."})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"ID3audio"


def test_interactive_meeting_tools_use_the_fast_model():
    with patch.object(settings, "gemini_api_key", "test"), patch.object(settings, "gemini_fast_model", "test-fast"), patch(
        "app.services.gemini_service.generate_text", return_value=("Vedant ships by Friday.", {})
    ) as generate:
        live_assist.answer("who ships?", CAPTIONS, timeout_seconds=7)
        assert generate.call_args.kwargs["model"] == "test-fast"
        assert generate.call_args.kwargs["timeout_seconds"] == 7
        assert generate.call_args.kwargs["thinking_budget"] == 0
        live_assist.parse_task("Vedant ships Friday", timeout_seconds=7)
        assert generate.call_args.kwargs["model"] == "test-fast"
        assert generate.call_args.kwargs["timeout_seconds"] == 7
