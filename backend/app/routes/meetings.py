import asyncio
import datetime
import json
import logging
import re
import secrets
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.db import async_session, get_db
from app.database.models import (
    AdminAuditEvent,
    Decision,
    Meeting,
    MeetingAttendee,
    MeetingInsight,
    MeetingTask,
    ProcessingStage,
    Project,
    RecordingSession,
    Risk,
    Trace,
    TranscriptSegment,
    User,
    meeting_projects,
)
from app.dependencies import (
    department_scope,
    get_current_user,
    is_admin,
    meeting_visibility_clause,
    user_can_manage_meeting_access,
    user_can_read_meeting,
    visible_meeting_ids,
)
from app.rate_limit import limiter
from app.routes.recordings import _diarize_full_recording, _session_dir
from app.services import (
    ai_extractor,
    series_service,
    attendee_service,
    contradiction_service,
    followup_service,
    insight_service,
    jira_service,
    pdf_service,
    privacy_service,
    processing_service,
    qdrant_service,
    sheets_service,
    standup_service,
    transcriber,
    transcript_service,
    usage_ledger,
    vocabulary_service,
)
from app.services.meeting_index_service import rebuild_meeting_index

router = APIRouter(prefix="/api/meetings", tags=["meetings"])
logger = logging.getLogger(__name__)
MANUAL_TASKS_MEETING_TITLE = "Manually Added Tasks"  # tasks.MANUAL_TASKS_MEETING_TITLE
MAX_AUDIO_BYTES = 100 * 1024 * 1024
SUPPORTED_LANGUAGES = {"en", "hi", "hinglish", "auto"}
MEETING_SOURCES = {"extension", "upload", "paste", "record", "bot", "capture"}


class UpdateMeetingProjectsRequest(BaseModel):
    project_ids: list[uuid.UUID] = Field(default_factory=list)


class AttendeeInput(BaseModel):
    user_id: uuid.UUID | None = None
    name: str = Field(default="", max_length=200)
    email: str | None = Field(default=None, max_length=320)
    # Lets a full-list save keep "was in the call, not shared yet" people
    # pending instead of silently granting them access.
    access: str | None = Field(default=None, pattern="^(granted|pending)$")


class UpdateAttendeesRequest(BaseModel):
    attendees: list[AttendeeInput] = Field(default_factory=list, max_length=100)


class AccessChange(BaseModel):
    access: str = Field(pattern="^(granted|pending)$")


class ShareRequest(BaseModel):
    user_id: uuid.UUID


class UpdateMeetingTitleRequest(BaseModel):
    title: str = Field(max_length=160)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Meeting title is required")
        return value


class UpdateMeetingSummaryRequest(BaseModel):
    summary: str = Field(max_length=30000)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Summary is required")
        return value


class UpdateRiskRequest(BaseModel):
    description: str = Field(max_length=4000)
    severity: str | None = Field(default=None, max_length=40)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Risk description is required")
        return value


def _fallback_title(transcript: str) -> str:
    first_line = next((line.strip() for line in transcript.splitlines() if line.strip()), "")
    if ":" in first_line:
        first_line = first_line.split(":", 1)[1].strip()
    words = first_line.rstrip(".!?").split()[:8]
    return " ".join(words).strip().capitalize() or "Recorded meeting"


async def _enrich_meeting_after_ingest(
    meeting_id: uuid.UUID,
    meeting_title: str,
    meeting_date: str,
    transcript: str,
    extraction: dict,
    department: str | None,
    decision_checks: list[tuple[uuid.UUID, str]],
) -> None:
    started = time.perf_counter()
    # Past decisions are only compared from meetings the recorder can read
    # that aren't confidential: the note quotes them to this meeting's readers.
    candidate_ids: list[str] = []
    if decision_checks:
        async with async_session() as db:
            meeting = await db.get(Meeting, meeting_id)
            owner = await db.get(User, meeting.user_id) if meeting is not None else None
            if owner is not None:
                candidate_ids = [
                    str(value)
                    for value in (
                        await db.execute(
                            visible_meeting_ids(owner).where(Meeting.confidential.is_(False), Meeting.id != meeting_id)
                        )
                    ).scalars().all()
                ]

    async def check_decision(decision_id: uuid.UUID, text: str):
        try:
            result = await asyncio.to_thread(
                contradiction_service.check_for_contradiction, text, department, meeting_ids=candidate_ids
            )
            return decision_id, result
        except Exception:
            logger.exception("Background contradiction check failed for decision %s", decision_id)
            return decision_id, {"note": None, "usage": None}

    checks = await asyncio.gather(
        *(check_decision(decision_id, text) for decision_id, text in decision_checks)
    )
    if checks:
        async with async_session() as db:
            for decision_id, result in checks:
                decision = await db.get(Decision, decision_id)
                if decision:
                    decision.conflict_note = result["note"]
            await db.commit()

    await processing_service.set_stage(meeting_id, "indexing", "running")
    try:
        await asyncio.to_thread(
            qdrant_service.upsert_meeting,
            str(meeting_id),
            meeting_title,
            meeting_date,
            extraction["summary"],
            transcript,
            extraction["decisions"],
            extraction["tasks"],
            department,
            extraction["risks"],
        )
        await processing_service.set_stage(meeting_id, "indexing", "succeeded")
    except Exception as error:
        logger.exception("Meeting %s saved without Qdrant indexing", meeting_id)
        await processing_service.set_stage(meeting_id, "indexing", "failed", error=error)
    logger.info("Meeting %s background enrichment finished in %.2fs", meeting_id, time.perf_counter() - started)


def _concat_webm_chunks(chunk_paths: list[Path], output_path: Path) -> None:
    if len(chunk_paths) == 1:
        output_path.write_bytes(chunk_paths[0].read_bytes())
        return
    concat_list = output_path.parent / f"{output_path.stem}_concat.txt"
    concat_list.write_text("".join(f"file '{path.name}'\n" for path in chunk_paths), encoding="utf-8")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list.name,
                "-c:a", "libopus", "-b:a", "48k", output_path.name,
            ],
            cwd=output_path.parent, check=True, capture_output=True,
        )
    finally:
        concat_list.unlink(missing_ok=True)


def _assemble_meeting_audio(staging_dir: Path, output_path: Path) -> None:
    """Reassemble the extension's separately-recorded tab/mic chunk streams
    into one playable file. Chrome captures the Meet tab and the user's own
    microphone as two independent MediaRecorder streams (so each can be
    transcribed cleanly); for playback they need to be mixed back together.
    """
    tab_chunks = sorted(staging_dir.glob("*_tab.webm"))
    mic_chunks = sorted(staging_dir.glob("*_mic.webm"))
    if not tab_chunks and not mic_chunks:
        raise RuntimeError("No staged audio chunks found")

    tab_path = staging_dir / "tab_full.webm"
    mic_path = staging_dir / "mic_full.webm"
    if tab_chunks:
        _concat_webm_chunks(tab_chunks, tab_path)
    if mic_chunks:
        _concat_webm_chunks(mic_chunks, mic_path)

    if tab_chunks and mic_chunks:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(tab_path), "-i", str(mic_path),
                "-filter_complex", "amix=inputs=2:duration=longest:dropout_transition=0",
                "-c:a", "libopus", "-b:a", "48k", str(output_path),
            ],
            check=True, capture_output=True,
        )
    else:
        (tab_path if tab_chunks else mic_path).replace(output_path)


