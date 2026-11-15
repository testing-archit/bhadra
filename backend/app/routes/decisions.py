import asyncio
import datetime
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.database.models import Decision, Meeting, Project, RecordingSession, TranscriptSegment, User
from app.dependencies import get_current_user, meeting_visibility_clause
from app.services import vocabulary_service
from app.services.meeting_index_service import rebuild_meeting_index


def _visibility(user: User) -> tuple:
    """Splat into a .where() — empty for admins, one clause for everyone else,
    restricting decisions to the meetings the user attended."""
    clause = meeting_visibility_clause(user)
    return () if clause is None else (clause,)


router = APIRouter(prefix="/api/decisions", tags=["decisions"])


class DecisionUpdate(BaseModel):
    decision: str | None = Field(default=None, max_length=4000)
    reason: str | None = Field(default=None, max_length=8000)
    alternatives: list[str] | None = None
    participants: list[str] | None = None

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Decision is required")
        return value


@router.delete("/{decision_id}")
async def delete_decision(
    decision_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Decision)
        .join(Meeting, Decision.meeting_id == Meeting.id)
        .where(
            Decision.id == decision_id,
            Decision.deleted_at.is_(None),
            Meeting.deleted_at.is_(None),
            *_visibility(user),
        )
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    decision = row[0]

    meeting_id = decision.meeting_id
    decision.deleted_at = datetime.datetime.now(datetime.UTC)
    decision.deleted_by = user.id
    await db.flush()
    await rebuild_meeting_index(db, meeting_id)
    await db.commit()
    return {"ok": True}


@router.get("")
async def list_decisions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = (
        select(Decision, Meeting.title, Meeting.date, Project.name)
        .join(Meeting, Decision.meeting_id == Meeting.id)
        .outerjoin(Project, and_(Decision.project_id == Project.id, Project.deleted_at.is_(None)))
        .where(Decision.deleted_at.is_(None), Meeting.deleted_at.is_(None))
        .order_by(Decision.created_at.desc())
    )
    query = query.where(*_visibility(user))

    result = await db.execute(query)
    return [
        {
            "id": str(decision.id),
            "meeting_id": str(decision.meeting_id),
            "meeting_title": title,
            "meeting_date": date.isoformat(),
            "decision": decision.decision,
            "reason": decision.reason,
            "alternatives": decision.alternatives or [],
            "participants": decision.participants or [],
            "conflict_note": decision.conflict_note,
            "project": project_name,
            "project_id": str(decision.project_id) if decision.project_id else None,
            "verified_at": decision.verified_at.isoformat() if decision.verified_at else None,
        }
        for decision, title, date, project_name in result.all()
    ]


@router.get("/{decision_id}")
async def get_decision(
    decision_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Decision, Meeting.title, Meeting.date, Project.name)
        .join(Meeting, Decision.meeting_id == Meeting.id)
        .outerjoin(Project, and_(Decision.project_id == Project.id, Project.deleted_at.is_(None)))
        .where(
            Decision.id == decision_id,
            Decision.deleted_at.is_(None),
            Meeting.deleted_at.is_(None),
            *_visibility(user),
        )
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")

    decision, title, date, project_name = row

    return {
        "id": str(decision.id),
        "meeting_id": str(decision.meeting_id),
        "meeting_title": title,
        "meeting_date": date.isoformat(),
        "decision": decision.decision,
        "reason": decision.reason,
        "alternatives": decision.alternatives or [],
        "participants": decision.participants or [],
        "conflict_note": decision.conflict_note,
        "project": project_name,
        "project_id": str(decision.project_id) if decision.project_id else None,
        "verified_at": decision.verified_at.isoformat() if decision.verified_at else None,
    }


