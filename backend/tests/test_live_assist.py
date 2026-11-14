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
    assert live_assist._clean("**Charcha:** ## Vedant builds it by Friday.") == "Vedant builds it by Friday."


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
    assert "Friday tak read-back" in prompt and "Question from the chat: recap" in prompt