async def _process_meeting_audio(
    meeting_id: uuid.UUID,
    client_meeting_id: str,
    user_id: uuid.UUID,
    meeting_title: str,
    meeting_language: str,
    duration_minutes: int,
) -> None:
    staging_root = Path(settings.recordings_dir).resolve() / "meeting_audio_staging"
    staging_dir = (staging_root / client_meeting_id).resolve()
    # client_meeting_id comes from the client: never let it point outside
    # the staging area (an absolute path or "../" would, and the folder is
    # deleted once its audio is assembled).
    if staging_dir.parent != staging_root or not staging_dir.is_dir():
        return
    assembly_succeeded = False
    await processing_service.set_stage(meeting_id, "audio", "running")
    try:
        async with async_session() as db:
            recording = RecordingSession(
                user_id=user_id,
                meeting_id=meeting_id,
                title=meeting_title,
                meeting_type="online",
                language=meeting_language,
                status="processed",
                mime_type="audio/webm",
                duration_seconds=max(0, duration_minutes * 60),
            )
            db.add(recording)
            await db.commit()
            await db.refresh(recording)

            directory = _session_dir(recording.id)
            output_path = directory / "recording.webm"
            await asyncio.to_thread(_assemble_meeting_audio, staging_dir, output_path)
            recording.total_bytes = output_path.stat().st_size
            await db.commit()
            assembly_succeeded = True

        await processing_service.set_stage(meeting_id, "audio", "succeeded")
        # Provider transcription can take a while on a multi-hour meeting and
        # touches no database rows itself — run it after the session above
        # closes rather than holding a Postgres connection open for it. The
        # caption-named transcript stays as is; people can switch to the
        # timestamped one from the meeting page.
        await processing_service.set_stage(meeting_id, "diarization", "running")
        try:
            await _diarize_full_recording(recording, directory)
            await processing_service.set_stage(meeting_id, "diarization", "succeeded")
        except Exception as error:
            logger.exception("Diarization failed for Meet recording %s; audio playback still saved", recording.id)
            await processing_service.set_stage(meeting_id, "diarization", "failed", error=error)
    except Exception as error:
        logger.exception("Could not assemble Meet audio for meeting %s", meeting_id)
        if not assembly_succeeded:
            await processing_service.set_stage(meeting_id, "audio", "failed", error=error)
    finally:
        # A failed assembly must not destroy the only remaining raw copy.
        if assembly_succeeded:
            shutil.rmtree(staging_dir, ignore_errors=True)


