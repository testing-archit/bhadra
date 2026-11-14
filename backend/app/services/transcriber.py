import asyncio
import json
import logging
import re
import subprocess
from collections import Counter
from typing import Any

import httpx

from app.config import settings
from app.services import usage_ledger, vocabulary_service

logger = logging.getLogger(__name__)

# Prisma v3.0 accepts recorded media through the Gnani REST endpoint. The
# product's language selector maps to BCP-47 where a person chooses a single
# language; Hinglish and Auto deliberately use Prisma's Auto-LID instead.
# Prisma's Auto-LID code is "indic-auto"; a bare "auto" is rejected with
# INVALID_LANGUAGE_CODE.
_AUTO_LID = "indic-auto"
_LANGUAGE_MAP = {"en": "en-IN", "hi": "hi-IN", "hinglish": _AUTO_LID, "auto": _AUTO_LID}

# Prisma accepts only these containers (UNSUPPORTED_AUDIO_FORMAT otherwise).
# Everything Charcha records is WebM (Opus), so it is repackaged as Ogg:
# the same Opus audio in a container Prisma takes, copied, not re-encoded.
_SUPPORTED_UPLOADS = {
    "audio/ogg": "ogg", "audio/opus": "ogg", "audio/mpeg": "mp3", "audio/mp3": "mp3",
    "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/flac": "flac",
    "audio/x-flac": "flac", "audio/aac": "aac", "audio/mp4": "m4a", "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
}
_CONVERT_TIMEOUT_SECONDS = 300


def _ffmpeg_to_ogg(audio_bytes: bytes, reencode: bool) -> bytes:
    codec = ["-c:a", "libopus", "-b:a", "48k", "-ac", "1"] if reencode else ["-c:a", "copy"]
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", "pipe:0", "-vn", *codec, "-f", "ogg", "pipe:1"],
        input=audio_bytes, capture_output=True, timeout=_CONVERT_TIMEOUT_SECONDS, check=True,
    )
    if not result.stdout:
        raise RuntimeError("ffmpeg produced no audio")
    return result.stdout


async def _prisma_upload(audio_bytes: bytes, mime_type: str) -> tuple[str, bytes, str]:
    """(filename, bytes, content type) in a container Prisma accepts. WebM and
    anything unknown become Ogg: a stream copy first (milliseconds, lossless),
    then a re-encode to Opus if the codec can't go into Ogg as-is. If ffmpeg
    can't read the audio at all, the original is sent and Prisma's own error
    explains the problem."""
    base = (mime_type or "").split(";")[0].strip().lower()
    extension = _SUPPORTED_UPLOADS.get(base)
    if extension:
        return f"meeting.{extension}", audio_bytes, base
    for reencode in (False, True):
        try:
            converted = await asyncio.to_thread(_ffmpeg_to_ogg, audio_bytes, reencode)
            return "meeting.ogg", converted, "audio/ogg"
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            logger.info("Converting %s audio to Ogg (reencode=%s) failed: %s", base or "unknown", reencode, error)
    logger.warning("Sending %s audio to Prisma unconverted", base or "unknown")
    return "meeting.webm", audio_bytes, mime_type or "audio/webm"
_LOW_SPEAKER_CONFIDENCE = 0.62


def _join_words(words: list[dict[str, Any]]) -> str:
    text = " ".join(str(word.get("punctuated_word") or word.get("word") or "") for word in words)
    return re.sub(r"\s+([,.;:!?])", r"\1", text).strip()


