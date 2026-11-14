from unittest.mock import patch

import pytest

from app.config import settings
from app.services.transcriber import _build_turns, _diagnostics, format_transcript


@pytest.fixture(autouse=True)
def deepgram_key():
    # The request-shape tests below mock the HTTP call; they only need the
    # "is transcription configured" guard to pass, not a real key.
    with patch.object(settings, "deepgram_api_key", "test-key"):
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


async def test_diarization_is_actually_requested():
    """Diarization must be requested with `diarize_model` alone. Deepgram
    rejects it alongside `diarize=true` (every transcription then fails), and
    `diarize=true` by itself collapses everyone into one speaker."""
    import httpx
    from unittest.mock import AsyncMock, patch

    from app.services import transcriber

    captured = {}

    async def fake_post(self, url, **kwargs):
        captured["params"] = kwargs.get("params")
        return httpx.Response(
            200,
            json={"results": {"channels": [{"alternatives": [{"words": []}]}]}, "metadata": {}},
            request=httpx.Request("POST", url),
        )

    with patch.object(httpx.AsyncClient, "post", fake_post):
        await transcriber.transcribe_audio_detailed(b"audio", "audio/webm", "en")

    assert ("diarize_model", "v2") in captured["params"]
    assert not any(key == "diarize" for key, _ in captured["params"])
    assert ("language", "en") in captured["params"]


async def test_hinglish_maps_to_deepgrams_multilingual_model():
    import httpx
    from unittest.mock import patch

    from app.services import transcriber

    captured = {}

    async def fake_post(self, url, **kwargs):
        captured["params"] = kwargs.get("params")
        return httpx.Response(
            200,
            json={"results": {"channels": [{"alternatives": [{"words": []}]}]}, "metadata": {}},
            request=httpx.Request("POST", url),
        )

    with patch.object(httpx.AsyncClient, "post", fake_post):
        await transcriber.transcribe_audio_detailed(b"audio", "audio/webm", "hinglish")

    assert ("language", "multi") in captured["params"]
