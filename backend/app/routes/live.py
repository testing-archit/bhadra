import asyncio
import base64
import json
import logging
import time

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
    """One spoken turn of Wilco Live: Gnani Prisma hears it, Gemini
    answers briefly from the person's meetings, Gnani Timbre says it.
    Returns the transcript, the reply and the reply's MP3 (base64)."""
    if not settings.gnani_api_key:
        raise HTTPException(status_code=503, detail="Wilco Live needs GNANI_API_KEY")
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

    started = time.monotonic()
    async def hear():
        # A live caller must not wait through an entire batch or eight retries.
        async with asyncio.timeout(12):
            return await transcriber.transcribe_audio_detailed(
                audio_bytes, audio.content_type or 'audio/webm', 'hinglish', timeout_seconds=8, interactive=True)
    # Read the digest while Prisma listens, but never leave it running on this
    # request's session after transcription fails (gather doesn't cancel it).
    digest_task = asyncio.create_task(live_conversation.meeting_digest(db, user))
    try:
        heard = await hear()
    except BaseException as error:
        digest_task.cancel()
        await asyncio.gather(digest_task, return_exceptions=True)
        if isinstance(error, TimeoutError):
            raise HTTPException(status_code=503, detail='Speech is busy. Please try again in a moment.') from error
        raise
    digest = await digest_task
    speech_input_ms = round((time.monotonic()-started)*1000, 2)
    text = " ".join(turn["text"] for turn in heard["turns"]).strip()
    if not text:
        return {"transcript": "", "reply": None, "audio": None}

    reply_started = time.monotonic()
    try:
        answer = await asyncio.to_thread(
            live_conversation.reply, past, text, digest, (user.name or "").split(" ")[0] or None, heard.get("language")
        )
    except Exception:
        logger.exception("Wilco Live reply failed")
        answer = "Sorry, abhi jawab nahi de paaya. Ek baar phir boliye?"
    if not answer:
        answer = "Sorry, main samjha nahi. Ek baar phir boliye?"
    reply_ms = round((time.monotonic()-reply_started)*1000, 2)
    tts_started = time.monotonic()
    spoken_language = live_conversation.speech_language(heard.get('language')) if heard.get('language') else tts_service.language_for_text(answer)
    try:
        async with asyncio.timeout(8):
            speech = await tts_service.synthesize(answer, spoken_language)
        encoded = base64.b64encode(speech).decode()
    except Exception:
        logger.exception("Wilco Live speech failed")
        encoded = None
    timings = {'input_and_context_ms': speech_input_ms, 'reply_ms': reply_ms,
               'tts_ms': round((time.monotonic()-tts_started)*1000, 2),
               'total_ms': round((time.monotonic()-started)*1000, 2)}
    logger.info('live_turn_timing %s', json.dumps(timings))
    return {"transcript": text, "reply": answer, "audio": encoded, "language": heard.get("language"),
            'timings': timings, 'speech_provider': 'gnani', 'speech_model': tts_service.voice_for(spoken_language)[0],
            'speech_voice': tts_service.voice_for(spoken_language)[1], 'speech_language': spoken_language}
