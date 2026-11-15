import asyncio
import json
import logging
import math
import re
from collections import Counter
from typing import Any

import httpx

from app.config import settings
from app.services import scribe_service, usage_ledger, vocabulary_service
from app.services.speech_admission import SpeechAdmission
from app.services.audio_preparation import enhanced_upload, prepare_audio

logger = logging.getLogger(__name__)

# Prisma v3.0 accepts recorded media through the Gnani REST endpoint. The
# language selector sends Hindi/English hints for Hinglish and Auto-LID
# when the source language is unknown.
# Prisma's Auto-LID code is "indic-auto"; a bare "auto" is rejected with
# INVALID_LANGUAGE_CODE.
_AUTO_LID = "indic-auto"
_LANGUAGE_MAP = {"en": "en-IN", "hi": "hi-IN", "hinglish": "hi-IN,en-IN", "auto": _AUTO_LID}

# The Gnani account allows one active request at a time (429 RATE_LIMITED
# otherwise), so every Prisma call in this process queues on one lock and a
# 429 from elsewhere (another process) is retried with a short back-off.
_RATE_LIMIT_RETRIES = 8
_prisma_lock: SpeechAdmission | None = None


def _lock() -> SpeechAdmission:
    global _prisma_lock
    if _prisma_lock is None:
        _prisma_lock = SpeechAdmission()
    return _prisma_lock


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
        number = float(value)
        return number if math.isfinite(number) else default
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
    interactive: bool = False,
    channel_mode: str = "preserve",
    profile: str | None = None,
) -> dict[str, Any]:
    profile = profile or settings.stt_profile
    if profile not in {"standard", "robust"}:
        raise ValueError("Unknown transcription profile")
    robust = profile == "robust"
    provider, model = ("elevenlabs", scribe_service.MODEL) if robust else ("gnani", settings.gnani_stt_model)
    if not (settings.eleven_labs_api_key if robust else settings.gnani_api_key):
        if settings.fixture_mode_active:
            return _fixture_transcription()
        raise TranscriptionNotConfigured("Transcription is not set up for the selected profile")
    # Prisma REST uses format/keyterms. httpx supplies the multipart boundary.
    vocabulary = await vocabulary_service.active_vocabulary()
    terms = vocabulary_service.keyterms(settings.team_roster_list, vocabulary, people or ())[:200]
    data = {
        "model": settings.gnani_stt_model,
        "format": settings.gnani_stt_mode,
        "language_code": _LANGUAGE_MAP.get(meeting_language, _AUTO_LID),
    }
    if terms:
        data["keyterms"] = json.dumps(terms, ensure_ascii=False)

    # Prisma's REST endpoint takes at most 30 s of audio per request
    # (MAX_AUDIO_DURATION_EXCEEDED). Submit lossless pieces serially, letting
    # live requests go ahead of the next batch piece.
    timeout = httpx.Timeout(min(timeout_seconds, 300.0), connect=20.0)

    async def transcribe_piece(client: httpx.AsyncClient, upload: tuple[str, bytes, str], request_data: dict) -> dict:
        for attempt in range(2 if interactive else _RATE_LIMIT_RETRIES):
            async with _lock().slot(interactive):
                response = await client.post(
                    settings.gnani_stt_url,
                    headers={"X-API-Key-ID": settings.gnani_api_key},
                    files={"audio_file": upload},
                    data=request_data,
                )
            if response.status_code == 429 or (response.status_code >= 500 and attempt < 1):
                await asyncio.sleep(min(1.0 + attempt, 5.0))
                continue
            break
        if not response.is_success:
            raise RuntimeError(f"Gnani Prisma error {response.status_code}")
        piece_payload = response.json()
        if piece_payload.get("success") is False:
            raise RuntimeError("Gnani Prisma rejected the audio")
        return piece_payload

    turns = []
    languages: Counter[str] = Counter()
    enhancement_counts: Counter[str] = Counter()
    next_speaker = 0
    previous: dict[int | None, str] = {}
    request_count = 0
    submitted_seconds = skipped_seconds = 0.0
    last_request_id = None
    async with prepare_audio(audio_bytes, channel_mode) as prepared, httpx.AsyncClient(timeout=timeout) as client:
        for piece in prepared.pieces():
            if piece.silent:
                skipped_seconds += piece.duration
                previous.pop(piece.channel, None)
                continue
            # Benchmark selected native PCM for Scribe; keep experimental
            # frontend denoisers confined to the standard profile.
            upload, enhancement = await enhanced_upload(piece, "off" if robust else settings.stt_enhancement, settings.stt_rnnoise_model_path)
            enhancement_counts[enhancement] += 1
            request_data = dict(data)
            if settings.stt_previous_context and previous.get(piece.channel):
                request_data["previous_text"] = previous[piece.channel][-600:]
            if robust:
                piece_payload = await scribe_service.transcribe(client, upload, meeting_language, interactive=interactive)
            else:
                piece_payload = await transcribe_piece(client, upload, request_data)
            # Account for each successful request even if a later chunk fails.
            usage_ledger.record_audio("transcription", provider, model, piece.duration)
            submitted_seconds += piece.duration
            request_count += 1
            piece_metadata = piece_payload.get("metadata") or {}
            last_request_id = piece_payload.get("request_id") or piece_metadata.get("request_id")
            language = piece_payload.get("detected_language_code") or piece_metadata.get("detected_language_code") or piece_payload.get("language_code")
            if language:
                languages[language] += 1
            piece_turns = scribe_service.turns(piece_payload) if robust else _turns_from_prisma(piece_payload)
            previous[piece.channel] = " ".join(turn["text"] for turn in piece_turns)[-600:]
            local_speakers = {speaker: next_speaker + index for index, speaker in enumerate(
                sorted({turn["speaker"] for turn in piece_turns}))}
            next_speaker += len(local_speakers)
            for turn in piece_turns:
                # Channel labels are stable only when the caller explicitly
                # declares one party per channel. Mono diarization is local.
                turn["speaker"] = piece.channel if piece.channel is not None else local_speakers[turn["speaker"]]
                if piece.channel is not None:
                    turn["channel"] = piece.channel
                start = min(piece.duration, max(0.0, turn["start"]))
                end = min(piece.duration, max(start, turn["end"] or piece.duration))
                turn["start"] = round(piece.offset + start, 3)
                turn["end"] = round(piece.offset + end, 3)
                if turn.get("words"):
                    turn["words"] = [[round(1000 * piece.offset) + min(round(piece.duration * 1000), max(0, value))
                                      for value in span] for span in turn["words"]]
                turns.append(turn)
        duration = prepared.duration
        audio_metadata = {"sample_rate": prepared.rate, "channels": prepared.channels,
                          "channel_mode": channel_mode, "encoding": "pcm_s16le",
                          "enhancement": dict(enhancement_counts), "requests": request_count,
                          "submitted_seconds": round(submitted_seconds, 3),
                          "digital_silence_skipped_seconds": round(skipped_seconds, 3)}
    turns.sort(key=lambda turn: (turn["start"], turn["speaker"]))

    await vocabulary_service.record_applied(vocabulary_service.apply_to_turns(turns, vocabulary.rules))
    diagnostics = _diagnostics(turns, expected_speakers)
    return {
        "transcript": format_transcript(turns),
        "turns": turns,
        "diagnostics": diagnostics,
        # e.g. "hi-IN", "ta-IN"; set when Prisma's Auto-LID ran.
        "language": languages.most_common(1)[0][0] if languages else None,
        "metadata": {
            "request_id": last_request_id,
            "duration": duration,
            "diarizer": model,
            "provider": provider,
            "profile": profile,
            "audio": audio_metadata,
        },
    }


async def transcribe_audio(
    audio_bytes: bytes, mime_type: str = "audio/webm", meeting_language: str = "hinglish"
) -> str:
    result = await transcribe_audio_detailed(audio_bytes, mime_type, meeting_language)
    return result["transcript"]