@router.get("")
async def list_meetings(
    q: str | None = None,
    project_id: uuid.UUID | None = None,
    attendee_id: uuid.UUID | None = None,
    source: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = (
        select(
            Meeting,
            func.count(func.distinct(MeetingTask.id)),
            func.count(func.distinct(Decision.id)),
        )
        .outerjoin(MeetingTask, and_(MeetingTask.meeting_id == Meeting.id, MeetingTask.deleted_at.is_(None)))
        .outerjoin(Decision, and_(Decision.meeting_id == Meeting.id, Decision.deleted_at.is_(None)))
        .where(
            Meeting.deleted_at.is_(None),
            # The per-person holder for hand-added tasks isn't a meeting.
            ~and_(Meeting.title == MANUAL_TASKS_MEETING_TITLE, Meeting.source.is_(None)),
        )
        .group_by(Meeting.id)
        .order_by(Meeting.date.desc())
        .options(selectinload(Meeting.projects))
    )
    visibility = meeting_visibility_clause(user)
    if visibility is not None:
        query = query.where(visibility)

    if q:
        pattern = f"%{q}%"
        query = query.where(
            or_(
                Meeting.title.ilike(pattern),
                Meeting.summary.ilike(pattern),
                Meeting.transcript.ilike(pattern),
            )
        )
    if project_id:
        query = query.where(
            Meeting.id.in_(
                select(meeting_projects.c.meeting_id).where(
                    meeting_projects.c.project_id == project_id
                )
            )
        )
    if attendee_id:
        # Layered on top of the visibility clause, never instead of it: this
        # narrows what you already have access to, it cannot widen it.
        query = query.where(
            Meeting.id.in_(
                select(MeetingAttendee.meeting_id).where(MeetingAttendee.user_id == attendee_id)
            )
        )

    if source:
        query = query.where(Meeting.source == source)
    if date_from:
        query = query.where(Meeting.date >= datetime.datetime.combine(date_from, datetime.time.min, datetime.UTC))
    if date_to:
        query = query.where(Meeting.date < datetime.datetime.combine(date_to + datetime.timedelta(days=1), datetime.time.min, datetime.UTC))

    result = await db.execute(query)
    rows = result.all()

    stage_rows = []
    if rows:
        stage_rows = (
            await db.execute(
                select(ProcessingStage.meeting_id, ProcessingStage.status).where(
                    ProcessingStage.meeting_id.in_([meeting.id for meeting, _, _ in rows])
                )
            )
        ).all()
    processing: dict[uuid.UUID, str] = {}
    for meeting_id, status in stage_rows:
        if status in {"pending", "running"}:
            processing[meeting_id] = "processing"
        elif status == "failed" and processing.get(meeting_id) != "processing":
            processing[meeting_id] = "attention"

    attendees_by_meeting: dict[uuid.UUID, list[dict]] = {}
    if rows:
        attendee_rows = (
            await db.execute(
                select(MeetingAttendee)
                .where(MeetingAttendee.meeting_id.in_([meeting.id for meeting, _, _ in rows]))
                .order_by(MeetingAttendee.kind, MeetingAttendee.display_name)
            )
        ).scalars().all()
        for row in attendee_rows:
            attendees_by_meeting.setdefault(row.meeting_id, []).append(attendee_service.serialize(row))

    return [
        {
            "id": str(meeting.id),
            "title": meeting.title,
            "date": meeting.date.isoformat(),
            "duration_minutes": meeting.duration_minutes,
            "summary": meeting.summary,
            "task_count": task_count,
            "decision_count": decision_count,
            "source": meeting.source,
            "processing_state": processing.get(meeting.id, "ready"),
            "attendees": attendees_by_meeting.get(meeting.id, []),
            "projects": [
                {"id": str(project.id), "name": project.name}
                for project in meeting.projects
                if project.deleted_at is None
            ],
        }
        for meeting, task_count, decision_count in rows
    ]


@router.get("/{meeting_id}")
async def get_meeting(
    meeting_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Meeting)
        .options(
            selectinload(Meeting.tasks).selectinload(MeetingTask.project),
            selectinload(Meeting.decisions).selectinload(Decision.project),
            selectinload(Meeting.risks).selectinload(Risk.project),
            selectinload(Meeting.projects),
        )
        .where(Meeting.id == meeting_id, Meeting.deleted_at.is_(None))
    )
    meeting = result.scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if not await user_can_read_meeting(db, user, meeting.id):
        raise HTTPException(status_code=404, detail="Meeting not found")

    insight = await db.get(MeetingInsight, meeting.id)
    recording_result = await db.execute(
        select(RecordingSession).where(RecordingSession.meeting_id == meeting.id).limit(1)
    )
    recording = recording_result.scalar_one_or_none()

    attendees = await attendee_service.list_for_meeting(db, meeting.id)
    own_access = meeting.user_id == user.id or any(
        row["user_id"] == str(user.id) and row["access"] == "granted" for row in attendees
    )
    live_tasks = [t for t in meeting.tasks if t.deleted_at is None]
    inside = await privacy_service.owners_in_meeting(db, live_tasks)
    return {
        "id": str(meeting.id),
        "attendees": attendees,
        "confidential": meeting.confidential,
        "confidential_source": meeting.confidential_source,
        "confidential_reason": meeting.confidential_reason,
        # Anyone in it can mark it; only the recorder or organizer can unmark.
        "can_unmark_confidential": user.id in (meeting.user_id, meeting.organizer_user_id),
        # Who decides who else may read it: the recorder, the calendar
        # organizer and Charcha admins.
        "can_manage_access": await user_can_manage_meeting_access(db, user, meeting),
        # True when the viewer only sees this because they are an admin.
        "viewing_as_admin": not own_access and is_admin(user),
        "title": meeting.title,
        "date": meeting.date.isoformat(),
        "duration_minutes": meeting.duration_minutes,
        "summary": meeting.summary,
        "summary_verified_at": meeting.summary_verified_at.isoformat() if meeting.summary_verified_at else None,
        "transcript": meeting.transcript,
        "source": meeting.source,
        "template": meeting.template,
        "transcript_revision": meeting.transcript_revision,
        "insights_revision": meeting.insights_revision,
        "insights_stale": meeting.insights_revision is not None and meeting.insights_revision < meeting.transcript_revision,
        "insights": {
            "key_topics": insight.key_topics or [],
            "open_questions": insight.open_questions or [],
            "highlights": insight.highlights or [],
            "next_steps": insight.next_steps or [],
            "speaker_activity": insight.speaker_activity or [],
            "overview": insight.overview,
            "sections": insight.sections or [],
            "template_sections": insight.template_sections or [],
            "follow_up_draft": insight.follow_up_draft,
        }
        if insight
        else None,
        "recording": {
            "id": str(recording.id),
            "meeting_type": recording.meeting_type,
            "participants": recording.participants or [],
            "duration_seconds": recording.duration_seconds,
            "total_bytes": recording.total_bytes,
        }
        if recording
        else None,
        "projects": [
            {"id": str(project.id), "name": project.name}
            for project in meeting.projects
            if project.deleted_at is None
        ],
        "tasks": [
            {
                "id": str(t.id),
                "owner": t.owner,
                "description": t.description,
                "deadline": t.deadline,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "priority": t.priority,
                "status": t.status,
                "parent_task_id": str(t.parent_task_id) if t.parent_task_id else None,
                "owner_user_id": str(t.owner_user_id) if t.owner_user_id else None,
                "evidence": t.evidence or [],
                "ai_flags": t.ai_flags or [],
                "origin": t.origin,
                "project": t.project.name if t.project and t.project.deleted_at is None else None,
                "project_id": str(t.project_id) if t.project and t.project.deleted_at is None else None,
                "verified_at": t.verified_at.isoformat() if t.verified_at else None,
                "jira_issue_key": t.jira_issue_key,
                "jira_status": t.jira_status,
                "jira_error": t.jira_error,
                "owner_access": privacy_service.owner_access(t, inside),
            }
            for t in live_tasks
        ],
        "risks": [
            {
                "id": str(r.id),
                "description": r.description,
                "severity": r.severity,
                "evidence": r.evidence or [],
                "ai_flags": r.ai_flags or [],
                "origin": r.origin,
                "project": r.project.name if r.project and r.project.deleted_at is None else None,
                "project_id": str(r.project_id) if r.project and r.project.deleted_at is None else None,
                "verified_at": r.verified_at.isoformat() if r.verified_at else None,
            }
            for r in meeting.risks
            if r.deleted_at is None
        ],
        "decisions": [
            {
                "id": str(d.id),
                "decision": d.decision,
                "reason": d.reason,
                "alternatives": d.alternatives or [],
                "participants": d.participants or [],
                "conflict_note": d.conflict_note,
                "evidence": d.evidence or [],
                "ai_flags": d.ai_flags or [],
                "origin": d.origin,
                "project": d.project.name if d.project and d.project.deleted_at is None else None,
                "project_id": str(d.project_id) if d.project and d.project.deleted_at is None else None,
                "verified_at": d.verified_at.isoformat() if d.verified_at else None,
            }
            for d in meeting.decisions
            if d.deleted_at is None
        ],
    }


