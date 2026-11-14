import asyncio
import base64
import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.db import get_db
from app.database.models import User
from app.dependencies import get_current_user
from app.rate_limit import limiter
from app.services import live_conversation, transcriber, tts_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/live", tags=["live"])
MAX_TURN_AUDIO_BYTES = 8 * 1024 * 1024


@router.post("/turn")
@limiter.limit("60/minute")
async def live_turn(
    request: Request,
    audio: UploadFile = File(...),
    history: str = Form("[]"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One spoken turn of Charcha Live: Gnani Prisma hears it, Gemini
    answers briefly from the person's meetings, Gnani Timbre says it.
    Returns the transcript, the reply and the reply's MP3 (base64)."""
    if not settings.gnani_api_key:
        raise HTTPException(status_code=503, detail="Charcha Live needs GNANI_API_KEY")
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="The audio was empty")
    if len(audio_bytes) > MAX_TURN_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="That was too long for one turn")
    try:
        past = json.loads(history)
        past = [turn for turn in past if isinstance(turn, dict)][-live_conversation.MAX_HISTORY_TURNS:]
    except (ValueError, TypeError):
        past = []

    heard = await transcriber.transcribe_audio_detailed(audio_bytes, audio.content_type or "audio/webm", "hinglish")
    text = " ".join(turn["text"] for turn in heard["turns"]).strip()
    if not text:
        return {"transcript": "", "reply": None, "audio": None}

    digest = await live_conversation.meeting_digest(db, user)
    try:
        answer = await asyncio.to_thread(live_conversation.reply, past, text, digest, (user.name or "").split(" ")[0] or None)
    except Exception:
        logger.exception("Charcha Live reply failed")
        answer = "Sorry, abhi jawab nahi de paaya. Ek baar phir boliye?"
    if not answer:
        answer = "Sorry, main samjha nahi. Ek baar phir boliye?"
    try:
        speech = await tts_service.synthesize(answer)
        encoded = base64.b64encode(speech).decode()
    except Exception:
        logger.exception("Charcha Live speech failed")
        encoded = None
    return {"transcript": text, "reply": answer, "audio": encoded}
