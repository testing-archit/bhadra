from unittest.mock import patch

import httpx
import pytest

from app.config import settings
from app.services import tts_service


@pytest.fixture(autouse=True)
def speech_setup(tmp_path):
    with patch.object(settings, "gnani_api_key", "test-key"), patch.object(settings, "recordings_dir", str(tmp_path)):
        yield


def test_spoken_text_drops_markdown_and_citations():
    text = "### Executive overview\n- **Vedant** builds read-back by Friday [S3].\n- Use [WhatsApp](https://x.example) not SMS [1, 2]."
    assert tts_service.spoken_text(text) == "Executive overview. Vedant builds read-back by Friday. Use WhatsApp not SMS"


def test_spoken_text_cuts_long_answers_at_a_sentence():
    text = ("Yeh ek lamba jawab hai. " * 100).strip()
    spoken = tts_service.spoken_text(text)
    assert len(spoken) <= tts_service.MAX_SPOKEN_CHARS
    assert spoken.endswith(".")


async def test_synthesize_calls_timbre_once_then_uses_the_cache():
    calls = []

    async def fake_post(self, url, **kwargs):
        calls.append(kwargs["json"])
        return httpx.Response(200, content=b"ID3mp3", headers={"content-type": "audio/mpeg"}, request=httpx.Request("POST", url))

    with patch.object(httpx.AsyncClient, "post", fake_post):
        first = await tts_service.synthesize("Sharma ji ka udhaar baaki hai.")
        second = await tts_service.synthesize("Sharma ji ka udhaar baaki hai.")

    assert first == second == b"ID3mp3"
    assert len(calls) == 1
    assert calls[0]["model"] == "timbre-v2.5"
    assert calls[0]["language"] == "hi-en"
    assert calls[0]["audio_config"]["container"] == "mp3"


async def test_synthesize_rejects_bad_input_and_missing_key():
    with pytest.raises(ValueError):
        await tts_service.synthesize("   ")
    with pytest.raises(ValueError):
        await tts_service.synthesize("Hello", "xx-YY")
    with patch.object(settings, "gnani_api_key", ""), pytest.raises(tts_service.SpeechNotConfigured):
        await tts_service.synthesize("Hello")


async def test_timbre_errors_are_raised_not_cached():
    async def failing_post(self, url, **kwargs):
        return httpx.Response(500, json={"success": False, "message": "boom"}, request=httpx.Request("POST", url))

    with patch.object(httpx.AsyncClient, "post", failing_post), pytest.raises(RuntimeError):
        await tts_service.synthesize("Hello team")