@router.get("/{meeting_id}/attendees")
async def list_meeting_attendees(
    meeting_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    if not await user_can_read_meeting(db, user, meeting_id):
        raise HTTPException(status_code=404, detail="Meeting not found")
    return await attendee_service.list_for_meeting(db, meeting_id)


@router.put("/{meeting_id}/attendees")
async def set_meeting_attendees(
    meeting_id: uuid.UUID,
    body: UpdateAttendeesRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Replace the attendee list. Only the people who decide access — the
    recorder, the calendar organizer, or a Charcha admin — may do this, since
    adding someone here lets them read the notes. The meeting's owner is
    re-added automatically, so this cannot lock the recorder out."""
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, meeting_id):
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not await user_can_manage_meeting_access(db, user, meeting):
        raise HTTPException(
            status_code=403,
            detail="Only the meeting's organizer, the person who recorded it, or a Charcha admin can change who has access",
        )

    resolved = await attendee_service.resolve(db, [item.model_dump() for item in body.attendees])
    previous = {row["id"] for row in await attendee_service.list_for_meeting(db, meeting_id)}
    rows, newly_added = await attendee_service.apply_to_meeting(
        db, meeting_id, resolved, owner_user_id=meeting.user_id, source="manual"
    )
    await attendee_service.mark_shared(db, meeting_id, newly_added)
    await attendee_service.notify_new_attendees(db, meeting_id, newly_added, meeting.title)
    # Changing this list changes who can read the transcript, so it belongs in
    # the admin audit trail alongside role and account changes.
    db.add(
        AdminAuditEvent(
            actor_id=user.id,
            action="meeting.attendees.set",
            target_type="meeting",
            target_id=str(meeting_id),
            details={
                "attendees": [
                    {"user_id": row["user_id"], "name": row["name"], "kind": row["kind"]}
                    for row in rows
                ],
                "granted_access_to": [str(item) for item in newly_added],
                "previous_row_count": len(previous),
            },
        )
    )
    await db.commit()
    return rows


@router.get("/{meeting_id}/series")
async def meeting_series(
    meeting_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """The other occurrences of a recurring meeting this person can read, and
    the carry-over check of the previous occurrence's open tasks."""
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, meeting_id):
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not meeting.series_key:
        return {"series_key": None, "occurrences": [], "review": None}
    occurrences = (
        await db.execute(
            select(Meeting)
            .where(Meeting.series_key == meeting.series_key, Meeting.deleted_at.is_(None), meeting_visibility_clause(user))
            .order_by(Meeting.date.desc())
            .limit(30)
        )
    ).scalars().all()
    review = meeting.series_review
    if review:
        ids = [uuid.UUID(item["task_id"]) for item in review.get("items", [])]
        current = {
            str(task.id): task
            for task in (await db.execute(select(MeetingTask).where(MeetingTask.id.in_(ids)))).scalars().all()
        } if ids else {}
        # The review covers earlier occurrences, which this person may not
        # have been invited to (or which are confidential): only tasks from
        # occurrences they can open are shown.
        readable = {
            meeting_id
            for meeting_id in {task.meeting_id for task in current.values()}
            if await user_can_read_meeting(db, user, meeting_id)
        }
        current = {key: task for key, task in current.items() if task.meeting_id in readable}
        previous_id = review.get("previous_meeting_id")
        if previous_id and not await user_can_read_meeting(db, user, uuid.UUID(previous_id)):
            review = {**review, "previous_meeting_id": None, "previous_title": None}
        review = {
            **review,
            "items": [
                {
                    **item,
                    # Live status, so a task confirmed since the review shows as done.
                    "current_status": current[item["task_id"]].status if item["task_id"] in current else "deleted",
                }
                for item in review.get("items", [])
                if item["task_id"] in current and current[item["task_id"]].deleted_at is None
            ],
        }
    return {
        "series_key": meeting.series_key,
        "occurrences": [
            {"id": str(m.id), "title": m.title, "date": m.date.isoformat(), "current": m.id == meeting.id}
            for m in occurrences
        ],
        "review": review,
    }


@router.get("/{meeting_id}/series/standup")
async def standup_digest(
    meeting_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Each person's updates, blockers and plans across the last five
    occurrences of a stand-up, plus blockers raised more than once."""
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, meeting_id):
        raise HTTPException(status_code=404, detail="Meeting not found")
    result = await standup_service.digest(db, user, meeting)
    return result or {"occurrences": [], "people": [], "repeated_blockers": []}


async def _managed_meeting(db: AsyncSession, user: User, meeting_id: uuid.UUID) -> Meeting:
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, meeting_id):
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not await user_can_manage_meeting_access(db, user, meeting):
        raise HTTPException(
            status_code=403,
            detail="Only the meeting's organizer, the person who recorded it, or a Charcha admin can share it",
        )
    return meeting


def _audit_access(user: User, meeting: Meeting, action: str, details: dict) -> AdminAuditEvent:
    return AdminAuditEvent(
        actor_id=user.id, action=action, target_type="meeting", target_id=str(meeting.id), details=details
    )


@router.post("/{meeting_id}/attendees/{attendee_id}/access")
async def change_attendee_access(
    meeting_id: uuid.UUID,
    attendee_id: uuid.UUID,
    body: AccessChange,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Share the notes with someone who was in the call but not on the invite
    (pending → granted), or take access back."""
    meeting = await _managed_meeting(db, user, meeting_id)
    try:
        row = await attendee_service.set_access(db, meeting, attendee_id, body.access)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    if row is None:
        raise HTTPException(status_code=404, detail="Attendee not found")
    db.add(_audit_access(user, meeting, f"meeting.access.{body.access}", {"user_id": str(row.user_id), "name": row.display_name}))
    await db.commit()
    return await attendee_service.list_for_meeting(db, meeting.id)


@router.post("/{meeting_id}/share")
async def share_meeting(
    meeting_id: uuid.UUID,
    body: ShareRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Give a colleague who wasn't picked up as an attendee access to it."""
    meeting = await _managed_meeting(db, user, meeting_id)
    target = await db.get(User, body.user_id)
    if target is None or target.status != "active":
        raise HTTPException(status_code=404, detail="Colleague not found")
    row = await attendee_service.share_with_user(db, meeting, target)
    db.add(_audit_access(user, meeting, "meeting.access.shared", {"user_id": str(row.user_id), "name": row.display_name}))
    await db.commit()
    return await attendee_service.list_for_meeting(db, meeting.id)


@router.delete("/{meeting_id}")
async def delete_meeting(
    meeting_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, meeting.id):
        raise HTTPException(status_code=404, detail="Meeting not found")
    # Reading a meeting doesn't make it yours to delete for everyone.
    if not await user_can_manage_meeting_access(db, user, meeting):
        raise HTTPException(
            status_code=403,
            detail="Only the meeting's organizer, the person who recorded it, or a Charcha admin can delete it",
        )

    # Remove searchable memory first. If Qdrant is unavailable, keep the
    # relational record so the user can retry instead of leaving ghost facts.
    await asyncio.to_thread(qdrant_service.delete_meeting, str(meeting.id))
    meeting.deleted_at = datetime.datetime.now(datetime.UTC)
    meeting.deleted_by = user.id
    await db.commit()
    return {"ok": True}


@router.delete("/{meeting_id}/risks/{risk_id}")
async def delete_meeting_risk(
    meeting_id: uuid.UUID,
    risk_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Risk)
        .join(Meeting, Risk.meeting_id == Meeting.id)
        .where(
            Risk.id == risk_id,
            Risk.meeting_id == meeting_id,
            Risk.deleted_at.is_(None),
            Meeting.deleted_at.is_(None),
        )
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    risk = row[0]
    if not await user_can_read_meeting(db, user, meeting_id):
        raise HTTPException(status_code=404, detail="Risk not found")

    risk.deleted_at = datetime.datetime.now(datetime.UTC)
    risk.deleted_by = user.id
    await db.flush()
    await rebuild_meeting_index(db, meeting_id)
    await db.commit()
    return {"ok": True}


@router.patch("/{meeting_id}/risks/{risk_id}")
async def update_meeting_risk(
    meeting_id: uuid.UUID,
    risk_id: uuid.UUID,
    body: UpdateRiskRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Risk)
        .join(Meeting, Risk.meeting_id == Meeting.id)
        .where(
            Risk.id == risk_id,
            Risk.meeting_id == meeting_id,
            Risk.deleted_at.is_(None),
            Meeting.deleted_at.is_(None),
        )
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    risk = row[0]
    if not await user_can_read_meeting(db, user, meeting_id):
        raise HTTPException(status_code=404, detail="Risk not found")

    previous_description = risk.description
    risk.description = body.description
    risk.severity = body.severity.strip() if body.severity else None
    risk.verified_at = datetime.datetime.now(datetime.UTC)
    risk.verified_by = user.id
    await db.flush()
    corrections, propagation = await vocabulary_service.correct_from_edit(
        db, meeting_id, [(previous_description, risk.description)], user
    )
    await rebuild_meeting_index(db, meeting_id)
    await db.commit()
    vocabulary_service.schedule_followups(background_tasks, meeting_id, propagation)
    return {
        "learned_corrections": corrections,
        "id": str(risk.id),
        "description": risk.description,
        "severity": risk.severity,
        "verified_at": risk.verified_at.isoformat(),
    }


@router.get("/{meeting_id}/export.pdf")
async def export_meeting_pdf(
    meeting_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await db.execute(
        select(Meeting)
        .options(
            selectinload(Meeting.tasks).selectinload(MeetingTask.project),
            selectinload(Meeting.decisions).selectinload(Decision.project),
            selectinload(Meeting.risks).selectinload(Risk.project),
            selectinload(Meeting.projects),
        )
        .where(Meeting.id == meeting_id, Meeting.deleted_at.is_(None))
    )
    meeting = result.scalar_one_or_none()
    if meeting is None or not await user_can_read_meeting(db, user, meeting.id):
        raise HTTPException(status_code=404, detail="Meeting not found")

    insight = await db.get(MeetingInsight, meeting.id)
    recording_result = await db.execute(
        select(RecordingSession).where(RecordingSession.meeting_id == meeting.id).limit(1)
    )
    recording = recording_result.scalar_one_or_none()
    pdf = await asyncio.to_thread(pdf_service.build_meeting_pdf, meeting, insight, recording)
    filename = re.sub(r"[^a-zA-Z0-9._ -]+", "", meeting.title).strip() or "meeting"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )


@router.get("/{meeting_id}/related")
async def get_related_meetings(
    meeting_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.deleted_at.is_(None))
    )
    meeting = result.scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if not await user_can_read_meeting(db, user, meeting.id):
        raise HTTPException(status_code=404, detail="Meeting not found")

    query_text = meeting.summary or meeting.transcript or ""
    # No department pre-filter in the vector store — attendance is not a
    # property Qdrant knows about, so candidates are narrowed to the ones this
    # user may actually read by the SQL query below, which is authoritative.
    related = await asyncio.to_thread(
        qdrant_service.find_related_meetings, query_text, str(meeting.id), None, 8
    )
    candidate_ids: list[uuid.UUID] = []
    for item in related:
        try:
            candidate_ids.append(uuid.UUID(item["meeting_id"]))
        except (KeyError, TypeError, ValueError):
            continue
    if not candidate_ids:
        return []

    active_query = select(Meeting).where(
        Meeting.id.in_(candidate_ids),
        Meeting.deleted_at.is_(None),
    )
    visibility = meeting_visibility_clause(user)
    if visibility is not None:
        active_query = active_query.where(visibility)
    active_meetings = {
        item.id: item for item in (await db.execute(active_query)).scalars().all()
    }
    validated = []
    for item in related:
        try:
            active = active_meetings.get(uuid.UUID(item["meeting_id"]))
        except (KeyError, TypeError, ValueError):
            continue
        if active is None:
            continue
        validated.append(
            {
                **item,
                "meeting_title": active.title,
                "meeting_date": active.date.isoformat(),
            }
        )
        if len(validated) == 3:
            break
    return validated


@router.patch("/{meeting_id}/projects")
async def update_meeting_projects(
    meeting_id: uuid.UUID,
    body: UpdateMeetingProjectsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Meeting)
        .options(selectinload(Meeting.projects))
        .where(Meeting.id == meeting_id, Meeting.deleted_at.is_(None))
    )
    meeting = result.scalar_one_or_none()
    if meeting is None or not await user_can_read_meeting(db, user, meeting.id):
        raise HTTPException(status_code=404, detail="Meeting not found")

    scope = department_scope(user)
    project_ids = list(dict.fromkeys(body.project_ids))
    if project_ids:
        project_result = await db.execute(
            select(Project).where(Project.id.in_(project_ids), Project.deleted_at.is_(None))
        )
        projects = list(project_result.scalars().all())
        if len(projects) != len(project_ids) or (
            scope is not None and any(project.department != scope for project in projects)
        ):
            raise HTTPException(status_code=400, detail="One or more projects are invalid")
    else:
        projects = []

    meeting.projects = projects
    await db.commit()
    return {"projects": [{"id": str(project.id), "name": project.name} for project in projects]}


@router.patch("/{meeting_id}/title")
async def update_meeting_title(
    meeting_id: uuid.UUID,
    body: UpdateMeetingTitleRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, meeting.id):
        raise HTTPException(status_code=404, detail="Meeting not found")

    meeting.title = body.title
    recording_result = await db.execute(
        select(RecordingSession).where(RecordingSession.meeting_id == meeting.id)
    )
    for recording in recording_result.scalars().all():
        recording.title = body.title
    await db.commit()
    try:
        await asyncio.to_thread(qdrant_service.update_meeting_title, str(meeting.id), body.title)
    except Exception:
        logger.exception("Meeting %s title updated without Qdrant payload refresh", meeting.id)
    return {"title": body.title}


@router.patch("/{meeting_id}/summary")
async def update_meeting_summary(
    meeting_id: uuid.UUID,
    body: UpdateMeetingSummaryRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, meeting.id):
        raise HTTPException(status_code=404, detail="Meeting not found")

    previous_summary = meeting.summary
    meeting.summary = body.summary
    meeting.summary_verified_at = datetime.datetime.now(datetime.UTC)
    meeting.summary_verified_by = user.id
    await db.flush()
    corrections, propagation = await vocabulary_service.correct_from_edit(
        db, meeting.id, [(previous_summary, meeting.summary)], user
    )
    await rebuild_meeting_index(db, meeting.id)
    await db.commit()
    vocabulary_service.schedule_followups(background_tasks, meeting.id, propagation)
    return {
        "learned_corrections": corrections,
        "summary": meeting.summary,
        "summary_verified_at": meeting.summary_verified_at.isoformat(),
    }


@router.post("/{meeting_id}/summary/regenerate")
async def regenerate_meeting_summary(
    meeting_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Meeting)
        .options(
            selectinload(Meeting.tasks).selectinload(MeetingTask.project),
            selectinload(Meeting.decisions).selectinload(Decision.project),
            selectinload(Meeting.risks).selectinload(Risk.project),
        )
        .where(Meeting.id == meeting_id, Meeting.deleted_at.is_(None))
    )
    meeting = result.scalar_one_or_none()
    if meeting is None or not await user_can_read_meeting(db, user, meeting.id):
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not meeting.transcript:
        raise HTTPException(status_code=409, detail="This meeting has no transcript to summarize")

    summary, usage = await asyncio.to_thread(
        ai_extractor.generate_detailed_summary, meeting.transcript, meeting.title
    )
    summary = summary.strip()
    if not summary:
        raise HTTPException(status_code=502, detail="Gemini returned an empty summary")
    meeting.summary = summary
    meeting.summary_verified_at = None
    meeting.summary_verified_by = None
    await db.commit()

    try:
        await asyncio.to_thread(
            qdrant_service.upsert_meeting,
            str(meeting.id),
            meeting.title,
            meeting.date.isoformat(),
            summary,
            meeting.transcript,
            [
                {
                    "decision": item.decision,
                    "reason": item.reason or "",
                    "alternatives": item.alternatives or [],
                    "project": item.project.name if item.project else "",
                }
                for item in meeting.decisions
            ],
            [
                {
                    "task": item.description,
                    "assignedTo": item.owner or "",
                    "dueDate": item.deadline or "",
                    "priority": item.priority or "",
                    "project": item.project.name if item.project else "",
                }
                for item in meeting.tasks
            ],
            meeting.department,
            [
                {
                    "risk": item.description,
                    "severity": item.severity or "",
                    "project": item.project.name if item.project else "",
                }
                for item in meeting.risks
            ],
        )
    except Exception:
        logger.exception("Meeting %s summary updated without Qdrant reindexing", meeting.id)
    return {"summary": summary, "usage": usage}


