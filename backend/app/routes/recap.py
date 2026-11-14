import asyncio
import base64
import datetime
import logging
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.db import get_db
from app.database.models import Meeting, MeetingTask, User
from app.dependencies import get_current_user
from app.rate_limit import limiter
from app.services import live_conversation, transcriber, tts_service, voice_recap

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/recap", tags=["recap"])
MAX_RECAP_BYTES = 25 * 1024 * 1024


@router.post("")
@limiter.limit("20/minute")
async def recap_audio(
    request: Request,
    audio: UploadFile = File(...),
    kind: Literal["call", "voice_note"] = Form("voice_note"),
    save: bool = Form(True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Recap a phone call recording or WhatsApp voice note: Gnani Prisma
    transcribes it in whatever Indian language it is in, Gemini writes the
    recap in that language, Gnani Timbre speaks a short voice recap. Saved
    as a meeting with its action items, so it joins memory and Tasks."""
    if not settings.gnani_api_key:
        raise HTTPException(status_code=503, detail="Recaps need GNANI_API_KEY")
    if not settings.gemini_api_key:
        raise HTTPException(status_code=503, detail="Recaps need GEMINI_API_KEY")
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="The file is empty")
    if len(data) > MAX_RECAP_BYTES:
        raise HTTPException(status_code=413, detail="Files up to 25 MB, about an hour of call audio")

    try:
        heard = await transcriber.transcribe_audio_detailed(data, audio.content_type or "", "hinglish")
    except Exception as error:
        logger.exception("Recap transcription failed")
        raise HTTPException(status_code=422, detail="Couldn't read that audio. Try an mp3, m4a, ogg, opus or wav file.") from error
    lines = [str(turn.get("text") or "").strip() for turn in heard["turns"]]
    transcript = "\n".join(line for line in lines if line)
    if not transcript:
        raise HTTPException(status_code=422, detail="No speech was found in that audio")
    language = heard.get("language")

    result = await asyncio.to_thread(voice_recap.recap, transcript, language, kind)
    try:
        speech = await tts_service.synthesize(result["spoken_recap"], live_conversation.speech_language(language))
        spoken = base64.b64encode(speech).decode()
    except Exception:
        logger.exception("Recap speech failed")
        spoken = None

    meeting_id = None
    if save:
        duration = float((heard.get("metadata") or {}).get("duration") or 0)
        notes = result["summary"] + ("\n\nAmounts and numbers:\n" + "\n".join(f"- {a}" for a in result["amounts"]) if result["amounts"] else "")
        meeting = Meeting(
            user_id=user.id,
            organizer_user_id=user.id,
            title=result["title"],
            date=datetime.datetime.now(datetime.UTC),
            transcript=transcript,
            summary=notes,
            duration_minutes=max(1, round(duration / 60)) if duration else 1,
            source=kind,
            department=user.department,
        )
        db.add(meeting)
        await db.flush()
        for item in result["action_items"]:
            db.add(MeetingTask(
                meeting_id=meeting.id, owner=item["owner"] or None, description=item["task"],
                deadline=item["due"] or None, origin="ai",
            ))
        await db.commit()
        meeting_id = str(meeting.id)

    return {
        **result,
        "transcript": transcript,
        "language": language,
        "audio": spoken,
        "meeting_id": meeting_id,
    }
