"""Transcript segments: parsing, persistence, rendering and export.

Once a meeting has `TranscriptSegment` rows they are the authoritative
transcript. `Meeting.transcript` (the flat "Speaker: text" string the rest of
the app — search, PDF export, Qdrant — already reads) is re-rendered from them
after every change, so nothing downstream has to know segments exist.

Timestamps, speaker identities and confidences are only ever ones a source
actually supplied: a plain pasted transcript gets segments with no times and
no confidence, never invented ones.
"""

import json
import re
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Meeting, TranscriptSegment

MAX_SPEAKER_CHARS = 60
MAX_SPEAKER_WORDS = 5
# Labels that look like "Name:" but are almost always prose.
_NOT_SPEAKERS = {"note", "notes", "agenda", "action", "action item", "todo", "update", "summary", "re", "subject", "http", "https"}
_GENERIC_SPEAKER_RE = re.compile(r"^speaker\s*(\d+)$", re.IGNORECASE)
_CLOCK = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"
_LEADING_TIME_RE = re.compile(rf"^\s*[\[(]?\s*({_CLOCK})\s*[\])]?\s*[-–—|]?\s*")
_CUE_TIMING_RE = re.compile(rf"^\s*({_CLOCK})\s*-->\s*({_CLOCK})")
_HAS_CUES_RE = re.compile(rf"^\s*{_CLOCK}\s*-->\s*{_CLOCK}", re.MULTILINE)
_VTT_VOICE_RE = re.compile(r"^<v(?:\.[^ >]*)?\s+([^>]+)>(.*?)(?:</v>)?$", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_SPEAKER_LINE_RE = re.compile(r"^(?:\[([^\]]{1,60})\]|([^:\n]{1,60})):\s*(.+)$", re.DOTALL)


# --- labels ------------------------------------------------------------------


def generic_label(speaker_key: str) -> str:
    if speaker_key.isdigit():
        return f"Speaker {int(speaker_key) + 1}"
    return speaker_key or "Unknown speaker"


def display_label(segment: TranscriptSegment | dict) -> str:
    if isinstance(segment, dict):
        return segment.get("speaker_label") or generic_label(segment.get("speaker_key") or "")
    return segment.speaker_label or generic_label(segment.speaker_key)


def format_clock(ms: int | None) -> str:
    if ms is None:
        return ""
    seconds = max(0, ms) // 1000
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _parse_clock(value: str) -> int:
    value = value.replace(",", ".")
    parts = value.split(":")
    seconds = float(parts[-1])
    minutes = int(parts[-2]) if len(parts) >= 2 else 0
    hours = int(parts[-3]) if len(parts) >= 3 else 0
    return int(round((hours * 3600 + minutes * 60 + seconds) * 1000))


# --- parsing -----------------------------------------------------------------


def _speaker_from_name(raw: str) -> tuple[str, str | None]:
    """(speaker_key, speaker_label) for a speaker named in the text itself.
    "Speaker 2" is the generic diarizer label and maps back to key "1"."""
    name = raw.strip()
    generic = _GENERIC_SPEAKER_RE.match(name)
    if generic:
        return str(max(0, int(generic.group(1)) - 1)), None
    return name, name


def _looks_like_speaker(candidate: str) -> bool:
    candidate = candidate.strip()
    if not candidate or len(candidate) > MAX_SPEAKER_CHARS:
        return False
    if len(candidate.split()) > MAX_SPEAKER_WORDS or candidate.lower() in _NOT_SPEAKERS:
        return False
    if re.search(r"\d{1,2}:\d{2}", candidate) or "//" in candidate:
        return False
    return bool(re.match(r"^[^\W\d_]", candidate))


def _split_speaker(line: str) -> tuple[str, str | None, str]:
    match = _SPEAKER_LINE_RE.match(line)
    if match:
        candidate = match.group(1) or match.group(2) or ""
        if _looks_like_speaker(candidate):
            key, label = _speaker_from_name(candidate)
            return key, label, match.group(3).strip()
    return "", None, line.strip()


def _parse_cues(text: str) -> list[dict]:
    """WebVTT or SRT — anything whose cues carry `start --> end` timings."""
    segments: list[dict] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = [line for line in block.split("\n") if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if _CUE_TIMING_RE.match(line)), None)
        if timing_index is None:
            continue
        timing = _CUE_TIMING_RE.match(lines[timing_index])
        body = "\n".join(lines[timing_index + 1:]).strip()
        if not body:
            continue
        voice = _VTT_VOICE_RE.match(body)
        if voice:
            key, label = _speaker_from_name(voice.group(1))
            spoken = _TAG_RE.sub("", voice.group(2)).strip()
        else:
            key, label, spoken = _split_speaker(_TAG_RE.sub("", body).replace("\n", " "))
        if not spoken:
            continue
        segments.append(
            {
                "speaker_key": key,
                "speaker_label": label,
                "text": re.sub(r"\s+", " ", spoken),
                "start_ms": _parse_clock(timing.group(1)),
                "end_ms": _parse_clock(timing.group(2)),
                "confidence": None,
            }
        )
    return segments