async def _existing_ingest_response(db: AsyncSession, meeting: Meeting) -> dict:
    """The response shape /ingest returns, rebuilt from an already-stored
    meeting. Used when a retried ingest resolves to a meeting that was created
    by an earlier attempt — the caller only needs its id, title and extracted
    items for local history and notifications."""
    tasks = (
        await db.execute(
            select(MeetingTask).where(
                MeetingTask.meeting_id == meeting.id, MeetingTask.deleted_at.is_(None)
            )
        )
    ).scalars().all()
    decisions = (
        await db.execute(
            select(Decision).where(
                Decision.meeting_id == meeting.id, Decision.deleted_at.is_(None)
            )
        )
    ).scalars().all()
    risks = (
        await db.execute(
            select(Risk).where(Risk.meeting_id == meeting.id, Risk.deleted_at.is_(None))
        )
    ).scalars().all()
    return {
        "meeting_id": str(meeting.id),
        "title": meeting.title,
        "summary": meeting.summary or "",
        "tasks": [
            {
                "task": item.description,
                "assignedTo": item.owner or "",
                "dueDate": item.deadline or "",
                "priority": item.priority or "",
            }
            for item in tasks
        ],
        "decisions": [
            {
                "decision": item.decision,
                "reason": item.reason or "",
                "alternatives": item.alternatives or [],
                "participants": item.participants or [],
            }
            for item in decisions
        ],
        "risks": [{"risk": item.description, "severity": item.severity or ""} for item in risks],
        "indexing_status": "done",
        "deduplicated": True,
    }


