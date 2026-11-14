"""Employee voice setup and explicit learning from corrected meeting speakers."""

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.database.models import Meeting, RecordingSession, TranscriptSegment, User, VoiceProfile, VoiceProfileConfirmation
from app.dependencies import get_current_user, user_can_read_meeting
from app.services import secret_box, voice_identity

router = APIRouter(prefix="/api/voice", tags=["voice"])
MAX_ENROLLMENT_BYTES = 8_000_000


@router.get("/profile")
async def profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(VoiceProfile, user.id)
    return {
        "enrolled": row is not None,
        "available": voice_identity.available(),
        "confirmed_samples": row.confirmed_samples if row else 0,
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
    }


@router.post("/profile")
async def enroll(
    audio: UploadFile = File(...),
    consent: bool = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not consent:
        raise HTTPException(status_code=422, detail="Agree to voice matching before recording your profile")
    if not voice_identity.available():
        raise HTTPException(status_code=503, detail="Voice matching is not configured on this server")
    content = await audio.read(MAX_ENROLLMENT_BYTES + 1)
    if len(content) > MAX_ENROLLMENT_BYTES:
        raise HTTPException(status_code=413, detail="Voice sample is too large")
    try:
        vector = await asyncio.to_thread(voice_identity.embed_enrollment, content)
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    row = await db.get(VoiceProfile, user.id)
    if row is None:
        row = VoiceProfile(user_id=user.id, embedding_encrypted="", model=voice_identity.MODEL_ID)
        db.add(row)
    row.embedding_encrypted = secret_box.encrypt(json.dumps(vector))
    row.model = voice_identity.MODEL_ID
    row.confirmed_samples = 1
    await db.execute(delete(VoiceProfileConfirmation).where(VoiceProfileConfirmation.user_id == user.id))
    await db.commit()
    return {"enrolled": True, "confirmed_samples": 1}


@router.delete("/profile")
async def delete_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await db.execute(delete(VoiceProfileConfirmation).where(VoiceProfileConfirmation.user_id == user.id))
    await db.execute(delete(VoiceProfile).where(VoiceProfile.user_id == user.id))
    await db.commit()
    return {"enrolled": False}


@router.post("/confirm/{meeting_id}/{speaker_key}")
async def confirm_my_voice(
    meeting_id: uuid.UUID,
    speaker_key: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Only the named employee can use a corrected meeting turn to improve their profile."""
    profile_row = await db.get(VoiceProfile, user.id)
    if profile_row is None:
        raise HTTPException(status_code=409, detail="Record your voice profile first")
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, meeting_id):
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not user.name:
        raise HTTPException(status_code=422, detail="Add your name to your account first")
    existing = await db.get(VoiceProfileConfirmation, (user.id, meeting_id, speaker_key))
    if existing is not None:
        return {"confirmed": True, "confirmed_samples": profile_row.confirmed_samples}
    result = await db.execute(
        select(TranscriptSegment).where(
            TranscriptSegment.meeting_id == meeting_id,
            TranscriptSegment.speaker_key == speaker_key,
        )
    )
    segments = result.scalars().all()
    if not segments or any((segment.speaker_label or "").casefold() != user.name.casefold() for segment in segments):
        raise HTTPException(status_code=422, detail="Name this speaker as yourself in the transcript first")
    recording_result = await db.execute(
        select(RecordingSession).where(RecordingSession.meeting_id == meeting_id)
        .order_by(RecordingSession.created_at.desc()).limit(1)
    )
    recording = recording_result.scalar_one_or_none()
    if recording is None:
        raise HTTPException(status_code=422, detail="This meeting has no audio to confirm")
    from app.routes.recordings import _session_dir
    path = _session_dir(recording.id) / "recording.webm"
    if not path.is_file():
        raise HTTPException(status_code=422, detail="The meeting audio is unavailable")
    turns = [
        {"start": segment.start_ms / 1000, "end": segment.end_ms / 1000}
        for segment in segments if segment.start_ms is not None and segment.end_ms is not None
    ]
    try:
        vector = await voice_identity.embed_confirmed_turns(path, turns)
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if vector is None:
        raise HTTPException(status_code=422, detail="At least eight seconds of your speech are needed to improve the profile")
    old = secret_box.decrypt(profile_row.embedding_encrypted)
    if not old:
        raise HTTPException(status_code=409, detail="Voice profile key changed; record a new profile")
    blended = voice_identity.blend_confirmed(json.loads(old), vector, profile_row.confirmed_samples)
    profile_row.embedding_encrypted = secret_box.encrypt(json.dumps(blended))
    profile_row.confirmed_samples += 1
    db.add(VoiceProfileConfirmation(user_id=user.id, meeting_id=meeting_id, speaker_key=speaker_key))
    await db.commit()
    return {"confirmed": True, "confirmed_samples": profile_row.confirmed_samples}