def _parse_json(text: str) -> list[dict] | None:
    """A JSON array of {speaker, text, start, end} objects (seconds), or this
    app's own JSON export ({segments: [{speaker, text, start_ms, end_ms}]})."""
    try:
        payload = json.loads(text)
    except ValueError:
        return None
    items = payload.get("segments") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return None
    segments = []
    for item in items:
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            continue
        if "start_ms" in item or "end_ms" in item:
            start = item.get("start_ms")
            end = item.get("end_ms")
        else:
            start = int(round(float(item["start"]) * 1000)) if item.get("start") is not None else None
            end = int(round(float(item["end"]) * 1000)) if item.get("end") is not None else None
        speaker = str(item.get("speaker") or item.get("speaker_label") or "").strip()
        key, label = _speaker_from_name(speaker) if speaker else ("", None)
        segments.append(
            {
                "speaker_key": key,
                "speaker_label": label,
                "text": str(item["text"]).strip(),
                "start_ms": int(start) if start is not None else None,
                "end_ms": int(end) if end is not None else None,
                "confidence": None,
            }
        )
    return segments


def parse_transcript_text(text: str) -> list[dict]:
    """Turn pasted or legacy transcript text into segment dicts.

    Supports WebVTT/SRT cues, a JSON segment array, and plain lines with an
    optional leading timestamp ("[00:01:23]") and optional "Speaker:" prefix.
    Lines without a speaker continue the previous speaker's turn rather than
    being attributed to anyone new.
    """
    text = (text or "").strip()
    if not text:
        return []
    if text.startswith("[") or text.startswith("{"):
        parsed = _parse_json(text)
        if parsed:
            return parsed
    if _HAS_CUES_RE.search(text):
        cues = _parse_cues(text)
        if cues:
            return cues

    segments: list[dict] = []
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        start_ms = None
        time_match = _LEADING_TIME_RE.match(line)
        if time_match and time_match.end() < len(line):
            start_ms = _parse_clock(time_match.group(1))
            line = line[time_match.end():].strip()
        key, label, spoken = _split_speaker(line)
        if not spoken:
            continue
        has_speaker = bool(key or label)
        if segments and not has_speaker and start_ms is None:
            segments[-1]["text"] = f"{segments[-1]['text']} {spoken}"
            continue
        segments.append(
            {
                "speaker_key": key,
                "speaker_label": label,
                "text": spoken,
                "start_ms": start_ms,
                "end_ms": None,
                "confidence": None,
            }
        )
    # A timestamp on the next line is the only honest end time we have.
    for current, following in zip(segments, segments[1:]):
        if current["start_ms"] is not None and following["start_ms"] is not None and following["start_ms"] >= current["start_ms"]:
            current["end_ms"] = following["start_ms"]
    return segments


def segments_from_turns(turns: list[dict], names: dict[str, str] | None = None) -> list[dict]:
    """Provider transcription turns (seconds, speaker numbers) → segment dicts."""
    names = names or {}
    segments = []
    for turn in turns:
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        key = str(int(turn.get("speaker", 0)))
        confidence = turn.get("confidence")
        words = turn.get("words")
        segments.append(
            {
                "speaker_key": key,
                "speaker_label": names.get(key) or None,
                "text": text,
                "start_ms": int(round(float(turn.get("start", 0.0)) * 1000)),
                "end_ms": int(round(float(turn.get("end", 0.0)) * 1000)),
                "confidence": float(confidence) if confidence is not None else None,
                # Only when it lines up word-for-word with the text.
                "word_times": words if isinstance(words, list) and len(words) == len(text.split()) else None,
            }
        )
    return segments


# --- persistence -------------------------------------------------------------


def render_transcript(segments: list) -> str:
    return "\n".join(f"{display_label(segment)}: {_text(segment)}" for segment in segments)


def _text(segment) -> str:
    return segment["text"] if isinstance(segment, dict) else segment.text


async def load_segments(db: AsyncSession, meeting_id: uuid.UUID) -> list[TranscriptSegment]:
    result = await db.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.meeting_id == meeting_id)
        .order_by(TranscriptSegment.seq)
    )
    return list(result.scalars().all())


