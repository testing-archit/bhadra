from unittest.mock import AsyncMock, patch

import httpx
import numpy as np
import pytest

from app.config import settings
from app.services import scribe_service, transcriber, vocabulary_service, usage_ledger
from app.services.audio_preparation import wav_bytes


def test_scribe_word_timing_and_real_speaker_turns_are_preserved():
    payload = {"words": [
        {"type": "word", "text": "Do", "start": 0, "end": .2, "speaker_id": "speaker_0"},
        {"type": "word", "text": "not", "start": .2, "end": .4, "speaker_id": "speaker_0"},
        {"type": "audio_event", "text": "(noise)", "start": .4, "end": .5},
        {"type": "word", "text": "agreed", "start": 1, "end": 1.5, "speaker_id": "speaker_1"},
    ]}
    turns = scribe_service.turns(payload)
    assert [turn["text"] for turn in turns] == ["Do not", "agreed"]
    assert turns[0]["words"] == [[0, 200], [200, 400]]
    assert turns[0]["speaker_confidence"] == 0  # no fabricated speaker certainty


async def test_robust_uses_one_provider_accounts_usage_and_offsets_words():
    samples = (2000*np.sin(np.arange(30*8000)*.1)).astype("<i2")
    response = httpx.Response(200, json={"language_code": "en", "words": [
        {"type": "word", "text": "hello", "start": .1, "end": .3, "speaker_id": "s0"}]})
    with patch.object(settings, "eleven_labs_api_key", "test-eleven"), \
         patch.object(settings, "gnani_api_key", ""), \
         patch.object(vocabulary_service, "active_vocabulary", AsyncMock(return_value=vocabulary_service.Vocabulary())), \
         patch.object(vocabulary_service, "record_applied", AsyncMock()), \
         patch.object(httpx.AsyncClient, "post", AsyncMock(return_value=response)) as post, \
         patch.object(usage_ledger, "record_audio") as ledger:
        result = await transcriber.transcribe_audio_detailed(wav_bytes(samples, 8000), profile="robust")
    assert post.await_count == 2
    assert all(call.args[0] == "https://api.elevenlabs.io/v1/speech-to-text" for call in post.await_args_list)
    assert post.await_args.kwargs["data"]["model_id"] == "scribe_v3"
    assert "keyterms" not in post.await_args.kwargs["data"]
    assert result["turns"][1]["words"] == [[25100, 25300]]
    assert result["metadata"]["provider"] == "elevenlabs"
    assert ledger.call_args_list[0].args == ("transcription", "elevenlabs", "scribe_v3", 25)


async def test_missing_robust_key_is_explicit_and_does_not_silently_switch_provider():
    with patch.object(settings, "eleven_labs_api_key", ""), \
         patch.object(settings, "fixture_mode", False):
        with pytest.raises(transcriber.TranscriptionNotConfigured):
            await transcriber.transcribe_audio_detailed(b"audio", profile="robust")


async def test_scribe_auth_failure_has_no_retry_and_no_response_body_leak():
    with patch.object(httpx.AsyncClient, "post", AsyncMock(return_value=httpx.Response(401, text="private data"))) as post:
        async with httpx.AsyncClient() as client:
            with pytest.raises(RuntimeError, match="Scribe error 401") as error:
                await scribe_service.transcribe(client, ("a.wav", b"audio", "audio/wav"), "en", interactive=True)
    assert post.await_count == 1 and "private data" not in str(error.value)


def test_scribe_usage_price_is_overridable():
    with patch.object(settings, "ai_pricing_json", ""):
        assert usage_ledger.audio_price_per_minute("elevenlabs") == pytest.approx(.20/60)
    with patch.object(settings, "ai_pricing_json", '{"elevenlabs": 0.01}'):
        assert usage_ledger.audio_price_per_minute("elevenlabs") == .01
