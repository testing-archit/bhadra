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