async def replace_segments(
    db: AsyncSession,
    meeting: Meeting,
    segment_dicts: list[dict],
    *,
    language: str | None = None,
) -> list[TranscriptSegment]:
    """Store `segment_dicts` as the meeting's transcript, replacing any
    existing segments, and re-render `meeting.transcript` from them."""
    await db.execute(delete(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting.id))
    rows = [
        TranscriptSegment(
            id=uuid.uuid4(),
            meeting_id=meeting.id,
            seq=index,
            speaker_key=item.get("speaker_key") or "",
            speaker_label=item.get("speaker_label") or None,
            text=item["text"],
            original_text=item.get("original_text") or item["text"],
            start_ms=item.get("start_ms"),
            end_ms=item.get("end_ms"),
            confidence=item.get("confidence"),
            word_times=item.get("word_times"),
            language=language,
        )
        for index, item in enumerate(segment_dicts)
    ]
    db.add_all(rows)
    await db.flush()
    if rows:
        meeting.transcript = render_transcript(rows)
    return rows


def _recording_segments(recording_id: uuid.UUID) -> list[dict] | None:
    """Timestamped segments from a recording's stored diarization, with the
    speaker names and per-turn corrections people already saved."""
    # Imported lazily: app.routes.recordings imports this module.
    from app.routes.recordings import (
        _apply_speaker_corrections,
        _load_speaker_names,
        _session_dir,
    )

    directory = _session_dir(recording_id)
    path = directory / "recording.diarization.json"
    if not path.exists():
        return None
    detailed = _apply_speaker_corrections(directory, json.loads(path.read_text(encoding="utf-8")))
    return segments_from_turns(detailed.get("turns") or [], _load_speaker_names(directory)) or None


async def ensure_segments(db: AsyncSession, meeting: Meeting) -> list[TranscriptSegment]:
    """Segments for a meeting, creating them on first access for meetings
    stored before segments existed. A linked recording's diarization is
    preferred because it carries real timestamps; otherwise the stored
    transcript text is parsed."""
    segments = await load_segments(db, meeting.id)
    if segments:
        return segments
    from app.database.models import RecordingSession

    recording = (
        await db.execute(
            select(RecordingSession).where(RecordingSession.meeting_id == meeting.id).limit(1)
        )
    ).scalar_one_or_none()
    dicts = _recording_segments(recording.id) if recording else None
    from_recording = bool(dicts)
    if not dicts:
        dicts = parse_transcript_text(meeting.transcript or "")
    if not dicts:
        return []
    keep_text = meeting.transcript
    segments = await replace_segments(db, meeting, dicts)
    if not from_recording:
        # Parsing is lossless enough for search, but never rewrite the stored
        # text of a meeting nobody has corrected yet just because we read it.
        meeting.transcript = keep_text
    return segments


async def sync_from_turns(
    db: AsyncSession, meeting: Meeting, turns: list[dict], names: dict[str, str]
) -> list[TranscriptSegment]:
    """Bring segments in line with a recording's (re)diarized turns.

    When the turns are the same ones the segments were built from (same count,
    same start times) only speakers change, so any text corrections survive.
    Otherwise the audio was re-transcribed: segments are rebuilt and evidence
    on the meeting's items is re-anchored by its quoted text.
    """
    fresh = segments_from_turns(turns, names)
    existing = await load_segments(db, meeting.id)
    same_turns = len(existing) == len(fresh) and all(
        old.start_ms == new["start_ms"] for old, new in zip(existing, fresh)
    )
    if same_turns:
        for old, new in zip(existing, fresh):
            old.speaker_key = new["speaker_key"]
            old.speaker_label = new["speaker_label"]
            if old.word_times is None and new.get("word_times") and old.text == new["text"]:
                old.word_times = new["word_times"]
        meeting.transcript = render_transcript(existing)
        await db.flush()
        return existing
    segments = await replace_segments(db, meeting, fresh)
    from app.services import insight_service

    await insight_service.reanchor_evidence(db, meeting.id, segments)
    return segments


# --- prompts, exports, analytics ---------------------------------------------


def prompt_lines(segments: list, prefix: str = "S") -> str:
    """The transcript as the LLM sees it: every line carries a citable id."""
    lines = []
    for segment in segments:
        clock = format_clock(segment.start_ms)
        stamp = f"{prefix}{segment.seq}" + (f" {clock}" if clock else "")
        lines.append(f"[{stamp}] {display_label(segment)}: {segment.text}")
    return "\n".join(lines)