def _smooth_speaker_labels(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove isolated, low-confidence speaker flips without hiding real turns."""
    normalized = [dict(word) for word in words if word.get("word")]
    if len(normalized) < 3:
        return normalized

    runs: list[tuple[int, int, int]] = []
    start = 0
    for index in range(1, len(normalized) + 1):
        if index == len(normalized) or normalized[index].get("speaker") != normalized[start].get("speaker"):
            runs.append((start, index, int(normalized[start].get("speaker", 0))))
            start = index

    for run_index, (start, end, _) in enumerate(runs):
        if run_index == 0 or run_index == len(runs) - 1 or end - start > 2:
            continue
        previous_speaker = runs[run_index - 1][2]
        next_speaker = runs[run_index + 1][2]
        confidence = sum(float(word.get("speaker_confidence", 0.0)) for word in normalized[start:end]) / (end - start)
        if previous_speaker == next_speaker and confidence < 0.85:
            for word in normalized[start:end]:
                word["speaker"] = previous_speaker

    return normalized


def _build_turns(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    words = _smooth_speaker_labels(words)
    turns: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        word_confidence = sum(float(word.get("confidence", 0.0)) for word in current) / len(current)
        speaker_values = [float(word.get("speaker_confidence", 0.0)) for word in current]
        speaker_confidence = sum(speaker_values) / len(speaker_values) if speaker_values else 0.0
        turns.append(
            {
                "speaker": int(current[0].get("speaker", 0)),
                "start": round(float(current[0].get("start", 0.0)), 3),
                "end": round(float(current[-1].get("end", 0.0)), 3),
                "text": _join_words(current),
                "confidence": round(word_confidence, 3),
                "speaker_confidence": round(speaker_confidence, 3),
                "word_count": len(current),
                # [start_ms, end_ms] per word of `text` (one per space-separated
                # token), for word-by-word highlighting during playback.
                "words": [
                    [int(round(float(word.get("start", 0.0)) * 1000)), int(round(float(word.get("end", 0.0)) * 1000))]
                    for word in current
                ],
            }
        )

    for word in words:
        gap = float(word.get("start", 0.0)) - float(current[-1].get("end", 0.0)) if current else 0.0
        if current and (word.get("speaker") != current[-1].get("speaker") or gap > 1.4):
            flush()
            current = []
        current.append(word)
    flush()
    return [turn for turn in turns if turn["text"]]


def _diagnostics(turns: list[dict[str, Any]], expected_speakers: int | None) -> dict[str, Any]:
    speakers = sorted({turn["speaker"] for turn in turns})
    total_words = sum(turn["word_count"] for turn in turns)
    low_confidence_words = sum(
        turn["word_count"] for turn in turns if turn["speaker_confidence"] < _LOW_SPEAKER_CONFIDENCE
    )
    average = (
        sum(turn["speaker_confidence"] * turn["word_count"] for turn in turns) / total_words
        if total_words
        else 0.0
    )
    mismatch = expected_speakers is not None and expected_speakers > 0 and len(speakers) != expected_speakers
    low_share = low_confidence_words / total_words if total_words else 1.0
    quality = "review" if mismatch or average < 0.7 or low_share > 0.2 else "good"
    return {
        "quality": quality,
        "detected_speakers": len(speakers),
        "expected_speakers": expected_speakers,
        "average_speaker_confidence": round(average, 3),
        "low_confidence_share": round(low_share, 3),
        "turn_count": len(turns),
    }


class TranscriptionNotConfigured(RuntimeError):
    pass


def _fixture_transcription() -> dict[str, Any]:
    """DEVELOPMENT FIXTURE — never active when APP_ENV=production. The text
    says what it is so it can never be mistaken for a real transcript."""
    turns = [
        {"speaker": 0, "start": 0.0, "end": 4.2, "text": "[Development fixture] This is not a real transcription.", "confidence": None, "speaker_confidence": 0.0, "word_count": 8},
        {"speaker": 1, "start": 4.6, "end": 9.8, "text": "[Development fixture] Configure GNANI_API_KEY to transcribe real audio.", "confidence": None, "speaker_confidence": 0.0, "word_count": 8},
    ]
    return {
        "transcript": format_transcript(turns),
        "turns": turns,
        "diagnostics": _diagnostics(turns, None),
        "metadata": {"request_id": None, "duration": 9.8, "diarizer": "development-fixture"},
    }


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _turns_from_prisma(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise Prisma REST responses without tying the meeting pipeline to
    one response revision. The documented minimum response is `transcript`;
    when timestamped segments are present, keep them for playback/evidence.
    """
    raw_segments = payload.get("segments") or payload.get("utterances") or []
    if isinstance(payload.get("results"), dict):
        raw_segments = raw_segments or payload["results"].get("segments") or []
    turns: list[dict[str, Any]] = []
    if isinstance(raw_segments, list):
        for index, segment in enumerate(raw_segments):
            if not isinstance(segment, dict):
                continue
            text = str(segment.get("text") or segment.get("transcript") or "").strip()
            if not text:
                continue
            start = _number(segment.get("start", segment.get("start_time", 0)))
            end = _number(segment.get("end", segment.get("end_time", start)))
            speaker_value = segment.get("speaker", segment.get("speaker_id", index))
            try:
                speaker = int(str(speaker_value).replace("speaker_", ""))
            except ValueError:
                speaker = index
            turns.append(
                {
                    "speaker": speaker,
                    "start": round(start, 3),
                    "end": round(max(start, end), 3),
                    "text": text,
                    "confidence": _number(segment.get("confidence")),
                    "speaker_confidence": _number(segment.get("speaker_confidence", segment.get("confidence", 0.0))),
                    "word_count": len(text.split()),
                }
            )
    if turns:
        return turns
    transcript = str(payload.get("transcript") or (payload.get("results") or {}).get("transcript") or "").strip()
    if not transcript:
        return []
    duration = _number((payload.get("metadata") or {}).get("duration", payload.get("duration", 0)))
    return [{
        "speaker": 0, "start": 0.0, "end": duration, "text": transcript,
        "confidence": None, "speaker_confidence": 0.0, "word_count": len(transcript.split()),
    }]


def format_transcript(turns: list[dict[str, Any]], speaker_names: dict[str, str] | None = None) -> str:
    names = speaker_names or {}
    lines = []
    for turn in turns:
        label = names.get(str(turn["speaker"])) or f"Speaker {int(turn['speaker']) + 1}"
        lines.append(f"{label}: {turn['text']}")
    return "\n".join(lines)


async def transcribe_audio_detailed(
    audio_bytes: bytes,
    mime_type: str = "audio/webm",
    meeting_language: str = "hinglish",
    expected_speakers: int | None = None,
    # Meetings run up to 2-3 hours; batch transcription scales with audio
    # length, so a short timeout risks aborting the longest meetings.
    timeout_seconds: float = 1800.0,
    # Names of the people in this meeting (invitees, Meet speakers), listened
    # for ahead of everyone else at the company.
    people: list[str] | None = None,
) -> dict[str, Any]:
    if not settings.gnani_api_key:
        if settings.fixture_mode_active:
            return _fixture_transcription()
        raise TranscriptionNotConfigured("Transcription is not set up: GNANI_API_KEY is missing")
    # Prisma's REST API accepts multipart audio. `format` keeps compatibility
    # with the currently documented REST field; `mode` selects the v3 output
    # style. We intentionally do not set Content-Type: httpx supplies the
    # multipart boundary.
    vocabulary = await vocabulary_service.active_vocabulary()
    terms = vocabulary_service.keyterms(settings.team_roster_list, vocabulary, people or ())[:200]
    data = {
        "model": settings.gnani_stt_model,
        "mode": settings.gnani_stt_mode,
        "format": "transcribe",
        "language_code": _LANGUAGE_MAP.get(meeting_language, _AUTO_LID),
        "preferred_language": _LANGUAGE_MAP.get(meeting_language, _AUTO_LID),
    }
    if terms:
        data["key_terms"] = json.dumps(terms, ensure_ascii=False)

    upload = await _prisma_upload(audio_bytes, mime_type)
    timeout = httpx.Timeout(timeout_seconds, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            settings.gnani_stt_url,
            headers={"X-API-Key-ID": settings.gnani_api_key},
            files={"audio_file": upload},
            data=data,
        )

    if not response.is_success:
        raise RuntimeError(f"Gnani Prisma error {response.status_code}: {response.text}")

    payload = response.json()
    if payload.get("success") is False:
        raise RuntimeError(f"Gnani Prisma rejected the audio: {payload.get('message') or payload.get('error') or 'unknown error'}")
    turns = _turns_from_prisma(payload)

    await vocabulary_service.record_applied(vocabulary_service.apply_to_turns(turns, vocabulary.rules))
    diagnostics = _diagnostics(turns, expected_speakers)
    metadata = payload.get("metadata") or {}
    duration = _number(metadata.get("duration", payload.get("duration", 0)))
    usage_ledger.record_audio("transcription", "gnani", settings.gnani_stt_model, duration)
    return {
        "transcript": format_transcript(turns),
        "turns": turns,
        "diagnostics": diagnostics,
        "metadata": {
            "request_id": payload.get("request_id") or metadata.get("request_id"),
            "duration": duration,
            "diarizer": "prisma-v3.0",
        },
    }


async def transcribe_audio(
    audio_bytes: bytes, mime_type: str = "audio/webm", meeting_language: str = "hinglish"
) -> str:
    result = await transcribe_audio_detailed(audio_bytes, mime_type, meeting_language)
    return result["transcript"]
