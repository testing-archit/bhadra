"""Opt-in Scribe v3 recognition. No automatic paid second opinion."""
import asyncio
import math

import httpx

from app.config import settings
from app.services.speech_admission import SpeechAdmission

MODEL = "scribe_v3"
_admission = SpeechAdmission()


async def transcribe(client: httpx.AsyncClient, upload, language: str, *, interactive: bool):
    data = {"model_id": MODEL, "diarize": "true", "tag_audio_events": "false", "numbers_format": "words"}
    if language in {"en", "hi"}:
        data["language_code"] = language
    # Automatic multilingual recognition for Hinglish. Do not send keyterm
    # prompting by default: it incurs a separate provider surcharge.
    attempts = 2 if interactive else 4
    for attempt in range(attempts):
        async with _admission.slot(interactive):
            response = await client.post("https://api.elevenlabs.io/v1/speech-to-text",
                headers={"xi-api-key": settings.eleven_labs_api_key},
                files={"file": upload}, data=data)
        if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < attempts:
            await asyncio.sleep(min(2 ** attempt, 4))
            continue
        if not response.is_success:
            raise RuntimeError(f"ElevenLabs Scribe error {response.status_code}")
        return response.json()


def turns(payload):
    """Keep genuine word timing and speaker IDs; confidence is not invented."""
    result, labels = [], {}
    for word in payload.get("words") or []:
        if word.get("type") != "word" or not str(word.get("text") or "").strip():
            continue
        try:
            start, end = float(word["start"]), float(word["end"])
        except (KeyError, ValueError, TypeError):
            continue
        if not math.isfinite(start) or not math.isfinite(end):
            continue
        start, end = max(0, start), max(0, start, end)
        label = word.get("speaker_id") or "unknown"
        speaker = labels.setdefault(label, len(labels))
        text = str(word["text"]).strip()
        if result and result[-1]["speaker"] == speaker and start - result[-1]["end"] <= 1.4:
            result[-1]["text"] += " " + text
            result[-1]["end"] = end
            result[-1]["word_count"] += len(text.split())
            result[-1]["words"].extend([[round(start*1000), round(end*1000)]] * len(text.split()))
        else:
            result.append({"speaker": speaker, "start": start, "end": end, "text": text,
                           "word_count": len(text.split()), "confidence": None, "speaker_confidence": 0.0,
                           "words": [[round(start*1000), round(end*1000)]] * len(text.split())})
    if not result and str(payload.get("text") or "").strip():
        text = str(payload["text"]).strip()
        result.append({"speaker": 0, "start": 0.0, "end": 0.0, "text": text,
                       "word_count": len(text.split()), "confidence": None, "speaker_confidence": 0.0})
    return result
