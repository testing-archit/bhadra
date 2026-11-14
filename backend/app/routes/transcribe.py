import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.config import settings
from app.database.models import User
from app.dependencies import get_current_user
from app.rate_limit import limiter
from app.services import transcriber

router = APIRouter(prefix="/api/transcribe", tags=["transcribe"])
MAX_AUDIO_BYTES = 25 * 1024 * 1024
SUPPORTED_LANGUAGES = {"en", "hi", "hinglish", "auto"}
_CLIENT_MEETING_ID_RE = re.compile(r"^[A-Za-z0-9_]{1,128}$")
_SPEAKER_LABEL_RE = re.compile(r"^[a-z]{1,20}$")


def _stage_chunk_for_later_assembly(
    client_meeting_id: str | None, chunk_index: int | None, speaker_label: str | None, audio_bytes: bytes
) -> None:
    # Best-effort only: the Chrome extension deletes its own local copy of a
    # chunk's audio the moment it's transcribed (to stay under IndexedDB
    # limits), so this is the only point the raw bytes ever pass through a
    # place we can persist them. /api/meetings/ingest later finds this
    # directory (by client_meeting_id) and assembles it into playable audio.
    if not client_meeting_id or chunk_index is None or not speaker_label:
        return
    if not _CLIENT_MEETING_ID_RE.match(client_meeting_id) or not _SPEAKER_LABEL_RE.match(speaker_label):
        return
    if chunk_index < 0:
        return
    try:
        staging_dir = Path(settings.recordings_dir).resolve() / "meeting_audio_staging" / client_meeting_id
        staging_dir.mkdir(parents=True, exist_ok=True)
        (staging_dir / f"{chunk_index:06d}_{speaker_label}.webm").write_bytes(audio_bytes)
    except OSError:
        pass


@router.post("")
@limiter.limit("60/minute")
async def transcribe_chunk(
    request: Request,
    audio: UploadFile = File(...),
    meeting_language: str = Form("hinglish"),
    client_meeting_id: str | None = Form(None),
    chunk_index: int | None = Form(None),
    speaker_label: str | None = Form(None),
    user: User = Depends(get_current_user),
) -> dict:
    if meeting_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported meeting language")
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Audio chunk is empty")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio chunk exceeds the 25 MB limit")
    _stage_chunk_for_later_assembly(client_meeting_id, chunk_index, speaker_label, audio_bytes)
    text = await transcriber.transcribe_audio(
        audio_bytes, audio.content_type or "audio/webm", meeting_language
    )
    return {"text": text}
