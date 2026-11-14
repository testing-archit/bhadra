from unittest.mock import patch

import pytest

from app.config import settings
from app.services.transcriber import _build_turns, _diagnostics, _turns_from_prisma, format_transcript


@pytest.fixture(autouse=True)
def gnani_key():
    # The request-shape tests below mock the HTTP call; they only need the
    # "is transcription configured" guard to pass, not a real key.
    with patch.object(settings, "gnani_api_key", "test-key"):
        yield


def _word(text, speaker, start, speaker_confidence=0.9):
    return {
        "word": text,
        "punctuated_word": text,
        "speaker": speaker,
        "start": start,
        "end": start + 0.2,
        "confidence": 0.95,
        "speaker_confidence": speaker_confidence,
    }


def test_isolated_low_confidence_speaker_flip_is_smoothed():
    words = [
        _word("This", 0, 0.0),
        _word("is", 0, 0.3),
        _word("actually", 1, 0.6, speaker_confidence=0.4),
        _word("one", 0, 0.9),
        _word("speaker.", 0, 1.2),
    ]
    turns = _build_turns(words)
    assert len(turns) == 1
    assert turns[0]["speaker"] == 0


def test_confident_multiword_speaker_change_is_preserved():
    words = [
        _word("First", 0, 0.0),
        _word("person.", 0, 0.3),
        _word("Second", 1, 0.8),
        _word("person", 1, 1.1),
        _word("answers.", 1, 1.4),
    ]
    turns = _build_turns(words)
    assert [turn["speaker"] for turn in turns] == [0, 1]


def test_diagnostics_flag_speaker_count_mismatch_and_names_format():
    turns = [
        {"speaker": 0, "start": 0, "end": 1, "text": "Hello.", "confidence": 0.9, "speaker_confidence": 0.9, "word_count": 1}
    ]
    diagnostics = _diagnostics(turns, expected_speakers=2)
    assert diagnostics["quality"] == "review"
    assert diagnostics["detected_speakers"] == 1
    assert format_transcript(turns, {"0": "Archit"}) == "Archit: Hello."


def test_prisma_timestamped_segments_are_preserved():
    turns = _turns_from_prisma({"segments": [{"speaker": "speaker_2", "start_time": 1.2, "end_time": 3.8, "text": "Namaste team."}]})
    assert turns == [{"speaker": 2, "start": 1.2, "end": 3.8, "text": "Namaste team.", "confidence": 0.0, "speaker_confidence": 0.0, "word_count": 2}]


async def test_prisma_request_uses_v3_mode_auto_language_and_keyterms():
    import httpx
    from unittest.mock import AsyncMock, patch

    from app.services import transcriber

    captured = {}

    async def fake_post(self, url, **kwargs):
        captured["data"] = kwargs.get("data")
        captured["headers"] = kwargs.get("headers")
        captured["files"] = kwargs.get("files")
        return httpx.Response(
            200,
            json={"success": True, "transcript": "Hello from Prisma.", "metadata": {"duration": 2}},
            request=httpx.Request("POST", url),
        )

    with patch.object(httpx.AsyncClient, "post", fake_post):
        await transcriber.transcribe_audio_detailed(b"audio", "audio/webm", "en", people=["Archit"])

    assert captured["headers"] == {"X-API-Key-ID": "test-key"}
    assert captured["data"]["model"] == "prisma-v3.0"
    assert captured["data"]["mode"] == "codemix"
    assert captured["data"]["language_code"] == "en-IN"
    assert captured["data"]["key_terms"] == '["Archit"]'
    assert "audio_file" in captured["files"]


async def test_hinglish_uses_prismas_auto_lid():
    import httpx
    from unittest.mock import patch

    from app.services import transcriber

    captured = {}

    async def fake_post(self, url, **kwargs):
        captured["data"] = kwargs.get("data")
        return httpx.Response(
            200,
            json={"success": True, "transcript": "Namaste team.", "metadata": {}},
            request=httpx.Request("POST", url),
        )

    with patch.object(httpx.AsyncClient, "post", fake_post):
        await transcriber.transcribe_audio_detailed(b"audio", "audio/webm", "hinglish")

    assert captured["data"]["language_code"] == "auto"
