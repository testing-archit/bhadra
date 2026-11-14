"""Meeting Assistant: the transcript workspace around a stored meeting.

Every route here resolves the meeting through `_readable_meeting`, i.e. the
same attendee-based visibility rule as the rest of the app (see
app/dependencies.py). A meeting the caller cannot read is a 404 — never a 403
that would confirm it exists.
"""

import asyncio
import datetime
import json
import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.db import get_db
from app.database.models import (
    Decision,
    InsightRun,
    Meeting,
    MeetingAttendee,
    MeetingBookmark,
    MeetingComment,
    MeetingInsight,
    MeetingTask,
    RecordingSession,
    Risk,
    ServiceHeartbeat,
    Trace,
    TranscriptEdit,
    TranscriptSegment,
    User,
)
from app.dependencies import get_current_user, is_admin, meeting_visibility_clause, user_can_read_meeting
from app.rate_limit import limiter
from app.services import (
    ai_extractor,
    attendee_service,
    insight_service,
    media_service,
    meeting_pipeline,
    prep_service,
    processing_service,
    transcript_service,
    vocabulary_service,
)

router = APIRouter(prefix="/api/meetings", tags=["meeting-assistant"])
logger = logging.getLogger(__name__)

UPLOAD_READ_CHUNK = 1024 * 1024
MAX_SEGMENT_PAGE = 2000
NOTETAKER_HEARTBEAT = "notetaker"
NOTETAKER_ONLINE_SECONDS = 180


# --- helpers -------------------------------------------------------------------


async def _readable_meeting(db: AsyncSession, user: User, meeting_id: uuid.UUID) -> Meeting:
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, meeting.id):
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


def _iso(value: datetime.datetime | None) -> str | None:
    return value.isoformat() if value else None


def _segment_payload(segment: TranscriptSegment) -> dict:
    edited = segment.edited_at is not None
    return {
        "id": str(segment.id),
        "seq": segment.seq,
        "speaker_key": segment.speaker_key,
        "speaker": transcript_service.display_label(segment),
        "speaker_named": bool(segment.speaker_label),
        "text": segment.text,
        "original_text": segment.original_text if edited else None,
        "start_ms": segment.start_ms,
        "end_ms": segment.end_ms,
        "confidence": segment.confidence,
        "word_times": segment.word_times,
        "edited": edited,
        "edited_at": _iso(segment.edited_at),
    }


async def _recording_for(db: AsyncSession, meeting_id: uuid.UUID) -> RecordingSession | None:
    return (
        await db.execute(select(RecordingSession).where(RecordingSession.meeting_id == meeting_id).limit(1))
    ).scalar_one_or_none()


async def _notetaker_status(db: AsyncSession) -> dict:
    heartbeat = await db.get(ServiceHeartbeat, NOTETAKER_HEARTBEAT)
    online = bool(
        heartbeat
        and (datetime.datetime.now(datetime.UTC) - heartbeat.last_seen_at).total_seconds() < NOTETAKER_ONLINE_SECONDS
    )
    return {
        "configured": bool(settings.bot_api_secret),
        "online": online,
        "last_seen_at": _iso(heartbeat.last_seen_at) if heartbeat else None,
        "platforms": ["google_meet"],
        "bot_name": settings.notetaker_email,
    }


def _stale(meeting: Meeting) -> bool:
    return meeting.insights_revision is not None and meeting.insights_revision < (meeting.transcript_revision or 1)


async def _bump_revision(db: AsyncSession, meeting: Meeting, segments: list[TranscriptSegment]) -> None:
    meeting.transcript_revision = (meeting.transcript_revision or 1) + 1
    meeting.transcript = transcript_service.render_transcript(segments)


# --- status & templates ----------------------------------------------------------


