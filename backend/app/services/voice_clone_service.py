"""Gnani voice cloning (Timbre VC): a person's own consented voice.

Embeddings come from a 5-30 s sample and are stored encrypted; the sample
itself is never kept. Speech is made with the `vachana-vc-v1` model."""
import asyncio
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.services import secret_box, tts_service, usage_ledger

VC_MODEL = "vachana-vc-v1"
MIN_SECONDS, MAX_SECONDS = 5.0, 30.0


class VoiceCloneError(Exception):
    """Something the person can act on (too short, too long, unclear)."""


def _api_base() -> str:
    parsed = urlparse(settings.gnani_tts_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _to_wav(audio: bytes) -> tuple[bytes, float]:
    """16 kHz mono WAV and its length; browsers record WebM/Opus or MP4."""
    with tempfile.TemporaryDirectory() as folder:
        source, target = Path(folder) / "sample", Path(folder) / "sample.wav"
        source.write_bytes(audio)
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(source), "-ac", "1", "-ar", "16000", str(target)],
            capture_output=True, timeout=30,
        )
        if result.returncode != 0 or not target.exists():
            raise VoiceCloneError("That recording couldn't be read. Try recording again.")
        wav = target.read_bytes()
    seconds = max(0.0, (len(wav) - 44) / (16000 * 2))
    return wav, seconds


async def create_embedding(audio: bytes) -> dict:
    if not settings.gnani_api_key:
        raise tts_service.SpeechNotConfigured("Speech is not set up: GNANI_API_KEY is missing")
    wav, seconds = await asyncio.to_thread(_to_wav, audio)
    if seconds < MIN_SECONDS:
        raise VoiceCloneError(f"That was {seconds:.0f} seconds. Speak for at least {MIN_SECONDS:.0f} seconds.")
    if seconds > MAX_SECONDS + 1:
        raise VoiceCloneError(f"Keep it under {MAX_SECONDS:.0f} seconds.")
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        response = await client.post(
            f"{_api_base()}/api/v1/tts/voice-clone/embeddings",
            headers={"X-API-Key-ID": settings.gnani_api_key},
            files={"audio_file": ("sample.wav", wav, "audio/wav")},
        )
    if not response.is_success:
        raise RuntimeError(f"Gnani voice clone error {response.status_code}: {response.text[:300]}")
    data = (response.json().get("data") or {}).get("voice_clone_embedding") or {}
    if not data.get("embedding"):
        raise RuntimeError("Gnani voice clone returned no embedding")
    return {"embedding": data["embedding"], "shape": data.get("shape") or [1, 768], "dtype": data.get("dtype") or "torch.bfloat16"}


def seal(embedding: str) -> str:
    return secret_box.encrypt(embedding)


async def speak(text: str, clone) -> bytes:
    """MP3 of `text` in the cloned voice (`clone` is a VoiceClone row)."""
    if not settings.gnani_api_key:
        raise tts_service.SpeechNotConfigured("Speech is not set up: GNANI_API_KEY is missing")
    embedding = secret_box.decrypt(clone.embedding_encrypted)
    if not embedding:
        raise VoiceCloneError("Your saved voice can't be read any more. Record it again.")
    text = tts_service.spoken_text(text)
    if not text:
        raise ValueError("Nothing to read aloud")
    pieces = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        for chunk in tts_service._chunks(text):
            response = await client.post(
                settings.gnani_tts_url,
                headers={"X-API-Key-ID": settings.gnani_api_key},
                json={
                    "text": chunk,
                    "model": VC_MODEL,
                    "audio_config": {"sample_rate": 24000, "num_channels": 1, "sample_width": 2,
                                     "encoding": "linear_pcm", "container": "mp3", "bitrate": "128k"},
                    "speaker_embedding": {"embedding": embedding, "shape": clone.shape, "dtype": clone.dtype},
                },
            )
            if not (response.is_success and response.headers.get("content-type", "").startswith("audio/")):
                raise RuntimeError(f"Gnani voice clone speech error {response.status_code}: {response.text[:300]}")
            pieces.append(response.content)
    audio = b"".join(pieces)
    usage_ledger.record_audio("speech", "gnani_tts", VC_MODEL, len(audio) * 8 / 128_000)
    return audio
