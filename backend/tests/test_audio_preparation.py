import asyncio
import io
import shutil
import subprocess
import wave
from unittest.mock import AsyncMock, patch

import httpx
import numpy as np
import pytest

from app.config import settings
from app.services import transcriber, vocabulary_service
from app.services.audio_preparation import AudioPiece, InvalidAudio, cut_frame, enhanced_upload, prepare_audio, wav_bytes

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")


def signal(seconds=1, rate=8000):
    return (3000 * np.sin(2 * np.pi * 317 * np.arange(int(seconds * rate)) / rate)).astype("<i2")


@pytest.mark.parametrize("codec", ["pcm_mulaw", "pcm_alaw", "pcm_s16le"])
async def test_telephony_decodes_at_native_rate_without_lossy_reencoding(tmp_path, codec):
    original = tmp_path / "original.wav"
    encoded = tmp_path / "telephone.wav"
    original.write_bytes(wav_bytes(signal(29), 8000))
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(original), "-c:a", codec, str(encoded)], check=True)
    async with prepare_audio(encoded.read_bytes()) as audio:
        assert audio.rate == 8000 and audio.channels == 1
        pieces = list(audio.pieces())
        assert sum(len(piece.samples) for piece in pieces) == 29 * 8000
        assert max(piece.duration for piece in pieces) <= 28
        assert [piece.offset for piece in pieces] == [0, 25]
        with wave.open(io.BytesIO(pieces[0].upload()[1]), "rb") as wav:
            assert wav.getframerate() == 8000 and wav.getsampwidth() == 2
        if codec == "pcm_s16le":
            np.testing.assert_array_equal(np.concatenate([p.samples[:, 0] for p in pieces]), signal(29))
    assert not audio.path.exists()


async def test_opposite_phase_channels_survive_and_can_be_separated():
    stereo = np.column_stack([signal(30), -signal(30)])
    async with prepare_audio(wav_bytes(stereo, 8000), "separate") as audio:
        pieces = list(audio.pieces())
    assert [p.channel for p in pieces] == [0, 1, 0, 1]
    np.testing.assert_array_equal(np.concatenate([p.samples for p in pieces if p.channel == 0]), stereo[:, 0])
    assert all(not p.silent for p in pieces)


def test_quiet_boundary_preserves_all_samples_and_weak_speech():
    x = signal(29)
    x[24 * 8000:24 * 8000 + 4000] = 0
    cut = cut_frame(x, 8000)
    assert 24.1 <= cut / 8000 <= 24.4
    weak = np.full(8000, 1, dtype="<i2")
    assert not AudioPiece(0, 1, None, weak, 8000).silent


async def test_malformed_audio_never_reaches_provider():
    with pytest.raises(InvalidAudio):
        async with prepare_audio(b"not a recording"):
            pytest.fail("invalid input accepted")


async def test_spectral_enhancer_keeps_layout_and_duration():
    piece = AudioPiece(0, 1, 0, signal(), 8000)
    upload, applied = await enhanced_upload(piece, "spectral")
    assert applied == "spectral"
    with wave.open(io.BytesIO(upload[1]), "rb") as wav:
        assert (wav.getframerate(), wav.getnframes(), wav.getnchannels()) == (8000, 8000, 1)


async def test_missing_neural_model_falls_back_without_losing_audio():
    piece = AudioPiece(0, 1, 0, signal(), 8000)
    upload, applied = await enhanced_upload(piece, "rnnoise", "/missing/model.rnnn")
    assert applied == "fallback" and upload == piece.upload()


async def test_cancellation_kills_and_reaps_ffmpeg():
    from app.services.audio_preparation import _ffmpeg
    process = AsyncMock()
    process.returncode = None
    process.communicate.side_effect = asyncio.CancelledError
    with patch("asyncio.create_subprocess_exec", return_value=process):
        # kill is synchronous on the actual Process.
        from unittest.mock import Mock
        process.kill = Mock()
        with pytest.raises(asyncio.CancelledError):
            await _ffmpeg([])
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()


@pytest.fixture
def isolated_stt():
    with patch.object(settings, "gnani_api_key", "test"), \
         patch.object(settings, "stt_enhancement", "off"), \
         patch.object(vocabulary_service, "active_vocabulary", AsyncMock(return_value=vocabulary_service.Vocabulary())), \
         patch.object(vocabulary_service, "record_applied", AsyncMock()), \
         patch.object(transcriber.usage_ledger, "record_audio") as ledger:
        yield ledger


async def test_silence_skips_asr_and_empty_response_has_measured_duration(isolated_stt):
    with patch.object(httpx.AsyncClient, "post", AsyncMock()) as post:
        result = await transcriber.transcribe_audio_detailed(wav_bytes(np.zeros(8000, dtype="<i2"), 8000))
    post.assert_not_awaited()
    isolated_stt.assert_not_called()
    assert not result["turns"]
    assert result["metadata"]["duration"] == 1
    assert result["metadata"]["audio"]["digital_silence_skipped_seconds"] == 1


async def test_separate_channels_keep_identity_context_and_timestamps(isolated_stt):
    requests = []
    async def fake_post(self, url, **kwargs):
        requests.append(kwargs["data"])
        return httpx.Response(200, json={"transcript": f"part {len(requests)}"}, request=httpx.Request("POST", url))
    with patch.object(httpx.AsyncClient, "post", fake_post):
        result = await transcriber.transcribe_audio_detailed(
            wav_bytes(np.column_stack([signal(30), -signal(30)]), 8000), channel_mode="separate")
    assert [t["speaker"] for t in result["turns"]] == [0, 1, 0, 1]
    assert [t["start"] for t in result["turns"]] == [0, 0, 25, 25]
    assert [t["end"] for t in result["turns"]] == [25, 25, 30, 30]
    assert requests[2]["previous_text"] == "part 1"
    assert requests[3]["previous_text"] == "part 2"
    assert result["metadata"]["duration"] == 30
    assert result["metadata"]["audio"]["submitted_seconds"] == 60
    assert isolated_stt.call_count == 4


async def test_successful_chunk_is_billed_even_if_later_request_fails(isolated_stt):
    responses = [httpx.Response(200, json={"transcript": "hello"}), httpx.Response(400, text="private transcript")]
    with patch.object(httpx.AsyncClient, "post", AsyncMock(side_effect=responses)):
        with pytest.raises(RuntimeError, match="Gnani Prisma error 400") as error:
            await transcriber.transcribe_audio_detailed(wav_bytes(signal(30), 8000))
    assert "private" not in str(error.value)
    isolated_stt.assert_called_once_with("transcription", "gnani", settings.gnani_stt_model, 25)


async def test_provider_timestamps_are_clamped_to_actual_clip(isolated_stt):
    response = httpx.Response(200, json={"segments": [{"text": "hello", "start": -1, "end": 100}]})
    with patch.object(httpx.AsyncClient, "post", AsyncMock(return_value=response)):
        result = await transcriber.transcribe_audio_detailed(wav_bytes(signal(), 8000))
    assert result["turns"][0]["start"] == 0 and result["turns"][0]["end"] == 1
