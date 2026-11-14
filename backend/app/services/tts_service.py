"""Speech for Charcha's answers and summaries, through Gnani Timbre.

One REST call per text returns MP3 bytes. Results are cached on disk by a
hash of everything that shapes the audio, so replaying an answer or a
summary costs nothing.
"""
import hashlib
import logging
import re
from pathlib import Path

import httpx

from app.config import settings
from app.services import usage_ledger

logger = logging.getLogger(__name__)

# Timbre returns a generic 500 for overlong text, and nobody listens to a
# five-minute answer: speak the opening, cut at a sentence boundary.
MAX_SPOKEN_CHARS = 1200
SUPPORTED_LANGUAGES = {"auto", "hi-en", "hi-IN", "en-IN", "ta-IN", "te-IN", "kn-IN", "ml-IN", "mr-IN", "pa-IN", "bn-IN", "gu-IN"}
_MP3_BITRATE_BPS = 64_000


class SpeechNotConfigured(RuntimeError):
    pass


def spoken_text(text: str) -> str:
    """Markdown and citations read aloud sound like noise; keep the words."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links → their label
    text = re.sub(r"\s*\[(?:S?\d+(?:[,\s]+S?\d+)*)\]", "", text)  # [S3], [1, 2] citations
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)  # headings
    text = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", text, flags=re.M)  # list markers
    text = re.sub(r"[*_`>|~]+", "", text)
    text = re.sub(r"\s*\n+\s*", ". ", text)
    text = re.sub(r"(?:\.\s*){2,}", ". ", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" .")
    if len(text) > MAX_SPOKEN_CHARS:
        cut = text[:MAX_SPOKEN_CHARS]
        boundary = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "), cut.rfind("। "))
        text = cut[: boundary + 1] if boundary > MAX_SPOKEN_CHARS // 3 else cut
    return text.strip()


def _cache_path(text: str, language: str, model: str, voice: str) -> Path:
    key = "|".join([model, voice, language, text])
    digest = hashlib.sha256(key.encode()).hexdigest()
    return Path(settings.recordings_dir).resolve() / "tts_cache" / digest[:2] / f"{digest}.mp3"


def voice_for(language: str) -> tuple[str, str]:
    """(model, voice) for a language: the fast Hinglish/Hindi/English voice,
    or Timbre v3.0, whose voices speak every supported Indian language."""
    if language in {"hi-en", "hi-IN", "en-IN", "auto"}:
        return settings.gnani_tts_model, settings.gnani_tts_voice
    return settings.gnani_tts_multilingual_model, settings.gnani_tts_multilingual_voice


async def synthesize(text: str, language: str | None = None) -> bytes:
    """MP3 audio of `text` spoken by Timbre. Raises ValueError for empty or
    unsupported input, SpeechNotConfigured without a Gnani key."""
    if not settings.gnani_api_key:
        raise SpeechNotConfigured("Speech is not set up: GNANI_API_KEY is missing")
    language = language or settings.gnani_tts_language
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported speech language: {language}")
    text = spoken_text(text)
    if not text:
        raise ValueError("Nothing to read aloud")

    model, voice = voice_for(language)
    path = _cache_path(text, language, model, voice)
    try:
        if path.is_file():
            return path.read_bytes()
    except OSError:
        pass

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        response = await client.post(
            settings.gnani_tts_url,
            headers={"X-API-Key-ID": settings.gnani_api_key},
            json={
                "text": text,
                "model": model,
                "voice": voice,
                "language": language,
                "audio_config": {"container": "mp3", "sample_rate": 24000, "bitrate": "64k"},
            },
        )
    if not response.is_success or not response.headers.get("content-type", "").startswith("audio/"):
        raise RuntimeError(f"Gnani Timbre error {response.status_code}: {response.text[:300]}")
    audio = response.content

    # Timbre is billed by the request, not the second; the ledger records
    # the spoken length so Admin → AI spend shows how much was read aloud.
    usage_ledger.record_audio("speech", "gnani_tts", model, len(audio) * 8 / _MP3_BITRATE_BPS)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
    except OSError:
        logger.warning("Could not cache speech at %s", path)
    return audio