@router.get("/assistant/status")
async def assistant_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """What is set up. The UI shows "Setup required" from this instead of
    letting a user start something that cannot work."""
    fixture = settings.fixture_mode_active
    return {
        "transcription": {
            "configured": bool(settings.deepgram_api_key) or fixture,
            "provider": "Deepgram Nova-3" if settings.deepgram_api_key else ("Development fixture" if fixture else None),
            "missing": None if settings.deepgram_api_key or fixture else "DEEPGRAM_API_KEY",
        },
        "ai": {
            "configured": bool(settings.gemini_api_key) or fixture,
            "model": settings.gemini_model if settings.gemini_api_key else ("Development fixture" if fixture else None),
            "missing": None if settings.gemini_api_key or fixture else "GEMINI_API_KEY",
        },
        "capture": await _notetaker_status(db),
        "media_tools": media_service.tools_available(),
        "fixture_mode": fixture,
        "limits": {
            "max_upload_mb": settings.max_upload_bytes // (1024 * 1024),
            "max_upload_minutes": settings.max_upload_duration_minutes,
        },
        # "auto" = inherit from the meeting's series, else detect the type.
        "templates": [{"id": "auto", "label": "Detect automatically"}]
        + [{"id": key, "label": spec["label"]} for key, spec in ai_extractor.TEMPLATES.items()],
    }


# --- upload ----------------------------------------------------------------------