@router.patch("/{decision_id}")
async def update_decision(
    decision_id: uuid.UUID,
    body: DecisionUpdate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Decision)
        .join(Meeting, Decision.meeting_id == Meeting.id)
        .where(
            Decision.id == decision_id,
            Decision.deleted_at.is_(None),
            Meeting.deleted_at.is_(None),
            *_visibility(user),
        )
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    decision = row[0]

    updates = body.model_dump(exclude_unset=True)
    before = {"decision": decision.decision, "reason": decision.reason}
    for field, value in updates.items():
        if field in {"alternatives", "participants"}:
            value = [item.strip() for item in (value or []) if item.strip()]
        elif isinstance(value, str):
            value = value.strip()
        setattr(decision, field, value)
    decision.verified_at = datetime.datetime.now(datetime.UTC)
    decision.verified_by = user.id
    await db.flush()
    corrections, propagation = await vocabulary_service.correct_from_edit(
        db, decision.meeting_id, [(before["decision"], decision.decision), (before["reason"], decision.reason)], user
    )
    await rebuild_meeting_index(db, decision.meeting_id)
    await db.commit()
    vocabulary_service.schedule_followups(background_tasks, decision.meeting_id, propagation)
    return {
        "learned_corrections": corrections,
        "id": str(decision.id),
        "decision": decision.decision,
        "reason": decision.reason,
        "alternatives": decision.alternatives or [],
        "participants": decision.participants or [],
        "verified_at": decision.verified_at.isoformat(),
    }


async def _decision_source(decision_id, user, db):
    decision = await db.scalar(select(Decision).join(Meeting, Decision.meeting_id == Meeting.id).where(
        Decision.id == decision_id, Decision.deleted_at.is_(None), Meeting.deleted_at.is_(None), *_visibility(user)))
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    # Resolve current segments inside this meeting. Stale/cross-meeting refs
    # never become a playable quote, even if an old cache says verified.
    identifiers = []
    for ref in decision.evidence or []:
        if ref.get("verified") is True:
            try:
                identifiers.append(uuid.UUID(str(ref["segment_id"])))
            except (KeyError, ValueError, TypeError):
                pass
    segments = (await db.scalars(select(TranscriptSegment).where(
        TranscriptSegment.meeting_id == decision.meeting_id, TranscriptSegment.id.in_(identifiers)
    ).order_by(TranscriptSegment.seq))).all() if identifiers else []
    from app.services.insight_service import _norm
    segments = [segment for segment in segments if any(
        ref.get("segment_id") == str(segment.id) and ref.get("verified") is True
        and _norm(ref.get("excerpt", "")) and _norm(ref["excerpt"]) in _norm(segment.text)
        for ref in decision.evidence or [])]
    recording = await db.scalar(select(RecordingSession).where(
        RecordingSession.meeting_id == decision.meeting_id, RecordingSession.status == "processed"
    ).order_by(RecordingSession.started_at.desc()).limit(1))
    return decision, segments, recording


@router.get("/{decision_id}/source")
async def decision_source(decision_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    from app.routes.recordings import _session_dir
    from app.services.transcript_service import display_label
    decision, segments, recording = await _decision_source(decision_id, user, db)
    recorded = recording is not None and (_session_dir(recording.id) / "recording.webm").is_file()
    return {"meeting_id": str(decision.meeting_id), "lines": [
        {"segment_id": str(segment.id), "speaker": display_label(segment), "text": segment.text,
         "original_text": segment.original_text, "start_ms": segment.start_ms, "end_ms": segment.end_ms,
         "audio_available": bool(recorded and segment.start_ms is not None and segment.start_ms >= 0 and segment.end_ms is not None and segment.end_ms > segment.start_ms)}
        for segment in segments]}


@router.get("/{decision_id}/source/{segment_id}/audio")
async def decision_quote_audio(decision_id: uuid.UUID, segment_id: uuid.UUID,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> Response:
    from app.routes.recordings import _session_dir
    _, segments, recording = await _decision_source(decision_id, user, db)
    segment = next((line for line in segments if line.id == segment_id), None)
    if segment is None or recording is None or segment.start_ms is None or segment.start_ms < 0 or segment.end_ms is None or segment.end_ms <= segment.start_ms:
        raise HTTPException(status_code=404, detail="No timed recording for this quote")
    path = _session_dir(recording.id) / "recording.webm"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Recording is no longer available")
    start = max(0, segment.start_ms / 1000 - 0.4)
    duration = min(45, segment.end_ms / 1000 - start + 0.4)
    try:
        process = await asyncio.create_subprocess_exec("ffmpeg", "-v", "error", "-ss", str(start), "-i", str(path),
            "-t", str(duration), "-vn", "-f", "mp3", "pipe:1", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail="Quote playback is unavailable on this server") from error
    try:
        audio, _ = await asyncio.wait_for(process.communicate(), timeout=20)
    except TimeoutError as error:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise HTTPException(status_code=504, detail="Preparing this quote took too long. Try again.") from error
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode or not audio:
        raise HTTPException(status_code=502, detail="Couldn't play this quote. Open the transcript instead.")
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "private, no-store"})
