import asyncio
import datetime
import json
import logging
import re
import subprocess
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.db import get_db
from app.database.models import Meeting, MeetingInsight, RecordingSession, TranscriptSegment, User
from app.dependencies import get_current_user, user_can_manage_meeting_access, user_can_read_meeting
from app.services import ai_extractor, attendee_service, transcriber, transcript_service
from app.services.meeting_index_service import rebuild_meeting_index

router = APIRouter(prefix="/api/recordings", tags=["recordings"])
logger = logging.getLogger(__name__)
MAX_CHUNK_BYTES = 25 * 1024 * 1024
SUPPORTED_LANGUAGES = {"en", "hi", "hinglish", "auto"}
SUPPORTED_MEETING_TYPES = {"physical", "online"}


class AttendeeInput(BaseModel):
    """One person in the room. `user_id` set means a Charcha colleague picked
    from the directory; `user_id` unset means an external guest typed in by
    name (and optionally email) who has no account and never gains access."""

    user_id: uuid.UUID | None = None
    name: str = Field(default="", max_length=200)
    email: str | None = Field(default=None, max_length=320)


class CreateRecordingRequest(BaseModel):
    title: str = ""
    meeting_type: str = "physical"
    language: str = "hinglish"
    # Legacy field: a plain list of display names. Superseded by `attendees`,
    # still accepted so an older client keeps working.
    participants: list[str] = Field(default_factory=list, max_length=100)
    attendees: list[AttendeeInput] = Field(default_factory=list, max_length=100)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = value.strip()
        return value


class FinalizeRecordingRequest(BaseModel):
    duration_seconds: int


class LinkMeetingRequest(BaseModel):
    meeting_id: uuid.UUID


class SpeakerNamesRequest(BaseModel):
    names: dict[str, str]


class SpeakerCorrectionsRequest(BaseModel):
    corrections: dict[str, int]