@router.post("/upload", status_code=202)
@limiter.limit("10/minute")
async def upload_recording(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(""),
    language: str = Form("hinglish"),
    template: str = Form("general"),
    consent_acknowledged: bool = Form(False),
    idempotency_key: str | None = Form(None),
    attendees: str | None = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Store an uploaded recording and process it in the background.

    Returns as soon as the file is validated and stored; the meeting page
    shows each stage's real progress. `idempotency_key` makes a retried
    upload resolve to the meeting the first attempt created.
    """
    if not consent_acknowledged:
        raise HTTPException(
            status_code=422,
            detail="Confirm you have permission to record and process this conversation before uploading",
        )
    if language not in {"en", "hi", "hinglish", "auto"}:
        raise HTTPException(status_code=400, detail="Unsupported meeting language")
    # "auto" is resolved after transcription, once there's something to classify.
    template = "auto" if template == "auto" else ai_extractor.template_or_default(template)
    if idempotency_key is not None and not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", idempotency_key):
        raise HTTPException(status_code=400, detail="Invalid idempotency key")
    client_id = f"upload:{idempotency_key}" if idempotency_key else None
    if client_id:
        existing = (
            await db.execute(select(Meeting).where(Meeting.user_id == user.id, Meeting.client_meeting_id == client_id))
        ).scalar_one_or_none()
        if existing is not None:
            return {"meeting_id": str(existing.id), "status": "duplicate", "deduplicated": True}

    requested_attendees: list = []
    if attendees:
        try:
            requested_attendees = json.loads(attendees)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="attendees must be a JSON array")
        if not isinstance(requested_attendees, list):
            raise HTTPException(status_code=400, detail="attendees must be a JSON array")

    staging = Path(settings.recordings_dir).resolve() / "upload_staging"
    staging.mkdir(parents=True, exist_ok=True)
    temp_path = staging / f"{uuid.uuid4().hex}.upload"
    size = 0
    try:
        with temp_path.open("wb") as handle:
            while chunk := await file.read(UPLOAD_READ_CHUNK):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB upload limit",
                    )
                handle.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty")
        try:
            info = await asyncio.to_thread(media_service.probe, temp_path)
        except media_service.MediaRejected as error:
            raise HTTPException(status_code=415, detail=str(error))
        if info.duration_seconds and info.duration_seconds > settings.max_upload_duration_minutes * 60:
            raise HTTPException(
                status_code=413,
                detail=f"Recording is longer than the {settings.max_upload_duration_minutes}-minute limit",
            )

        recording = RecordingSession(
            user_id=user.id,
            title=(title.strip() or Path(file.filename or "Uploaded recording").stem)[:160],
            meeting_type="upload",
            language=language,
            status="processed",
            mime_type="audio/webm",
            duration_seconds=int(info.duration_seconds or 0),
            chunk_count=1,
            ended_at=datetime.datetime.now(datetime.UTC),
        )
        db.add(recording)
        await db.flush()
        from app.routes.recordings import _session_dir

        output = _session_dir(recording.id) / "recording.webm"
        try:
            await asyncio.to_thread(media_service.extract_audio, temp_path, output)
        except media_service.MediaRejected as error:
            raise HTTPException(status_code=415, detail=str(error))
        recording.total_bytes = output.stat().st_size

        meeting = Meeting(
            user_id=user.id,
            title=recording.title,
            date=datetime.datetime.now(datetime.UTC),
            transcript=None,
            duration_minutes=max(1, round((info.duration_seconds or 60) / 60)),
            department=user.department,
            client_meeting_id=client_id,
            source="upload",
            template=template,
        )
        db.add(meeting)
        await db.flush()
        recording.meeting_id = meeting.id
        _, newly_added = await attendee_service.apply_to_meeting(
            db, meeting.id, await attendee_service.resolve(db, requested_attendees),
            owner_user_id=user.id, source="manual",
        )
        await attendee_service.notify_new_attendees(db, meeting.id, newly_added, meeting.title)
        meeting_id, recording_id = meeting.id, recording.id
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        temp_path.unlink(missing_ok=True)

    await processing_service.set_stage(
        meeting_id, "audio", "succeeded",
        detail={"container": info.container, "has_video": info.has_video, "duration_seconds": info.duration_seconds, "bytes": size},
    )
    for stage in ("transcription", "extraction", "indexing"):
        await processing_service.set_stage(meeting_id, stage, "pending")
    background_tasks.add_task(
        meeting_pipeline.run_upload_pipeline, meeting_id, recording_id, template, adopt_title=not title.strip()
    )
    return {"meeting_id": str(meeting_id), "status": "processing", "deduplicated": False}


# --- processing --------------------------------------------------------------------


@router.get("/{meeting_id}/processing")
async def processing_status(
    meeting_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    meeting = await _readable_meeting(db, user, meeting_id)
    stages = await processing_service.list_stages(db, meeting.id)
    active = any(stage["status"] in {"pending", "running"} for stage in stages)
    return {
        "meeting_id": str(meeting.id),
        "stages": stages,
        "active": active,
        "transcript_revision": meeting.transcript_revision,
        "insights_revision": meeting.insights_revision,
        "insights_stale": _stale(meeting),
        "has_transcript": bool(meeting.transcript),
    }


RETRYABLE = {"transcription", "extraction", "indexing", "diarization"}


@router.post("/{meeting_id}/processing/{stage}/retry", status_code=202)
async def retry_stage(
    meeting_id: uuid.UUID,
    stage: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    meeting = await _readable_meeting(db, user, meeting_id)
    if stage not in RETRYABLE:
        raise HTTPException(status_code=400, detail=f"The {stage} stage cannot be retried")
    current = await processing_service.get_stage(db, meeting.id, stage)
    if current is not None and current.status in {"running", "pending"}:
        raise HTTPException(status_code=409, detail="That stage is already in progress")
    if current is not None and current.status == "succeeded" and stage == "transcription":
        # Never pay for the same audio twice.
        raise HTTPException(status_code=409, detail="This meeting is already transcribed")
    recording = await _recording_for(db, meeting.id)

    if stage == "transcription":
        if recording is None or not (Path(settings.recordings_dir).resolve() / str(recording.id) / "recording.webm").exists():
            raise HTTPException(status_code=409, detail="There is no stored recording to transcribe")
        await processing_service.set_stage(meeting.id, "transcription", "pending")
        background_tasks.add_task(
            meeting_pipeline.run_upload_pipeline, meeting.id, recording.id, meeting.template, adopt_title=False
        )
    elif stage == "extraction":
        if not meeting.transcript:
            raise HTTPException(status_code=409, detail="Transcribe the meeting before generating notes")
        await processing_service.set_stage(meeting.id, "extraction", "pending")

        async def run() -> None:
            async with processing_service.pipeline_slots():
                if await meeting_pipeline.extract(meeting_id, None):
                    await meeting_pipeline.index(meeting_id)

        background_tasks.add_task(run)
    elif stage == "indexing":
        await processing_service.set_stage(meeting.id, "indexing", "pending")
        background_tasks.add_task(meeting_pipeline.index, meeting.id)
    else:
        if recording is None:
            raise HTTPException(status_code=409, detail="This meeting has no recording to analyze")
        await processing_service.set_stage(meeting.id, "diarization", "pending")
        background_tasks.add_task(meeting_pipeline.diarize, meeting.id, recording.id)
    return {"ok": True, "stage": stage, "status": "pending"}


# --- transcript ----------------------------------------------------------------------


@router.get("/{meeting_id}/transcript")
async def get_transcript(
    meeting_id: uuid.UUID,
    q: str | None = Query(None, max_length=200),
    speaker: str | None = Query(None, max_length=200),
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=MAX_SEGMENT_PAGE),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    meeting = await _readable_meeting(db, user, meeting_id)
    segments = await transcript_service.ensure_segments(db, meeting)
    await db.commit()

    speakers: dict[str, dict] = {}
    for segment in segments:
        entry = speakers.setdefault(
            segment.speaker_key,
            {
                "key": segment.speaker_key,
                "label": transcript_service.display_label(segment),
                "generic": transcript_service.generic_label(segment.speaker_key),
                "named": bool(segment.speaker_label),
                "segment_count": 0,
            },
        )
        entry["segment_count"] += 1

    filtered = segments
    if speaker is not None:
        filtered = [s for s in filtered if s.speaker_key == speaker]
    if q and q.strip():
        needle = q.strip().lower()
        filtered = [s for s in filtered if needle in s.text.lower()]
    page = filtered[offset: offset + limit]
    recording = await _recording_for(db, meeting.id)
    diarization_available = bool(
        recording and (Path(settings.recordings_dir).resolve() / str(recording.id) / "recording.diarization.json").exists()
    )
    return {
        "meeting_id": str(meeting.id),
        "transcript_revision": meeting.transcript_revision,
        "insights_revision": meeting.insights_revision,
        "insights_stale": _stale(meeting),
        "has_timestamps": transcript_service.has_timestamps(segments),
        "has_recording": recording is not None,
        "recording_id": str(recording.id) if recording else None,
        # Offer "use the timestamped recording transcript" only when the
        # current segments have no times but the recording does.
        "can_use_recording_transcript": diarization_available and not transcript_service.has_timestamps(segments),
        "total": len(segments),
        "matched": len(filtered),
        "offset": offset,
        "limit": limit,
        "speakers": list(speakers.values()),
        "segments": [_segment_payload(s) for s in page],
    }


class SegmentEdit(BaseModel):
    text: str = Field(min_length=1, max_length=10000)

    @field_validator("text")
    @classmethod
    def strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Segment text cannot be empty")
        return value


async def _segment_for_edit(db: AsyncSession, meeting: Meeting, segment_id: uuid.UUID) -> TranscriptSegment:
    segment = await db.get(TranscriptSegment, segment_id)
    if segment is None or segment.meeting_id != meeting.id:
        raise HTTPException(status_code=404, detail="Transcript segment not found")
    return segment


async def _apply_text(db: AsyncSession, meeting: Meeting, segment: TranscriptSegment, text: str, user: User) -> None:
    if text == segment.text:
        return
    segments = await transcript_service.load_segments(db, meeting.id)
    old = segment.text
    segment.text = text
    segment.revision = (segment.revision or 1) + 1
    segment.edited_at = datetime.datetime.now(datetime.UTC) if text != segment.original_text else None
    segment.edited_by = user.id if segment.edited_at else None
    await _bump_revision(db, meeting, segments)
    db.add(
        TranscriptEdit(
            meeting_id=meeting.id, segment_id=segment.id, field="text", old_value=old, new_value=text,
            transcript_revision=meeting.transcript_revision, edited_by=user.id,
        )
    )


@router.patch("/{meeting_id}/transcript/segments/{segment_id}")
async def edit_segment(
    meeting_id: uuid.UUID,
    segment_id: uuid.UUID,
    body: SegmentEdit,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Correct one segment's text. The original ASR text is kept, the edit is
    logged, the transcript revision moves on (so current AI notes show as
    stale), and search is re-indexed from the corrected text."""
    meeting = await _readable_meeting(db, user, meeting_id)
    segment = await _segment_for_edit(db, meeting, segment_id)
    previous_text = segment.text
    await _apply_text(db, meeting, segment, body.text, user)
    await db.flush()
    corrections, _ = await vocabulary_service.correct_from_edit(db, meeting.id, [(previous_text, segment.text)], user)
    await db.commit()
    background_tasks.add_task(meeting_pipeline.reindex_after_edit, meeting.id)
    return {
        **_segment_payload(segment),
        "transcript_revision": meeting.transcript_revision,
        "insights_stale": _stale(meeting),
        "learned_corrections": corrections,
    }


@router.post("/{meeting_id}/transcript/segments/{segment_id}/revert")
async def revert_segment(
    meeting_id: uuid.UUID,
    segment_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    meeting = await _readable_meeting(db, user, meeting_id)
    segment = await _segment_for_edit(db, meeting, segment_id)
    await _apply_text(db, meeting, segment, segment.original_text, user)
    await db.commit()
    background_tasks.add_task(meeting_pipeline.reindex_after_edit, meeting.id)
    return {**_segment_payload(segment), "transcript_revision": meeting.transcript_revision, "insights_stale": _stale(meeting)}


class SpeakerNames(BaseModel):
    # speaker_key -> display name; an empty string returns to the generic label.
    names: dict[str, str] = Field(max_length=100)


@router.put("/{meeting_id}/transcript/speakers")
async def rename_speakers(
    meeting_id: uuid.UUID,
    body: SpeakerNames,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Name diarized speakers. Diarization only says *that* someone else is
    talking; a person establishes *who* — so this is the only path from
    "Speaker 2" to a name."""
    meeting = await _readable_meeting(db, user, meeting_id)
    segments = await transcript_service.ensure_segments(db, meeting)
    keys = {s.speaker_key for s in segments}
    changes: dict[str, str | None] = {}
    for key, raw in body.names.items():
        if key not in keys:
            raise HTTPException(status_code=422, detail=f"Unknown speaker: {key}")
        label = raw.strip()[:120] or None
        current = next(s.speaker_label for s in segments if s.speaker_key == key)
        if label != current:
            changes[key] = label
    if not changes:
        return {"changed": 0, "transcript_revision": meeting.transcript_revision}
    for segment in segments:
        if segment.speaker_key in changes:
            segment.speaker_label = changes[segment.speaker_key]
    await _bump_revision(db, meeting, segments)
    for key, label in changes.items():
        db.add(
            TranscriptEdit(
                meeting_id=meeting.id, segment_id=None, field="speaker",
                old_value=transcript_service.generic_label(key), new_value=label or transcript_service.generic_label(key),
                transcript_revision=meeting.transcript_revision, edited_by=user.id,
            )
        )
    # Keep the recording's own speaker map (used by its diarization panel)
    # consistent with what people see in the transcript.
    recording = await _recording_for(db, meeting.id)
    if recording is not None:
        from app.routes.recordings import _load_speaker_names, _session_dir

        directory = _session_dir(recording.id)
        names = _load_speaker_names(directory)
        for key, label in changes.items():
            if key.isdigit():
                if label:
                    names[key] = label
                else:
                    names.pop(key, None)
        (directory / "speaker_names.json").write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    await db.commit()
    background_tasks.add_task(meeting_pipeline.reindex_after_edit, meeting.id)
    return {"changed": len(changes), "transcript_revision": meeting.transcript_revision, "insights_stale": _stale(meeting)}


@router.get("/{meeting_id}/transcript/history")
async def transcript_history(
    meeting_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    meeting = await _readable_meeting(db, user, meeting_id)
    rows = (
        await db.execute(
            select(TranscriptEdit, User.name, TranscriptSegment.seq)
            .outerjoin(User, User.id == TranscriptEdit.edited_by)
            .outerjoin(TranscriptSegment, TranscriptSegment.id == TranscriptEdit.segment_id)
            .where(TranscriptEdit.meeting_id == meeting.id)
            .order_by(TranscriptEdit.created_at.desc())
            .limit(200)
        )
    ).all()
    return [
        {
            "id": str(edit.id),
            "field": edit.field,
            "segment_id": str(edit.segment_id) if edit.segment_id else None,
            "seq": seq,
            "old_value": edit.old_value,
            "new_value": edit.new_value,
            "transcript_revision": edit.transcript_revision,
            "edited_by": name,
            "created_at": _iso(edit.created_at),
        }
        for edit, name, seq in rows
    ]


@router.post("/{meeting_id}/transcript/use-recording")
async def use_recording_transcript(
    meeting_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Switch to the recording's timestamped, diarized transcript (e.g. for a
    Chrome-extension meeting stored from captions). Speakers become generic
    labels until named; text corrections to the old transcript do not carry
    over, which is why the UI asks first."""
    meeting = await _readable_meeting(db, user, meeting_id)
    recording = await _recording_for(db, meeting.id)
    if recording is None:
        raise HTTPException(status_code=409, detail="This meeting has no recording")
    dicts = transcript_service._recording_segments(recording.id)
    if not dicts:
        raise HTTPException(status_code=409, detail="The recording has not been analyzed yet")
    segments = await transcript_service.replace_segments(db, meeting, dicts)
    await insight_service.reanchor_evidence(db, meeting.id, segments)
    meeting.transcript_revision = (meeting.transcript_revision or 1) + 1
    db.add(
        TranscriptEdit(
            meeting_id=meeting.id, field="source", old_value="previous transcript",
            new_value="recording diarization", transcript_revision=meeting.transcript_revision, edited_by=user.id,
        )
    )
    await db.commit()
    background_tasks.add_task(meeting_pipeline.reindex_after_edit, meeting.id)
    return {"segments": len(segments), "transcript_revision": meeting.transcript_revision}


@router.get("/{meeting_id}/transcript/export")
async def export_transcript(
    meeting_id: uuid.UUID,
    format: str = Query("txt", pattern="^(txt|md|json|srt|vtt)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    meeting = await _readable_meeting(db, user, meeting_id)
    segments = await transcript_service.ensure_segments(db, meeting)
    await db.commit()
    if not segments:
        raise HTTPException(status_code=409, detail="This meeting has no transcript yet")
    try:
        content, media_type, extension = transcript_service.export(meeting, segments, format)
    except transcript_service.ExportUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error))
    filename = (re.sub(r"[^a-zA-Z0-9._ -]+", "", meeting.title).strip() or "meeting").replace(" ", "-")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}-transcript.{extension}"', "Cache-Control": "no-store"},
    )


# --- insights ------------------------------------------------------------------------


class RegenerateRequest(BaseModel):
    template: str | None = None


@router.post("/{meeting_id}/insights/regenerate")
async def regenerate_insights(
    meeting_id: uuid.UUID,
    body: RegenerateRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Regenerate AI notes from the current transcript revision with the
    chosen template. Reviewed, edited, commented or hand-made items are kept."""
    meeting = await _readable_meeting(db, user, meeting_id)
    if body.template is not None and body.template not in ai_extractor.TEMPLATES:
        raise HTTPException(status_code=422, detail="Unknown template")
    current = await processing_service.get_stage(db, meeting.id, "extraction")
    if current is not None and current.status == "running":
        raise HTTPException(status_code=409, detail="Notes are already being generated")
    try:
        result = await insight_service.regenerate(db, meeting, template=body.template, user=user)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"AI notes could not be generated: {str(error)[:200]}")
    background_tasks.add_task(meeting_pipeline.index, meeting.id)
    return result


@router.get("/{meeting_id}/insights/runs")
async def insight_runs(
    meeting_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    meeting = await _readable_meeting(db, user, meeting_id)
    runs = (
        await db.execute(
            select(InsightRun).where(InsightRun.meeting_id == meeting.id).order_by(InsightRun.started_at.desc()).limit(20)
        )
    ).scalars().all()
    return [
        {
            "id": str(run.id),
            "status": run.status,
            "template": run.template,
            "model": run.model,
            "prompt_version": run.prompt_version,
            "transcript_revision": run.transcript_revision,
            "chunk_count": run.chunk_count,
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "evidence_checked": run.evidence_checked,
            "evidence_rejected": run.evidence_rejected,
            "error": run.error,
            "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at),
        }
        for run in runs
    ]


@router.get("/{meeting_id}/analytics")
async def meeting_analytics(
    meeting_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Deterministic, evidence-based numbers only — no sentiment, no
    judgement of people. Cost is an estimate from configured rates."""
    meeting = await _readable_meeting(db, user, meeting_id)
    segments = await transcript_service.ensure_segments(db, meeting)
    await db.commit()
    talk = transcript_service.talk_time(segments)

    task_rows = (
        await db.execute(
            select(MeetingTask.status, func.count())
            .where(MeetingTask.meeting_id == meeting.id, MeetingTask.deleted_at.is_(None))
            .group_by(MeetingTask.status)
        )
    ).all()
    decisions = await db.scalar(select(func.count()).select_from(Decision).where(Decision.meeting_id == meeting.id, Decision.deleted_at.is_(None)))
    risks = await db.scalar(select(func.count()).select_from(Risk).where(Risk.meeting_id == meeting.id, Risk.deleted_at.is_(None)))
    insight = await db.get(MeetingInsight, meeting.id)
    topics = [
        {
            "title": section.get("title"),
            "start_ms": (section.get("evidence") or [{}])[0].get("start_ms") if section.get("evidence") else None,
            "segment_count": len(section.get("evidence") or []),
        }
        for section in (insight.sections or [] if insight else [])
    ]

    runs = (await db.execute(select(InsightRun).where(InsightRun.meeting_id == meeting.id))).scalars().all()
    traces = (await db.execute(select(Trace).where(Trace.meeting_id == meeting.id))).scalars().all()
    transcription_requests = sum(t.transcription_requests or 0 for t in traces)
    input_tokens = sum(r.input_tokens for r in runs)
    output_tokens = sum(r.output_tokens for r in runs)
    stages = await processing_service.list_stages(db, meeting.id)
    latency = {
        stage["stage"]: (
            (datetime.datetime.fromisoformat(stage["finished_at"]) - datetime.datetime.fromisoformat(stage["started_at"])).total_seconds()
            if stage["started_at"] and stage["finished_at"]
            else None
        )
        for stage in stages
    }
    audio_minutes = (talk["transcript_span_seconds"] or meeting.duration_minutes * 60 or 0) / 60
    rates_configured = any(
        (settings.transcription_usd_per_minute, settings.ai_usd_per_million_input_tokens, settings.ai_usd_per_million_output_tokens)
    )
    estimated_cost = (
        round(
            (audio_minutes * settings.transcription_usd_per_minute if transcription_requests else 0)
            + input_tokens / 1_000_000 * settings.ai_usd_per_million_input_tokens
            + output_tokens / 1_000_000 * settings.ai_usd_per_million_output_tokens,
            4,
        )
        if rates_configured
        else None
    )
    notes = []
    if talk["timed"]:
        notes.append("Speaking time sums each speaker's own turns; overlapping speech is credited to every speaker involved, so totals can exceed the meeting length.")
    else:
        notes.append("This transcript has no timestamps, so participation is measured in words rather than time.")
    if meeting.source == "record":
        notes.append("Recorded from one microphone: quiet or distant voices may be under-represented.")
    capture_gaps = next((s for s in stages if s["stage"] in {"audio", "transcription"} and s["status"] == "failed"), None)
    if capture_gaps:
        notes.append("Part of the processing failed, so these numbers may be incomplete.")
    return {
        "talk_time": talk,
        "tasks": {"total": sum(count for _, count in task_rows), "by_status": {status or "pending": count for status, count in task_rows}},
        "decisions": decisions or 0,
        "risks": risks or 0,
        "topics": topics,
        "usage": {
            "transcription_requests": transcription_requests,
            "ai_input_tokens": input_tokens,
            "ai_output_tokens": output_tokens,
            "insight_runs": len(runs),
            "estimated_cost_usd": estimated_cost,
        },
        "stage_seconds": latency,
        "notes": notes,
    }


# --- comments & bookmarks -------------------------------------------------------------


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    segment_id: uuid.UUID | None = None


async def _anchor(db: AsyncSession, meeting: Meeting, segment_id: uuid.UUID | None) -> TranscriptSegment | None:
    if segment_id is None:
        return None
    segment = await db.get(TranscriptSegment, segment_id)
    if segment is None or segment.meeting_id != meeting.id:
        raise HTTPException(status_code=422, detail="That transcript segment is not part of this meeting")
    return segment


@router.get("/{meeting_id}/comments")
async def list_comments(
    meeting_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    meeting = await _readable_meeting(db, user, meeting_id)
    rows = (
        await db.execute(
            select(MeetingComment, User.name)
            .outerjoin(User, User.id == MeetingComment.user_id)
            .where(MeetingComment.meeting_id == meeting.id)
            .order_by(MeetingComment.created_at)
        )
    ).all()
    return [
        {
            "id": str(comment.id),
            "body": comment.body,
            "segment_id": str(comment.segment_id) if comment.segment_id else None,
            "start_ms": comment.start_ms,
            "quote": comment.quote,
            "author": name or "Former member",
            "mine": comment.user_id == user.id,
            "created_at": _iso(comment.created_at),
        }
        for comment, name in rows
    ]


@router.post("/{meeting_id}/comments", status_code=201)
async def add_comment(
    meeting_id: uuid.UUID, body: CommentCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    meeting = await _readable_meeting(db, user, meeting_id)
    segment = await _anchor(db, meeting, body.segment_id)
    comment = MeetingComment(
        meeting_id=meeting.id,
        user_id=user.id,
        segment_id=segment.id if segment else None,
        start_ms=segment.start_ms if segment else None,
        quote=segment.text[:300] if segment else None,
        body=body.body.strip(),
    )
    db.add(comment)
    await db.commit()
    return {
        "id": str(comment.id), "body": comment.body, "segment_id": str(comment.segment_id) if comment.segment_id else None,
        "start_ms": comment.start_ms, "quote": comment.quote, "author": user.name, "mine": True, "created_at": _iso(comment.created_at),
    }


@router.delete("/{meeting_id}/comments/{comment_id}")
async def delete_comment(
    meeting_id: uuid.UUID, comment_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    meeting = await _readable_meeting(db, user, meeting_id)
    comment = await db.get(MeetingComment, comment_id)
    if comment is None or comment.meeting_id != meeting.id:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.user_id != user.id and not is_admin(user):
        raise HTTPException(status_code=403, detail="Only the author can delete this comment")
    await db.delete(comment)
    await db.commit()
    return {"ok": True}


class BookmarkCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    segment_id: uuid.UUID | None = None
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)


@router.get("/{meeting_id}/bookmarks")
async def list_bookmarks(
    meeting_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    meeting = await _readable_meeting(db, user, meeting_id)
    rows = (
        await db.execute(
            select(MeetingBookmark, User.name)
            .outerjoin(User, User.id == MeetingBookmark.user_id)
            .where(MeetingBookmark.meeting_id == meeting.id)
            .order_by(MeetingBookmark.start_ms.nulls_last(), MeetingBookmark.created_at)
        )
    ).all()
    return [
        {
            "id": str(b.id), "label": b.label, "segment_id": str(b.segment_id) if b.segment_id else None,
            "start_ms": b.start_ms, "end_ms": b.end_ms, "author": name or "Former member",
            "mine": b.user_id == user.id, "created_at": _iso(b.created_at),
        }
        for b, name in rows
    ]


@router.post("/{meeting_id}/bookmarks", status_code=201)
async def add_bookmark(
    meeting_id: uuid.UUID, body: BookmarkCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    meeting = await _readable_meeting(db, user, meeting_id)
    segment = await _anchor(db, meeting, body.segment_id)
    start_ms = body.start_ms if body.start_ms is not None else (segment.start_ms if segment else None)
    end_ms = body.end_ms if body.end_ms is not None else (segment.end_ms if segment else None)
    if start_ms is not None and end_ms is not None and end_ms < start_ms:
        raise HTTPException(status_code=422, detail="A clip must end after it starts")
    bookmark = MeetingBookmark(
        meeting_id=meeting.id, user_id=user.id, segment_id=segment.id if segment else None,
        label=body.label.strip(), start_ms=start_ms, end_ms=end_ms,
    )
    db.add(bookmark)
    await db.commit()
    return {
        "id": str(bookmark.id), "label": bookmark.label, "segment_id": str(bookmark.segment_id) if bookmark.segment_id else None,
        "start_ms": bookmark.start_ms, "end_ms": bookmark.end_ms, "author": user.name, "mine": True, "created_at": _iso(bookmark.created_at),
    }


@router.delete("/{meeting_id}/bookmarks/{bookmark_id}")
async def delete_bookmark(
    meeting_id: uuid.UUID, bookmark_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    meeting = await _readable_meeting(db, user, meeting_id)
    bookmark = await db.get(MeetingBookmark, bookmark_id)
    if bookmark is None or bookmark.meeting_id != meeting.id:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    if bookmark.user_id != user.id and not is_admin(user):
        raise HTTPException(status_code=403, detail="Only the person who added this bookmark can delete it")
    await db.delete(bookmark)
    await db.commit()
    return {"ok": True}


# --- meeting prep -------------------------------------------------------------------


class PrepRequest(BaseModel):
    attendee_user_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    agenda: str = Field(default="", max_length=4000)
    include_brief: bool = True


@router.post("/prep")
@limiter.limit("10/minute")
async def meeting_prep(
    request: Request, body: PrepRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """A brief for an upcoming meeting with these colleagues, built only from
    meetings the caller can read. People are matched by account id — never
    by a shared name."""
    ctx = await prep_service.gather(db, user, body.attendee_user_ids)
    result = {**prep_service.serialize(ctx), "brief": None, "brief_error": None}
    if ctx.empty:
        result["brief_error"] = "No earlier meetings you can access include these people."
        return result
    if not body.include_brief:
        return result
    try:
        result["brief"] = await prep_service.write_brief(ctx, body.agenda, feature="meeting_prep")
    except Exception as error:
        logger.exception("Meeting prep brief failed")
        result["brief_error"] = f"The AI brief is unavailable: {str(error)[:200]}"
    return result