def _empty_extraction() -> dict:
    return {
        "title": "", "tasks": [], "decisions": [], "risks": [], "summary": "",
        "key_topics": [], "open_questions": [], "highlights": [], "next_steps": [],
        "speaker_activity": [], "input_tokens": 0, "output_tokens": 0,
        "cache_tokens_read": 0, "cache_tokens_written": 0,
    }


def _transient_segments(segment_dicts: list[dict]) -> list[TranscriptSegment]:
    """Unsaved segment objects, so extraction can cite [S<n>] ids before the
    meeting row exists — the LLM call never holds a database transaction."""
    return [
        TranscriptSegment(
            seq=index,
            speaker_key=item.get("speaker_key") or "",
            speaker_label=item.get("speaker_label"),
            text=item["text"],
            original_text=item["text"],
            start_ms=item.get("start_ms"),
            end_ms=item.get("end_ms"),
        )
        for index, item in enumerate(segment_dicts)
    ]


@router.post("/ingest")
@limiter.limit("10/minute")
async def ingest_meeting(
    request: Request,
    background_tasks: BackgroundTasks,
    meeting_title: str = Form(""),
    duration_minutes: int = Form(0),
    spreadsheet_id: str | None = Form(None),
    google_sheets_token: str | None = Form(None),
    tasks_sheet_name: str | None = Form(None),
    notes_sheet_name: str | None = Form(None),
    meeting_language: str = Form("hinglish"),
    transcript: str | None = Form(None),
    audio: UploadFile | None = File(None),
    client_meeting_id: str | None = Form(None),
    # JSON array of attendees. Accepts bare strings (a name or an email) or
    # objects with user_id / name / email — the Chrome extension sends the
    # speaker names it read out of the Google Meet caption rail, the web
    # recorder sends picked user ids plus typed-in external guests.
    attendees: str | None = Form(None),
    template: str = Form("general"),
    source: str | None = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    started = time.perf_counter()
    meeting_title = meeting_title.strip()
    if duration_minutes < 0:
        raise HTTPException(status_code=400, detail="Duration cannot be negative")
    if meeting_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported meeting language")
    transcript = transcript.strip() if transcript and transcript.strip() else None
    if transcript is None and audio is None:
        raise HTTPException(status_code=400, detail="Provide either transcript or audio")
    if template == "auto":
        template = await series_service.resolve_template(db, None, transcript or "")
    template = ai_extractor.template_or_default(template)
    if source not in MEETING_SOURCES:
        source = "extension" if client_meeting_id else "paste"

    requested_attendees: list = []
    if attendees:
        try:
            parsed_attendees = json.loads(attendees)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="attendees must be a JSON array")
        if not isinstance(parsed_attendees, list):
            raise HTTPException(status_code=400, detail="attendees must be a JSON array")
        requested_attendees = parsed_attendees

    # An ingest that already succeeded must not create a second meeting. The
    # MV3 service worker can be evicted while this request is in flight; the
    # extension then recovers the "processing" record after five minutes and
    # finalizes again, and without this check the user gets the same meeting
    # twice (with the tasks, decisions and Sheets rows duplicated too).
    if client_meeting_id:
        existing = (
            await db.execute(
                select(Meeting).where(
                    Meeting.user_id == user.id,
                    Meeting.client_meeting_id == client_meeting_id,
                    Meeting.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            logger.info("Ingest for %s already produced meeting %s — returning it", client_meeting_id, existing.id)
            return await _existing_ingest_response(db, existing)

    # Cached as plain values — db.rollback() expires ORM objects, and
    # re-accessing user attributes afterward would trigger a synchronous
    # lazy-reload that crashes on an async session (MissingGreenlet).
    user_id = user.id
    user_department = user.department
    # Integration configuration belongs to the Charcha account, not to a
    # particular extension installation. Form values remain accepted for
    # backwards compatibility, but the authenticated user's shared settings
    # are authoritative.
    spreadsheet_id = user.google_sheets_spreadsheet_id
    tasks_sheet_name = user.google_sheets_tasks_tab or "Tasks"
    notes_sheet_name = user.google_sheets_notes_tab or "Meeting Notes"

    transcription_requests = 0
    tasks_found = 0
    decisions_found = 0
    input_tokens = output_tokens = cache_hits = 0
    cache_written = 0

    try:
        detailed = None
        if transcript is None:
            audio_bytes = await audio.read()
            if not audio_bytes:
                raise HTTPException(status_code=400, detail="Audio file is empty")
            if len(audio_bytes) > MAX_AUDIO_BYTES:
                raise HTTPException(status_code=413, detail="Audio file exceeds the 100 MB limit")
            detailed = await transcriber.transcribe_audio_detailed(
                audio_bytes, audio.content_type or "audio/webm", meeting_language,
                people=vocabulary_service.people_from_attendees(requested_attendees),
            )
            transcript = detailed["transcript"]
            transcription_requests = 1
            if not transcript.strip():
                raise HTTPException(status_code=422, detail="The recording did not contain recognizable speech")

        # Corrections the team taught Charcha (a provider transcript already
        # has them; pasted text and Meet captions don't), and how the
        # meeting's people and terms are spelled, for the notes model.
        vocabulary = await vocabulary_service.active_vocabulary()
        if detailed is None and vocabulary.rules:
            transcript, _ = vocabulary_service.apply_text(transcript, vocabulary.rules)
        vocabulary_hint = vocabulary_service.prompt_hint(
            vocabulary_service.people_from_attendees(requested_attendees), vocabulary, settings.team_roster_list
        )
        segment_dicts = (
            transcript_service.segments_from_turns(detailed["turns"])
            if detailed
            else transcript_service.parse_transcript_text(transcript)
        )

        # A failed extraction no longer loses the meeting: the transcript is
        # stored either way, and the "AI notes" stage can be retried later
        # without transcribing (or paying for) the audio again.
        extraction_error: Exception | None = None
        try:
            extraction = await asyncio.to_thread(
                ai_extractor.extract_from_transcript,
                transcript,
                meeting_title,
                datetime.date.today(),
                segments=_transient_segments(segment_dicts) or None,
                template=template,
                vocabulary_hint=vocabulary_hint,
            )
            extraction = vocabulary_service.clean_extraction(extraction, vocabulary.rules)
        except Exception as error:
            logger.exception("Extraction failed; storing the transcript without AI notes")
            extraction_error = error
            extraction = _empty_extraction()
        extracted_at = time.perf_counter()
        meeting_title = (
            (extraction.get("title") or "").strip()
            or meeting_title
            or _fallback_title(transcript)
        )[:160]
        input_tokens = extraction["input_tokens"]
        output_tokens = extraction["output_tokens"]
        cache_hits = extraction["cache_tokens_read"]
        cache_written = extraction["cache_tokens_written"]

        meeting = Meeting(
            user_id=user_id,
            title=meeting_title,
            date=datetime.datetime.now(datetime.UTC),
            transcript=transcript,
            summary=extraction["summary"] or None,
            duration_minutes=duration_minutes,
            department=user_department,
            client_meeting_id=client_meeting_id,
            source=source,
            template=template,
            transcript_revision=1,
            insights_revision=None if extraction_error else 1,
        )
        db.add(meeting)
        await db.flush()
        segments = await transcript_service.replace_segments(
            db, meeting, segment_dicts, language=meeting_language
        )

        # Who may read this meeting. The recorder is always included; anyone
        # else only gains access if their name/email resolves to a Charcha
        # account (see attendee_service.resolve).
        _, newly_added = await attendee_service.apply_to_meeting(
            db,
            meeting.id,
            await attendee_service.resolve(db, requested_attendees),
            owner_user_id=user_id,
            source="meet" if client_meeting_id else "manual",
        )
        await attendee_service.notify_new_attendees(db, meeting.id, newly_added, meeting_title)

        decision_objs = []
        if extraction_error is None:
            created = await insight_service.persist_items(db, meeting, extraction, segments, user_department)
            checked, rejected = await insight_service.write_insight(db, meeting, extraction, segments)
            insight_service.record_run(
                db, meeting, extraction, status="succeeded", template=template, user_id=user_id,
                checked=checked + created["checked"], rejected=rejected + created["rejected"],
            )
            decision_objs = created["decisions"]
            tasks_found = len(created["tasks"])
            decisions_found = len(created["decisions"])
        else:
            insight_service.record_run(
                db, meeting, None, status="failed", template=template, user_id=user_id, error=extraction_error
            )

        if spreadsheet_id and google_sheets_token and extraction_error is None:
            try:
                await sheets_service.ensure_sheet_tab(spreadsheet_id, tasks_sheet_name, google_sheets_token)
                await sheets_service.ensure_sheet_tab(spreadsheet_id, notes_sheet_name, google_sheets_token)

                task_rows = [
                    [
                        t["task"],
                        t.get("assignedTo", ""),
                        t.get("dueDate", ""),
                        t.get("priority", ""),
                        meeting_title,
                    ]
                    for t in extraction["tasks"]
                ]
                if task_rows:
                    await sheets_service.append_rows_to_sheet(
                        spreadsheet_id, tasks_sheet_name, task_rows, google_sheets_token
                    )

                decisions_text = "\n".join(f"- {d['decision']}" for d in extraction["decisions"])
                await sheets_service.append_rows_to_sheet(
                    spreadsheet_id,
                    notes_sheet_name,
                    [[meeting_title, meeting.date.isoformat(), extraction["summary"], decisions_text]],
                    google_sheets_token,
                )
            except Exception as e:
                if "GOOGLE_TOKEN_EXPIRED" in str(e):
                    raise HTTPException(status_code=401, detail="GOOGLE_TOKEN_EXPIRED")
                raise

        db.add(
            Trace(
                user_id=user_id,
                meeting_id=meeting.id,
                meeting_title=meeting_title,
                duration_minutes=duration_minutes,
                transcription_requests=transcription_requests,
                ai_input_tokens=input_tokens + cache_hits + cache_written,
                ai_output_tokens=output_tokens,
                ai_cache_hits=cache_hits,
                tasks_found=tasks_found,
                decisions_found=decisions_found,
                status="success" if extraction_error is None else "partial",
            )
        )

        await db.flush()
        decision_checks = [
            (decision_obj.id, extracted["decision"]) for decision_obj, extracted in decision_objs
        ]
        meeting_id = meeting.id
        meeting_date = meeting.date.isoformat()
        await db.commit()
        committed_at = time.perf_counter()
        # Transcription and notes above were paid for before the meeting
        # existed; link them (and anything later in this request) to it.
        usage_ledger.attribute(meeting_id=meeting_id)

        # Stage rows reference the meeting, so they can only be written once
        # it is committed.
        await processing_service.set_stage(
            meeting_id, "transcription", "succeeded" if detailed else "skipped",
            detail={"source": source, "segments": len(segment_dicts)},
        )
        if extraction_error is None:
            await processing_service.set_stage(
                meeting_id, "extraction", "succeeded", detail={"template": template, "transcript_revision": 1}
            )
        else:
            await processing_service.set_stage(meeting_id, "extraction", "failed", error=extraction_error)
        await processing_service.set_stage(meeting_id, "indexing", "pending")

        background_tasks.add_task(
            _enrich_meeting_after_ingest,
            meeting_id,
            meeting_title,
            meeting_date,
            transcript,
            extraction,
            user_department,
            decision_checks,
        )
        # A structured, editable board uses the notes already extracted above;
        # it incurs no additional model call and survives a failed indexing job.
        from app.services import board_service
        background_tasks.add_task(board_service.ensure_from_meeting, meeting_id)
        if extraction_error is None:
            background_tasks.add_task(followup_service.announce_notes, meeting_id)
            background_tasks.add_task(followup_service.notify_task_owners, meeting_id)
            background_tasks.add_task(jira_service.auto_send, meeting_id)
            background_tasks.add_task(vocabulary_service.learn_from_meeting, meeting_id)
        if client_meeting_id:
            background_tasks.add_task(
                _process_meeting_audio,
                meeting_id,
                client_meeting_id,
                user_id,
                meeting_title,
                meeting_language,
                duration_minutes,
            )
        logger.info(
            "Meeting %s ready: Gemini %.2fs, database and integrations %.2fs, response %.2fs",
            meeting_id,
            extracted_at - started,
            committed_at - extracted_at,
            committed_at - started,
        )

        return {
            "meeting_id": str(meeting_id),
            "title": meeting_title,
            "summary": extraction["summary"],
            "tasks": extraction["tasks"],
            "decisions": extraction["decisions"],
            "risks": extraction["risks"],
            "indexing_status": "pending",
            "extraction_status": "succeeded" if extraction_error is None else "failed",
            "extraction_error": str(extraction_error)[:300] if extraction_error else None,
            "processing_timings": {
                "analysis_seconds": round(extracted_at - started, 2),
                "persistence_seconds": round(committed_at - extracted_at, 2),
                "response_seconds": round(committed_at - started, 2),
            },
            "usage": {
                "transcription_requests": transcription_requests,
                "duration_minutes": duration_minutes,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_tokens_read": cache_hits,
                "cache_tokens_written": cache_written,
            },
        }

    except Exception:
        await db.rollback()
        # meeting_id is never persisted here — the rollback above undoes the
        # meeting insert (only flushed, never committed), so any reference to
        # it would violate the traces.meeting_id FK.
        async with async_session() as trace_db:
            trace_db.add(
                Trace(
                    user_id=user_id,
                    meeting_id=None,
                    meeting_title=meeting_title,
                    duration_minutes=duration_minutes,
                    transcription_requests=transcription_requests,
                    ai_input_tokens=input_tokens + cache_hits,
                    ai_output_tokens=output_tokens,
                    ai_cache_hits=cache_hits,
                    tasks_found=tasks_found,
                    decisions_found=decisions_found,
                    status="error",
                )
            )
            await trace_db.commit()
        raise


class ConfidentialBody(BaseModel):
    confidential: bool


@router.post("/{meeting_id}/confidential")
async def set_meeting_confidential(
    meeting_id: uuid.UUID,
    body: ConfidentialBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Anyone in the meeting can mark it confidential; only the recorder or
    organizer can unmark it — including when the notes AI marked it."""
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, meeting_id):
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not body.confidential and user.id not in (meeting.user_id, meeting.organizer_user_id):
        raise HTTPException(status_code=403, detail="Only the person who recorded or organised this meeting can unmark it")
    if body.confidential != meeting.confidential or meeting.confidential_source != "manual":
        await privacy_service.set_confidential(db, meeting, body.confidential, source="manual")
        db.add(_audit_access(user, meeting, "meeting.confidential" if body.confidential else "meeting.not_confidential", {}))
        await db.commit()
    return {"confidential": meeting.confidential, "confidential_source": meeting.confidential_source}


@router.post("/{meeting_id}/share-link")
async def create_share_link(
    meeting_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The only place a meeting's share_token is ever set. Idempotent —
    copying the link again just hands back the same token — so the link
    stays stable while it's live, and simply doesn't exist until this is
    called at least once. A public link is the widest share there is, so
    only the people who decide access may create it (as with attendees)."""
    meeting = await _managed_meeting(db, user, meeting_id)
    if meeting.confidential:
        raise HTTPException(status_code=409, detail="This meeting is confidential, so it can't have a public link")

    if meeting.share_token is None:
        meeting.share_token = secrets.token_urlsafe(24)
        await db.commit()

    return {"share_token": meeting.share_token}


@router.delete("/{meeting_id}/share-link")
async def revoke_share_link(
    meeting_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    meeting = await _managed_meeting(db, user, meeting_id)

    meeting.share_token = None
    await db.commit()
    return {"ok": True}


@router.get("/shared/{token}")
@limiter.limit("30/minute")
async def get_shared_meeting(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Public, unauthenticated — reachable by anyone holding the link. Returns
    only the processed output (overview, template sections, discussion,
    tasks, decisions, risks), never the raw transcript, evidence quotes,
    audio, or attendee list."""
    result = await db.execute(
        select(Meeting)
        .options(
            selectinload(Meeting.tasks),
            selectinload(Meeting.decisions),
            selectinload(Meeting.risks),
        )
        .where(Meeting.share_token == token, Meeting.deleted_at.is_(None), Meeting.confidential.is_(False))
    )
    meeting = result.scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=404, detail="This link is invalid or has been revoked")

    insight = await db.get(MeetingInsight, meeting.id)

    def texts(values: list[str] | None) -> list[str]:
        return [v for v in (values or []) if isinstance(v, str) and v.strip()]

    return {
        "title": meeting.title,
        "date": meeting.date.isoformat(),
        "duration_minutes": meeting.duration_minutes,
        "summary": (insight.overview if insight and insight.overview else None) or meeting.summary,
        "template_sections": [
            {
                "heading": block.get("heading") or "",
                "items": [
                    {"text": item.get("text") or "", "person": item.get("person") or None}
                    for item in block.get("items") or [] if (item.get("text") or "").strip()
                ],
            }
            for block in (insight.template_sections or [] if insight else [])
            if block.get("items")
        ],
        "sections": [
            {"title": section.get("title") or "", "summary": section.get("summary") or ""}
            for section in (insight.sections or [] if insight else [])
            if section.get("title") or section.get("summary")
        ],
        "key_topics": texts(insight.key_topics if insight else None),
        "highlights": texts(insight.highlights if insight else None),
        "next_steps": texts(insight.next_steps if insight else None),
        "open_questions": texts(insight.open_questions if insight else None),
        "tasks": [
            {
                "description": task.description,
                "owner": task.owner,
                "deadline": task.deadline,
                "due_date": task.due_date.isoformat() if task.due_date else None,
                "status": task.status,
            }
            for task in meeting.tasks
            if task.deleted_at is None
        ],
        "decisions": [
            {"decision": d.decision, "reason": d.reason, "alternatives": d.alternatives or []}
            for d in meeting.decisions
            if d.deleted_at is None
        ],
        "risks": [
            {"description": r.description, "severity": r.severity}
            for r in meeting.risks
            if r.deleted_at is None
        ],
    }
