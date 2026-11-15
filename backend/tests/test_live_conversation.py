import base64
from unittest.mock import patch

from app.config import settings
from app.services import live_conversation
from tests.conftest import auth_headers


async def test_live_turn_hears_answers_and_speaks(client, member_user, make_meeting):
    await make_meeting(member_user, "Sharma Kirana call", None)
    heard = {"turns": [{"text": "Sharma ji ka kitna udhaar baaki hai?"}]}
    with patch.object(settings, "gnani_api_key", "test"), patch(
        "app.services.transcriber.transcribe_audio_detailed", return_value=heard
    ), patch("app.services.gemini_service.generate_text", return_value=("**Sharma ji** ka 1,240 rupaye baaki hai.", {})) as gen, patch(
        "app.services.tts_service.synthesize", return_value=b"ID3speech"
    ):
        live_conversation._digests.clear()
        response = await client.post(
            "/api/live/turn",
            files={"audio": ("turn.webm", b"fake-audio", "audio/webm")},
            data={"history": '[{"role": "user", "content": "Namaste"}, {"role": "assistant", "content": "Namaste!"}]'},
            headers=auth_headers(member_user),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["transcript"] == "Sharma ji ka kitna udhaar baaki hai?"
    assert body["reply"] == "Sharma ji ka 1,240 rupaye baaki hai."
    assert base64.b64decode(body["audio"]) == b"ID3speech"
    prompt = gen.call_args.args[1]
    assert "Sharma Kirana call" in prompt and "Person: Namaste" in prompt


async def test_live_turn_with_silence_returns_nothing(client, member_user):
    with patch.object(settings, "gnani_api_key", "test"), patch(
        "app.services.transcriber.transcribe_audio_detailed", return_value={"turns": []}
    ):
        response = await client.post(
            "/api/live/turn", files={"audio": ("turn.webm", b"x", "audio/webm")}, headers=auth_headers(member_user)
        )
    assert response.json() == {"transcript": "", "reply": None, "audio": None}


async def test_live_turn_replies_in_the_detected_language(client, member_user):
    heard = {"turns": [{"text": "சர்மாவுக்கு எவ்வளவு பாக்கி?"}], "language": "ta-IN"}
    spoken = {}

    async def fake_synthesize(text, language=None):
        spoken["language"] = language
        return b"ID3"

    with patch.object(settings, "gnani_api_key", "test"), patch(
        "app.services.transcriber.transcribe_audio_detailed", return_value=heard
    ), patch("app.services.gemini_service.generate_text", return_value=("1,240 ரூபாய்.", {})) as gen, patch(
        "app.services.tts_service.synthesize", fake_synthesize
    ):
        response = await client.post(
            "/api/live/turn", files={"audio": ("turn.webm", b"x", "audio/webm")}, headers=auth_headers(member_user)
        )
    assert response.json()["language"] == "ta-IN"
    assert spoken["language"] == "ta-IN"
    assert "Reply in Tamil" in gen.call_args.args[1]


def test_tamil_uses_the_multilingual_voice():
    from app.services import tts_service
    assert tts_service.voice_for("ta-IN") == ("timbre-v3.0", "Shivani")
    assert tts_service.voice_for("hi-en") == ("timbre-v2.5", "Nalini")


def test_spoken_task_requests_are_recognised_but_questions_are_not():
    assert live_conversation.looks_like_task("Vedant ko login bug Friday tak fix karna hai, task bana do")
    assert live_conversation.looks_like_task("Add a task for Priya to publish the postmortem by Monday")
    assert live_conversation.looks_like_task("remind me to review the webhook PR")
    assert not live_conversation.looks_like_task("Which tasks are open for Vedant?")
    assert not live_conversation.looks_like_task("What did we decide about the rollout")


async def test_live_creates_a_real_task_from_a_spoken_request(client, member_user):
    from unittest.mock import AsyncMock
    heard = {"turns": [{"text": "Vedant ko login bug Friday tak fix karna hai, task bana do"}], "language": "hi-IN"}
    parsed = {"owner": "Vedant", "description": "Fix the login bug", "deadline": "Friday"}
    with patch.object(settings, "gnani_api_key", "test"), \
         patch("app.services.transcriber.transcribe_audio_detailed", return_value=heard), \
         patch("app.services.live_assist.parse_task", return_value=parsed), \
         patch("app.services.gemini_service.generate_text") as llm, \
         patch("app.services.tts_service.synthesize", new=AsyncMock(return_value=b"ID3")):
        response = await client.post("/api/live/turn", files={"audio": ("t.webm", b"x", "audio/webm")}, headers=auth_headers(member_user))
    body = response.json()
    assert body["reply"] == "Task bana diya: Fix the login bug, Vedant ke liye, Friday tak."
    assert body["task_added"]["description"] == "Fix the login bug"
    llm.assert_not_called()
    tasks = (await client.get("/api/tasks", headers=auth_headers(member_user))).json()
    created = [t for t in tasks if t["description"] == "Fix the login bug"]
    assert created and created[0]["origin"] == "live"
    await client.delete(f"/api/tasks/{created[0]['id']}", headers=auth_headers(member_user))