def _session_dir(recording_id: uuid.UUID) -> Path:
    path = Path(settings.recordings_dir).resolve() / str(recording_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _get_owned_recording(
    recording_id: uuid.UUID, user: User, db: AsyncSession
) -> RecordingSession:
    """For the write side of a recording — uploading chunks, finalizing,
    linking, renaming speakers. Only the person doing the recording may do
    these, whether or not it has been linked to a meeting yet."""
    recording = await db.get(RecordingSession, recording_id)
    if recording is None or recording.user_id != user.id:
        raise HTTPException(status_code=404, detail="Recording not found")
    return recording


async def _get_readable_recording(
    recording_id: uuid.UUID, user: User, db: AsyncSession
) -> RecordingSession:
    """For a finished recording's audio, diarization, and speaker corrections.

    Wider than `_get_owned_recording` on purpose: once a recording is linked to
    a meeting, everyone who can read that meeting can play its audio and fix
    its speaker labels. Without this, an attendee could open the meeting page
    but its audio player would 404 and the speaker editor it renders would fail
    on save — they can already read the transcript and edit the summary, so the
    recording is not the secret.
    """
    recording = await db.get(RecordingSession, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    if recording.user_id == user.id:
        return recording
    if recording.meeting_id and await user_can_read_meeting(db, user, recording.meeting_id):
        return recording
    raise HTTPException(status_code=404, detail="Recording not found")


def _serialize(recording: RecordingSession) -> dict:
    return {
        "id": str(recording.id),
        "meeting_id": str(recording.meeting_id) if recording.meeting_id else None,
        "title": recording.title,
        "meeting_type": recording.meeting_type,
        "language": recording.language,
        "participants": recording.participants or [],
        "attendees": recording.attendees or [],
        "status": recording.status,
        "duration_seconds": recording.duration_seconds,
        "chunk_count": recording.chunk_count,
        "total_bytes": recording.total_bytes,
        "started_at": recording.started_at.isoformat(),
        "ended_at": recording.ended_at.isoformat() if recording.ended_at else None,
    }


def _load_speaker_names(directory: Path) -> dict[str, str]:
    path = directory / "speaker_names.json"
    if not path.exists():
        return {}
    return {str(key): str(value) for key, value in json.loads(path.read_text(encoding="utf-8")).items()}


def _load_speaker_corrections(directory: Path) -> dict[str, int]:
    path = directory / "speaker_corrections.json"
    if not path.exists():
        return {}
    return {str(key): int(value) for key, value in json.loads(path.read_text(encoding="utf-8")).items()}


def _apply_speaker_corrections(directory: Path, detailed: dict) -> dict:
    corrections = _load_speaker_corrections(directory)
    return {
        **detailed,
        "turns": [
            {**turn, "speaker": corrections.get(str(index), int(turn["speaker"]))}
            for index, turn in enumerate(detailed["turns"])
        ],
    }


def _speaker_activity(turns: list[dict], names: dict[str, str]) -> list[dict]:
    totals: dict[int, dict] = {}
    for turn in turns:
        speaker = int(turn["speaker"])
        item = totals.setdefault(
            speaker,
            {"speaker": names.get(str(speaker)) or f"Speaker {speaker + 1}", "words": 0, "seconds": 0.0},
        )
        item["words"] += int(turn.get("word_count", 0))
        item["seconds"] += max(0.0, float(turn.get("end", 0)) - float(turn.get("start", 0)))
    total_words = sum(item["words"] for item in totals.values())
    return [
        {
            **item,
            "seconds": round(item["seconds"], 1),
            "share": round(item["words"] / total_words, 3) if total_words else 0,
        }
        for _, item in sorted(totals.items())
    ]


async def _apply_diarization_to_meeting(
    recording: RecordingSession, detailed: dict, names: dict[str, str], db: AsyncSession
) -> None:
    if not recording.meeting_id:
        return
    meeting = await db.get(Meeting, recording.meeting_id)
    if meeting:
        # Keeps segments (and so timestamps, comments' anchors and evidence)
        # in step with the diarization; re-renders meeting.transcript.
        await transcript_service.sync_from_turns(db, meeting, detailed["turns"], names)
        if meeting.summary:
            # A human-reviewed summary stays authoritative; only replace the
            # stale generic labels. AI summaries are regenerated from the
            # newly named transcript so prose and attribution both improve.
            if meeting.summary_verified_at:
                for speaker_id, name in names.items():
                    meeting.summary = re.sub(
                        rf"\bSpeaker\s+{int(speaker_id) + 1}\b",
                        name,
                        meeting.summary,
                        flags=re.IGNORECASE,
                    )
            else:
                try:
                    summary, _ = await asyncio.to_thread(
                        ai_extractor.generate_detailed_summary,
                        meeting.transcript,
                        meeting.title,
                    )
                    if summary.strip():
                        meeting.summary = summary.strip()
                except Exception:
                    logger.exception("Could not regenerate summary after speaker-name correction")
                    for speaker_id, name in names.items():
                        meeting.summary = re.sub(
                            rf"\bSpeaker\s+{int(speaker_id) + 1}\b",
                            name,
                            meeting.summary,
                            flags=re.IGNORECASE,
                        )
    insight = await db.get(MeetingInsight, recording.meeting_id)
    if insight:
        insight.speaker_activity = _speaker_activity(detailed["turns"], names)
    await db.flush()
    await rebuild_meeting_index(db, recording.meeting_id)


async def _diarize_full_recording(
    recording: RecordingSession, directory: Path, *, force: bool = False
) -> dict:
    detailed_path = directory / "recording.diarization.json"
    if detailed_path.exists() and not force:
        return json.loads(detailed_path.read_text(encoding="utf-8"))
    if force:
        (directory / "speaker_corrections.json").unlink(missing_ok=True)
    audio_path = directory / "recording.webm"
    detailed = await transcriber.transcribe_audio_detailed(
        audio_path.read_bytes(),
        recording.mime_type or "audio/webm",
        recording.language,
        expected_speakers=len(recording.participants or []) or None,
        people=list(recording.participants or []),
    )
    detailed_path.write_text(json.dumps(detailed, ensure_ascii=False), encoding="utf-8")
    (directory / "recording.txt").write_text(detailed["transcript"], encoding="utf-8")
    return detailed


def _diarization_response(directory: Path, detailed: dict) -> dict:
    detailed = _apply_speaker_corrections(directory, detailed)
    names = _load_speaker_names(directory)
    turns = [
        {
            **turn,
            "speaker_name": names.get(str(turn["speaker"])) or f"Speaker {int(turn['speaker']) + 1}",
        }
        for turn in detailed["turns"]
    ]
    return {
        **detailed,
        "turns": turns,
        "speaker_names": names,
        "speaker_corrections": _load_speaker_corrections(directory),
        "speaker_activity": _speaker_activity(detailed["turns"], names),
    }


@router.post("")
async def create_recording(
    body: CreateRecordingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if body.meeting_type not in SUPPORTED_MEETING_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported meeting type")
    if body.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported meeting language")
    raw_attendees = [item.model_dump() for item in body.attendees] or list(body.participants)
    resolved = await attendee_service.resolve(db, raw_attendees)
    recording = RecordingSession(
        user_id=user.id,
        title=body.title or "Meeting in progress",
        meeting_type=body.meeting_type,
        language=body.language,
        participants=[item["name"] for item in resolved],
        attendees=resolved,
    )
    db.add(recording)
    await db.commit()
    await db.refresh(recording)
    _session_dir(recording.id)
    return _serialize(recording)


@router.get("/active")
async def list_active_recordings(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    result = await db.execute(
        select(RecordingSession)
        .where(RecordingSession.user_id == user.id, RecordingSession.status.in_(["recording", "recorded"]))
        .order_by(RecordingSession.started_at.desc())
    )
    return [_serialize(item) for item in result.scalars().all()]


@router.post("/{recording_id}/chunks")
async def upload_chunk(
    recording_id: uuid.UUID,
    chunk_index: int = Form(...),
    chunk: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    recording = await _get_owned_recording(recording_id, user, db)
    if recording.status != "recording":
        raise HTTPException(status_code=409, detail="Recording is no longer accepting chunks")
    if chunk_index < 0:
        raise HTTPException(status_code=400, detail="Invalid chunk index")

    data = await chunk.read()
    if not data:
        raise HTTPException(status_code=400, detail="Audio chunk is empty")
    if len(data) > MAX_CHUNK_BYTES:
        raise HTTPException(status_code=413, detail="Audio chunk exceeds the 25 MB limit")

    directory = _session_dir(recording.id)
    audio_path = directory / f"{chunk_index:06d}.webm"
    transcript_path = directory / f"{chunk_index:06d}.txt"
    detailed_path = directory / f"{chunk_index:06d}.json"
    if not audio_path.exists():
        audio_path.write_bytes(data)
    if not transcript_path.exists():
        detailed = await transcriber.transcribe_audio_detailed(
            data,
            chunk.content_type or "audio/webm",
            recording.language,
            expected_speakers=len(recording.participants or []) or None,
            people=list(recording.participants or []),
        )
        text = detailed["transcript"]
        transcript_path.write_text(text, encoding="utf-8")
        detailed_path.write_text(json.dumps(detailed, ensure_ascii=False), encoding="utf-8")
    else:
        text = transcript_path.read_text(encoding="utf-8")

    chunk_files = list(directory.glob("*.webm"))
    recording.chunk_count = len(chunk_files)
    recording.total_bytes = sum(path.stat().st_size for path in chunk_files)
    recording.mime_type = chunk.content_type or recording.mime_type or "audio/webm"
    await db.commit()
    return {"chunk_index": chunk_index, "transcript": text}


@router.post("/{recording_id}/finalize")
async def finalize_recording(
    recording_id: uuid.UUID,
    body: FinalizeRecordingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    started = time.perf_counter()
    recording = await _get_owned_recording(recording_id, user, db)
    directory = _session_dir(recording.id)
    chunks = sorted(path for path in directory.glob("*.webm") if path.name != "recording.webm")
    transcripts = sorted(directory.glob("[0-9][0-9][0-9][0-9][0-9][0-9].txt"))
    if not chunks or len(chunks) != len(transcripts):
        raise HTTPException(status_code=409, detail="Some recording chunks have not finished uploading")

    full_audio = directory / "recording.webm"
    if len(chunks) == 1:
        full_audio.write_bytes(chunks[0].read_bytes())
    else:
        concat_file = directory / "chunks.txt"
        concat_file.write_text(
            "".join(f"file '{path.name}'\n" for path in chunks), encoding="utf-8"
        )

        def join_chunks() -> None:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    concat_file.name,
                    "-c:a",
                    "libopus",
                    "-b:a",
                    "48k",
                    full_audio.name,
                ],
                cwd=directory,
                check=True,
                capture_output=True,
            )

        try:
            await asyncio.to_thread(join_chunks)
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise HTTPException(status_code=500, detail="Unable to assemble the recording audio") from exc
    transcript = "\n".join(path.read_text(encoding="utf-8") for path in transcripts).strip()
    if not transcript:
        raise HTTPException(status_code=422, detail="The recording did not contain recognizable speech")

    recording.status = "recorded"
    recording.duration_seconds = max(0, body.duration_seconds)
    recording.total_bytes = full_audio.stat().st_size
    recording.ended_at = datetime.datetime.now(datetime.UTC)
    assembled_at = time.perf_counter()
    try:
        detailed = await _diarize_full_recording(recording, directory)
        transcript = detailed["transcript"]
    except Exception:
        # Chunk transcripts remain a durable fallback if the final, global
        # diarization pass is temporarily unavailable.
        detailed = None
        logger.exception("Full-recording diarization failed for %s; using chunk transcript", recording.id)
    await db.commit()
    finished_at = time.perf_counter()
    logger.info(
        "Recording %s finalized: assembly %.2fs, full diarization %.2fs, total %.2fs",
        recording.id,
        assembled_at - started,
        finished_at - assembled_at,
        finished_at - started,
    )
    return {
        "recording": _serialize(recording),
        "transcript": transcript,
        "diarization": _diarization_response(directory, detailed) if detailed else None,
        "processing_timings": {
            "assembly_seconds": round(assembled_at - started, 2),
            "diarization_seconds": round(finished_at - assembled_at, 2),
            "total_seconds": round(finished_at - started, 2),
        },
    }


@router.post("/{recording_id}/link")
async def link_recording(
    recording_id: uuid.UUID,
    body: LinkMeetingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    recording = await _get_owned_recording(recording_id, user, db)
    if recording.meeting_id and recording.meeting_id != body.meeting_id:
        raise HTTPException(status_code=409, detail="Recording is already linked to another meeting")
    meeting = await db.get(Meeting, body.meeting_id)
    if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, body.meeting_id):
        raise HTTPException(status_code=404, detail="Meeting not found")
    # Linking adds the recording's attendees to the meeting, i.e. grants them
    # access — only the people who decide access may do that.
    if not await user_can_manage_meeting_access(db, user, meeting):
        raise HTTPException(
            status_code=403,
            detail="Only the meeting's organizer, the person who recorded it, or a Charcha admin can attach a recording",
        )
    recording.meeting_id = meeting.id
    recording.title = meeting.title
    recording.status = "processed"
    # The people picked before recording started are what grants access to the
    # meeting this recording just became. Merged, never replaced: the meeting
    # may already have attendees added by hand or matched from Google Meet, and
    # linking a recording is no reason to drop them.
    _, newly_added = await attendee_service.apply_to_meeting(
        db,
        meeting.id,
        recording.attendees or [],
        owner_user_id=meeting.user_id,
        source="manual",
        replace=False,
    )
    await attendee_service.notify_new_attendees(db, meeting.id, newly_added, meeting.title)
    await _adopt_recording_segments(db, recording, meeting)
    await db.commit()
    return {"ok": True}


async def _adopt_recording_segments(db: AsyncSession, recording: RecordingSession, meeting: Meeting) -> None:
    """A freshly recorded meeting's transcript *is* this recording's
    diarization, so take its timestamped turns as the segments. Skipped once
    anyone has corrected the transcript by hand."""
    directory = _session_dir(recording.id)
    path = directory / "recording.diarization.json"
    if not path.exists():
        return
    edited = await db.scalar(
        select(func.count())
        .select_from(TranscriptSegment)
        .where(TranscriptSegment.meeting_id == meeting.id, TranscriptSegment.edited_at.is_not(None))
    )
    if edited:
        return
    detailed = _apply_speaker_corrections(directory, json.loads(path.read_text(encoding="utf-8")))
    await transcript_service.sync_from_turns(db, meeting, detailed["turns"], _load_speaker_names(directory))


@router.get("/{recording_id}/audio")
async def get_audio(
    recording_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    recording = await _get_readable_recording(recording_id, user, db)
    path = _session_dir(recording.id) / "recording.webm"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Recording audio is not available")
    safe_title = re.sub(r"[^a-zA-Z0-9._ -]+", "", recording.title).strip() or "meeting"
    return FileResponse(path, media_type=recording.mime_type or "audio/webm", filename=f"{safe_title}.webm")


@router.get("/{recording_id}/diarization")
async def get_diarization(
    recording_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    recording = await _get_readable_recording(recording_id, user, db)
    directory = _session_dir(recording.id)
    path = directory / "recording.diarization.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Detailed diarization is not available yet")
    return _diarization_response(directory, json.loads(path.read_text(encoding="utf-8")))


@router.post("/{recording_id}/rediarize")
async def rediarize_recording(
    recording_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    recording = await _get_readable_recording(recording_id, user, db)
    directory = _session_dir(recording.id)
    if not (directory / "recording.webm").exists():
        raise HTTPException(status_code=409, detail="Finalize the recording before re-analyzing speakers")
    detailed = await _diarize_full_recording(recording, directory, force=True)
    names = _load_speaker_names(directory)
    await _apply_diarization_to_meeting(
        recording, _apply_speaker_corrections(directory, detailed), names, db
    )
    await db.commit()
    return _diarization_response(directory, detailed)


@router.patch("/{recording_id}/speakers")
async def update_speaker_names(
    recording_id: uuid.UUID,
    body: SpeakerNamesRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    recording = await _get_readable_recording(recording_id, user, db)
    directory = _session_dir(recording.id)
    path = directory / "recording.diarization.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Detailed diarization is not available yet")
    detailed = json.loads(path.read_text(encoding="utf-8"))
    detected = {str(turn["speaker"]) for turn in detailed["turns"]}
    names = {
        key: value.strip()
        for key, value in body.names.items()
        if key in detected and value.strip()
    }
    (directory / "speaker_names.json").write_text(
        json.dumps(names, ensure_ascii=False), encoding="utf-8"
    )
    await _apply_diarization_to_meeting(
        recording, _apply_speaker_corrections(directory, detailed), names, db
    )
    await db.commit()
    return _diarization_response(directory, detailed)


@router.patch("/{recording_id}/speaker-corrections")
async def update_speaker_corrections(
    recording_id: uuid.UUID,
    body: SpeakerCorrectionsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    recording = await _get_readable_recording(recording_id, user, db)
    directory = _session_dir(recording.id)
    path = directory / "recording.diarization.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Detailed diarization is not available yet")
    detailed = json.loads(path.read_text(encoding="utf-8"))
    detected = {int(turn["speaker"]) for turn in detailed["turns"]}
    corrections = {
        key: speaker
        for key, speaker in body.corrections.items()
        if key.isdigit() and int(key) < len(detailed["turns"]) and speaker in detected
    }
    (directory / "speaker_corrections.json").write_text(
        json.dumps(corrections), encoding="utf-8"
    )
    corrected = _apply_speaker_corrections(directory, detailed)
    names = _load_speaker_names(directory)
    await _apply_diarization_to_meeting(recording, corrected, names, db)
    await db.commit()
    return _diarization_response(directory, detailed)
