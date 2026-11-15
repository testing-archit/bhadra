"""Meeting notes read aloud in the listener's language: Gemini translates,
Gnani Timbre speaks, and the response carries the text that was read."""
import base64
from unittest.mock import AsyncMock, patch

from app.routes import tts as tts_route
from tests.conftest import auth_headers


async def test_summary_is_translated_then_spoken_in_tamil(client, member_user):
    tts_route._translations.clear()
    with patch("app.services.gemini_service.generate_text", return_value=("விலை மாறாது.", {})) as translate, \
         patch("app.services.tts_service.synthesize", new=AsyncMock(return_value=b"ID3audio")) as speak:
        response = await client.post("/api/tts/translated", headers=auth_headers(member_user),
                                     json={"text": "Pricing stays the same.", "language": "ta-IN"})
        again = await client.post("/api/tts/translated", headers=auth_headers(member_user),
                                  json={"text": "Pricing stays the same.", "language": "ta-IN"})
    assert response.status_code == 200 and again.status_code == 200
    body = response.json()
    assert body["text"] == "விலை மாறாது." and body["language"] == "ta-IN"
    assert base64.b64decode(body["audio"]) == b"ID3audio"
    assert "Tamil" in translate.call_args.args[0]
    assert translate.call_count == 1  # the second request reuses the translation
    speak.assert_awaited_with("விலை மாறாது.", "ta-IN")


async def test_english_notes_in_english_are_not_translated(client, member_user):
    with patch("app.services.gemini_service.generate_text") as translate, \
         patch("app.services.tts_service.synthesize", new=AsyncMock(return_value=b"ID3")):
        response = await client.post("/api/tts/translated", headers=auth_headers(member_user),
                                     json={"text": "Ship on Friday.", "language": "en-IN"})
    assert response.status_code == 200 and response.json()["text"] == "Ship on Friday."
    translate.assert_not_called()


async def test_unknown_language_is_refused(client, member_user):
    response = await client.post("/api/tts/translated", headers=auth_headers(member_user),
                                 json={"text": "Ship on Friday.", "language": "xx-XX"})
    assert response.status_code == 422


async def test_translation_is_returned_even_when_speech_fails(client, member_user):
    tts_route._translations.clear()
    with patch("app.services.gemini_service.generate_text", return_value=("किंमत बदलणार नाही.", {})), \
         patch("app.services.tts_service.synthesize", new=AsyncMock(side_effect=RuntimeError("Timbre 500"))):
        response = await client.post("/api/tts/translated", headers=auth_headers(member_user),
                                     json={"text": "Pricing stays the same.", "language": "mr-IN"})
    body = response.json()
    assert response.status_code == 200 and body["text"] == "किंमत बदलणार नाही." and body["audio"] is None
    assert body["speech_error"]
