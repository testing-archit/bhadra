"""Background processing for uploaded recordings and stage retries.

Each stage reads its inputs from durable storage (the stored audio file, the
stored segments), records its outcome in `meeting_processing_stages`, and is
skipped when it already succeeded — so a retry resumes at the failed stage and
never pays for a second transcription of the same audio. Every stage re-reads
the meeting first and stops if it has been deleted (the tombstone check that
keeps a slow job from resurrecting deleted data).
"""

import asyncio
import json
import logging
import uuid

from app.database.db import async_session
from app.database.models import Meeting, RecordingSession, Trace
from app.services import followup_service, insight_service, jira_service, processing_service, transcriber, transcript_service, vocabulary_service
from app.services.meeting_index_service import rebuild_meeting_index
from app.services import usage_ledger

logger = logging.getLogger(__name__)


async def _live_meeting(db, meeting_id: uuid.UUID) -> Meeting | None:
    meeting = await db.get(Meeting, meeting_id)
    return meeting if meeting is not None and meeting.deleted_at is None else None


async def _stage_status(meeting_id: uuid.UUID, stage: str) -> str | None:
    async with async_session() as db:
        row = await processing_service.get_stage(db, meeting_id, stage)
        return row.status if row else None


async def transcribe_recording(meeting_id: uuid.UUID, recording_id: uuid.UUID) -> bool:
    from app.routes.recordings import _session_dir

    usage_ledger.attribute(meeting_id=meeting_id)
    async with async_session() as db:
        meeting = await _live_meeting(db, meeting_id)
        recording = await db.get(RecordingSession, recording_id)
        if meeting is None or recording is None:
            await processing_service.set_stage(meeting_id, "transcription", "skipped", error="Meeting was deleted")
            return False
        language = recording.language
        mime_type = recording.mime_type or "audio/webm"
        people = await vocabulary_service.meeting_people(db, meeting_id) + list(recording.participants or [])
    directory = _session_dir(recording_id)
    audio_path = directory / "recording.webm"
    await processing_service.set_stage(meeting_id, "transcription", "running")
    try:
        detailed = await transcriber.transcribe_audio_detailed(
            await asyncio.to_thread(audio_path.read_bytes), mime_type, language, people=people
        )
        if not detailed["turns"]:
            raise RuntimeError("No speech was recognized in this recording")
    except Exception as error:
        logger.exception("Transcription failed for meeting %s", meeting_id)
        await processing_service.set_stage(meeting_id, "transcription", "failed", error=error)
        return False

    # The diarization file doubles as the recording's cache, so the speaker
    # panel works and a later re-analysis is an explicit, separate choice.
    (directory / "recording.diarization.json").write_text(json.dumps(detailed, ensure_ascii=False), encoding="utf-8")
    (directory / "recording.txt").write_text(detailed["transcript"], encoding="utf-8")
    async with async_session() as db:
        meeting = await _live_meeting(db, meeting_id)
        if meeting is None:
            await processing_service.set_stage(meeting_id, "transcription", "skipped", error="Meeting was deleted")
            return False
        await transcript_service.replace_segments(
            db, meeting, transcript_service.segments_from_turns(detailed["turns"]), language=language
        )
        duration = float((detailed.get("metadata") or {}).get("duration") or 0)
        if duration:
            meeting.duration_minutes = max(1, round(duration / 60))
            recording = await db.get(RecordingSession, recording_id)
            if recording is not None:
                recording.duration_seconds = int(duration)
        db.add(
            Trace(
                user_id=meeting.user_id,
                meeting_id=meeting.id,
                meeting_title=meeting.title,
                duration_minutes=meeting.duration_minutes,
                transcription_requests=1,
                ai_input_tokens=0,
                ai_output_tokens=0,
                ai_cache_hits=0,
                status="success",
            )
        )
        await db.commit()
    await processing_service.set_stage(
        meeting_id,
        "transcription",
        "succeeded",
        detail={"segments": len(detailed["turns"]), "duration_seconds": duration, "provider": (detailed.get("metadata") or {}).get("diarizer")},
    )
    return True


async def extract(meeting_id: uuid.UUID, template: str | None, *, adopt_title: bool = False) -> bool:
    usage_ledger.attribute(meeting_id=meeting_id)
    if template == "auto":
        from app.services import series_service

        async with async_session() as db:
            meeting = await _live_meeting(db, meeting_id)
            template = await series_service.resolve_template(db, meeting.series_key if meeting else None, (meeting.transcript or "") if meeting else "")
            if meeting is not None:
                meeting.template = template
                await db.commit()
    async with async_session() as db:
        meeting = await _live_meeting(db, meeting_id)
        if meeting is None:
            return False
        try:
            await insight_service.regenerate(db, meeting, template=template, user=None, adopt_title=adopt_title)
        except Exception:
            # regenerate() already recorded the failed stage and run.
            logger.exception("Extraction failed for meeting %s", meeting_id)
            return False
    await followup_service.announce_notes(meeting_id)
    await followup_service.notify_task_owners(meeting_id)
    await jira_service.auto_send(meeting_id)
    await vocabulary_service.learn_from_meeting(meeting_id)
    return True


async def index(meeting_id: uuid.UUID) -> bool:
    await processing_service.set_stage(meeting_id, "indexing", "running")
    try:
        async with async_session() as db:
            # rebuild_meeting_index deletes the index for a deleted meeting,
            # so a late index job can never resurrect one.
            await rebuild_meeting_index(db, meeting_id, strict=True)
    except Exception as error:
        logger.exception("Indexing failed for meeting %s", meeting_id)
        await processing_service.set_stage(meeting_id, "indexing", "failed", error=error)
        return False
    await processing_service.set_stage(meeting_id, "indexing", "succeeded")
    return True


async def run_upload_pipeline(
    meeting_id: uuid.UUID,
    recording_id: uuid.UUID,
    template: str | None,
    *,
    adopt_title: bool,
) -> None:
    """transcription → extraction → indexing, skipping stages already done."""
    async with processing_service.pipeline_slots():
        transcribed_now = False
        if await _stage_status(meeting_id, "transcription") != "succeeded":
            if not await transcribe_recording(meeting_id, recording_id):
                return
            transcribed_now = True
        # A fresh transcript makes any earlier notes (e.g. ones made from
        # Meet captions after a transcription outage) out of date.
        if transcribed_now or await _stage_status(meeting_id, "extraction") != "succeeded":
            # Indexing still runs on failure: the transcript is searchable
            # even when the AI notes are not available.
            await extract(meeting_id, template, adopt_title=adopt_title)
        await index(meeting_id)


async def diarize(meeting_id: uuid.UUID, recording_id: uuid.UUID) -> None:
    from app.routes.recordings import _diarize_full_recording, _session_dir

    async with processing_service.pipeline_slots():
        async with async_session() as db:
            recording = await db.get(RecordingSession, recording_id)
            if recording is None or await _live_meeting(db, meeting_id) is None:
                return
        await processing_service.set_stage(meeting_id, "diarization", "running")
        try:
            await _diarize_full_recording(recording, _session_dir(recording_id))
        except Exception as error:
            logger.exception("Diarization retry failed for meeting %s", meeting_id)
            await processing_service.set_stage(meeting_id, "diarization", "failed", error=error)
            return
        await processing_service.set_stage(meeting_id, "diarization", "succeeded")


async def reindex_after_edit(meeting_id: uuid.UUID) -> None:
    """Search must reflect a correction promptly; failure is recorded as an
    indexing stage the user can retry."""
    await index(meeting_id)
