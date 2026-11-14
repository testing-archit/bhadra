import re
from collections import Counter
from typing import Any

import httpx

from app.config import settings
from app.services import usage_ledger, vocabulary_service

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
_LANGUAGE_MAP = {"en": "en", "hi": "hi", "hinglish": "multi", "auto": "multi"}
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
        {"speaker": 1, "start": 4.6, "end": 9.8, "text": "[Development fixture] Configure DEEPGRAM_API_KEY to transcribe real audio.", "confidence": None, "speaker_confidence": 0.0, "word_count": 8},
    ]
    return {
        "transcript": format_transcript(turns),
        "turns": turns,
        "diagnostics": _diagnostics(turns, None),
        "metadata": {"request_id": None, "duration": 9.8, "diarizer": "development-fixture"},
    }


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
    # Meetings run up to 2-3 hours; Deepgram's own processing time scales with
    # audio length, so a short timeout here risks aborting full-recording
    # diarization on exactly the longest (and most valuable) meetings.
    timeout_seconds: float = 1800.0,
    # Names of the people in this meeting (invitees, Meet speakers), listened
    # for ahead of everyone else at the company.
    people: list[str] | None = None,
) -> dict[str, Any]:
    if not settings.deepgram_api_key:
        if settings.fixture_mode_active:
            return _fixture_transcription()
        raise TranscriptionNotConfigured("Transcription is not set up: DEEPGRAM_API_KEY is missing")
    params: list[tuple[str, str]] = [
        ("model", "nova-3"),
        ("language", _LANGUAGE_MAP.get(meeting_language, "multi")),
        ("smart_format", "true"),
        ("punctuate", "true"),
        # `diarize_model` both turns diarization on and picks the diarizer.
        # Deepgram now rejects it combined with `diarize=true` (400
        # INVALID_QUERY_PARAMETER), and `diarize=true` on its own labels
        # every word as speaker 0 — checked against two-voice audio in
        # October 2026. Send exactly one: this one.
        ("diarize_model", "v2"),
        ("utterances", "true"),
        ("utt_split", "0.8"),
    ]
    # The meeting's people, then the names and terms the team taught Charcha
    # (Vocabulary) are listened for, and known mishearings fixed below.
    vocabulary = await vocabulary_service.active_vocabulary()
    for term in vocabulary_service.keyterms(settings.team_roster_list, vocabulary, people or ()):
        params.append(("keyterm", term))

    timeout = httpx.Timeout(timeout_seconds, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            DEEPGRAM_URL,
            params=params,
            headers={
                "Authorization": f"Token {settings.deepgram_api_key}",
                "Content-Type": mime_type,
            },
            content=audio_bytes,
        )

    if not response.is_success:
        raise RuntimeError(f"Deepgram error {response.status_code}: {response.text}")

    payload = response.json()
    results = payload.get("results") or {}
    alternatives = ((results.get("channels") or [{}])[0].get("alternatives") or [{}])
    words = alternatives[0].get("words") or []
    turns = _build_turns(words)
    if not turns:
        turns = [
            {
                "speaker": int(item.get("speaker", 0)),
                "start": round(float(item.get("start", 0.0)), 3),
                "end": round(float(item.get("end", 0.0)), 3),
                "text": item.get("transcript", ""),
                "confidence": round(float(item.get("confidence", 0.0)), 3),
                "speaker_confidence": 0.0,
                "word_count": len(item.get("transcript", "").split()),
            }
            for item in results.get("utterances") or []
            if item.get("transcript")
        ]

    await vocabulary_service.record_applied(vocabulary_service.apply_to_turns(turns, vocabulary.rules))
    diagnostics = _diagnostics(turns, expected_speakers)
    usage_ledger.record_audio("transcription", "deepgram", "nova-3", float((payload.get("metadata") or {}).get("duration") or 0))
    return {
        "transcript": format_transcript(turns),
        "turns": turns,
        "diagnostics": diagnostics,
        "metadata": {
            "request_id": (payload.get("metadata") or {}).get("request_id"),
            "duration": (payload.get("metadata") or {}).get("duration"),
            "diarizer": "v2",
        },
    }


async def transcribe_audio(
    audio_bytes: bytes, mime_type: str = "audio/webm", meeting_language: str = "hinglish"
) -> str:
    result = await transcribe_audio_detailed(audio_bytes, mime_type, meeting_language)
    return result["transcript"]