def has_timestamps(segments: list) -> bool:
    return bool(segments) and all(s.start_ms is not None and s.end_ms is not None for s in segments)


def _srt_clock(ms: int) -> str:
    hours, rest = divmod(ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


class ExportUnavailable(ValueError):
    pass


def export(meeting: Meeting, segments: list, fmt: str) -> tuple[str, str, str]:
    """(content, media type, file extension). SRT/VTT need real timestamps on
    every segment and raise ExportUnavailable otherwise."""
    header_date = meeting.date.isoformat()
    if fmt == "txt":
        lines = [meeting.title, header_date, ""]
        for s in segments:
            clock = format_clock(s.start_ms)
            lines.append(f"{'[' + clock + '] ' if clock else ''}{display_label(s)}: {s.text}")
        return "\n".join(lines) + "\n", "text/plain; charset=utf-8", "txt"
    if fmt == "md":
        lines = [f"# {meeting.title}", "", f"*{header_date}*", ""]
        for s in segments:
            clock = format_clock(s.start_ms)
            lines.append(f"**{display_label(s)}**{' `' + clock + '`' if clock else ''}: {s.text}")
            lines.append("")
        return "\n".join(lines), "text/markdown; charset=utf-8", "md"
    if fmt == "json":
        payload = {
            "meeting": {"id": str(meeting.id), "title": meeting.title, "date": header_date},
            "transcript_revision": meeting.transcript_revision,
            "segments": [
                {
                    "id": str(s.id),
                    "seq": s.seq,
                    "speaker": display_label(s),
                    "speaker_key": s.speaker_key,
                    "text": s.text,
                    "original_text": s.original_text,
                    "start_ms": s.start_ms,
                    "end_ms": s.end_ms,
                    "confidence": s.confidence,
                    "edited": s.edited_at is not None,
                }
                for s in segments
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2), "application/json", "json"
    if fmt in {"srt", "vtt"}:
        if not has_timestamps(segments):
            raise ExportUnavailable("This transcript has no timestamps, so SRT/VTT subtitles cannot be produced")
        if fmt == "srt":
            blocks = [
                f"{index}\n{_srt_clock(s.start_ms)} --> {_srt_clock(s.end_ms)}\n{display_label(s)}: {s.text}\n"
                for index, s in enumerate(segments, start=1)
            ]
            return "\n".join(blocks), "application/x-subrip; charset=utf-8", "srt"
        blocks = ["WEBVTT", ""] + [
            f"{_srt_clock(s.start_ms).replace(',', '.')} --> {_srt_clock(s.end_ms).replace(',', '.')}\n"
            f"<v {display_label(s)}>{s.text}\n"
            for s in segments
        ]
        return "\n".join(blocks), "text/vtt; charset=utf-8", "vtt"
    raise ExportUnavailable(f"Unsupported export format: {fmt}")


def talk_time(segments: list) -> dict[str, Any]:
    """Deterministic speaking-time breakdown.

    Each speaker's time is the sum of their own segments' durations, so when
    two people talk over each other both are credited and the per-speaker
    seconds can add up to more than the meeting's length. Shares are of total
    *speaking* time, not of the meeting. Without timestamps only word counts
    are available and `timed` is False.
    """
    timed = has_timestamps(segments)
    speakers: dict[str, dict[str, Any]] = {}
    for s in segments:
        item = speakers.setdefault(
            s.speaker_key or display_label(s),
            {"speaker_key": s.speaker_key, "speaker": display_label(s), "seconds": 0.0, "words": 0, "turns": 0},
        )
        item["words"] += len(s.text.split())
        item["turns"] += 1
        if timed:
            item["seconds"] += max(0, s.end_ms - s.start_ms) / 1000
    total_seconds = sum(item["seconds"] for item in speakers.values())
    total_words = sum(item["words"] for item in speakers.values())
    rows = []
    for item in speakers.values():
        rows.append(
            {
                **item,
                "seconds": round(item["seconds"], 1) if timed else None,
                "share": round((item["seconds"] / total_seconds) if timed and total_seconds else (item["words"] / total_words if total_words else 0), 3),
            }
        )
    rows.sort(key=lambda row: row["share"], reverse=True)
    span = (
        (max(s.end_ms for s in segments) - min(s.start_ms for s in segments)) / 1000 if timed else None
    )
    return {
        "timed": timed,
        "basis": "speaking_seconds" if timed else "words",
        "speakers": rows,
        "total_speaking_seconds": round(total_seconds, 1) if timed else None,
        "transcript_span_seconds": round(span, 1) if span is not None else None,
        "segment_count": len(segments),
    }
