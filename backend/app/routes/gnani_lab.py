"""Built on Gnani: try each Gnani model live, and manage your cloned voice.

Prisma (speech-to-text), Timbre v2.5/v3 (text-to-speech), Timbre voice
cloning, and Evon (Indic LLM, when a server is configured)."""
import base64
import datetime as dt
import time
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.db import get_db
from app.database.models import User, VoiceClone, VoiceUpdate
from app.dependencies import get_current_user, is_demo, require_full_account
from app.rate_limit import limiter
from app.services import capture_service, evon_service, transcriber, tts_service, usage_ledger, voice_clone_service

router = APIRouter(prefix="/api/gnani", tags=["gnani"])
MAX_SAMPLE_BYTES = 8 * 1024 * 1024
VOICE_UPDATE_HOURS = 24


def _ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 1)


@router.get("/models")
async def models(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """What Wilco runs on, and whether each model is reachable from here."""
    clone = await db.get(VoiceClone, user.id)
    speech = bool(settings.gnani_api_key)
    return {
        "prisma": {"configured": speech, "model": settings.gnani_stt_model, "mode": settings.gnani_stt_mode},
        "timbre": {"configured": speech, "fast_model": settings.gnani_tts_model, "fast_voice": settings.gnani_tts_voice,
                   "english_voice": settings.gnani_tts_english_voice, "multilingual_model": settings.gnani_tts_multilingual_model,
                   "multilingual_voice": settings.gnani_tts_multilingual_voice},
        "demo": is_demo(user),
        "voice_clone": {"configured": speech, "model": voice_clone_service.VC_MODEL, "enrolled": clone is not None,
                        "consented_at": clone.consented_at.isoformat() if clone else None},
        "evon": {"configured": evon_service.configured(), "model": settings.evon_model},
        "warp": {"configured": False},
    }


@router.post("/prisma")
@limiter.limit("20/minute")
async def try_prisma(request: Request, audio: UploadFile = File(...), user: User = Depends(get_current_user)) -> dict:
    """Speak anything: Prisma's transcript, detected language and latency."""
    data = await audio.read()
    if not data or len(data) > MAX_SAMPLE_BYTES:
        raise HTTPException(status_code=422, detail="Record a short clip (up to about a minute).")
    usage_ledger.attribute(user_id=user.id)
    started = time.monotonic()
    try:
        heard = await transcriber.transcribe_audio_detailed(
            data, audio.content_type or "audio/webm", "auto", timeout_seconds=20, interactive=True)
    except transcriber.TranscriptionNotConfigured as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Prisma couldn't transcribe that. Try again.") from error
    text = " ".join(turn["text"] for turn in heard.get("turns") or []).strip()
    return {"text": text, "language": heard.get("language"), "model": heard.get("model") or settings.gnani_stt_model,
            "speakers": len({turn.get("speaker") for turn in heard.get("turns") or [] if turn.get("speaker") is not None}),
            "latency_ms": _ms(started)}


class TimbreRequest(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    language: str = Field(min_length=2, max_length=8)


@router.post("/timbre")
@limiter.limit("30/minute")
async def try_timbre(request: Request, body: TimbreRequest, user: User = Depends(get_current_user)) -> dict:
    if body.language not in tts_service.SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail="Pick one of the listed languages.")
    usage_ledger.attribute(user_id=user.id)
    model, voice = tts_service.voice_for(body.language)
    started = time.monotonic()
    try:
        audio = await tts_service.synthesize(body.text, body.language)
    except tts_service.SpeechNotConfigured as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Timbre couldn't speak that right now. Try again.") from error
    return {"audio": base64.b64encode(audio).decode(), "model": model, "voice": voice,
            "language": body.language, "latency_ms": _ms(started)}


@router.post("/voice-clone")
@limiter.limit("5/minute")
async def enroll_voice(request: Request, audio: UploadFile = File(...), consent: bool = Form(False),
                       user: User = Depends(require_full_account), db: AsyncSession = Depends(get_db)) -> dict:
    """Save an AI copy of your own voice. Needs your explicit consent; the
    sample is discarded once Gnani returns the voice embedding."""
    if not consent:
        raise HTTPException(status_code=422, detail="Confirm that this is your own voice and you agree to an AI copy of it.")
    data = await audio.read()
    if not data or len(data) > MAX_SAMPLE_BYTES:
        raise HTTPException(status_code=422, detail="Record 10 to 30 seconds of your voice.")
    usage_ledger.attribute(user_id=user.id)
    try:
        embedding = await voice_clone_service.create_embedding(data)
    except voice_clone_service.VoiceCloneError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except tts_service.SpeechNotConfigured as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Gnani couldn't learn your voice right now. Try again.") from error
    clone = await db.get(VoiceClone, user.id) or VoiceClone(user_id=user.id)
    clone.embedding_encrypted = voice_clone_service.seal(embedding["embedding"])
    clone.shape, clone.dtype = embedding["shape"], embedding["dtype"]
    clone.consented_at = dt.datetime.now(dt.UTC)
    db.add(clone)
    await db.commit()
    return {"enrolled": True}


@router.delete("/voice-clone")
async def delete_voice(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """Forget your cloned voice and any updates still waiting to be spoken."""
    await db.execute(delete(VoiceUpdate).where(VoiceUpdate.user_id == user.id, VoiceUpdate.delivered_at.is_(None)))
    await db.execute(delete(VoiceClone).where(VoiceClone.user_id == user.id))
    await db.commit()
    return {"enrolled": False}


class CloneSpeech(BaseModel):
    text: str = Field(min_length=1, max_length=600)


@router.post("/voice-clone/speak")
@limiter.limit("20/minute")
async def speak_in_my_voice(request: Request, body: CloneSpeech, user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)) -> dict:
    clone = await db.get(VoiceClone, user.id)
    if clone is None:
        raise HTTPException(status_code=404, detail="Record your voice first.")
    usage_ledger.attribute(user_id=user.id)
    started = time.monotonic()
    try:
        audio = await voice_clone_service.speak(body.text, clone)
    except voice_clone_service.VoiceCloneError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Gnani couldn't speak in your voice right now. Try again.") from error
    return {"audio": base64.b64encode(audio).decode(), "model": voice_clone_service.VC_MODEL, "latency_ms": _ms(started)}


class EvonRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1000)


@router.post("/evon")
@limiter.limit("20/minute")
async def try_evon(request: Request, body: EvonRequest, user: User = Depends(get_current_user)) -> dict:
    if not evon_service.configured():
        raise HTTPException(status_code=503, detail="Evon isn't connected here. Set EVON_URL to an Evon v3.3 server.")
    started = time.monotonic()
    try:
        reply = await evon_service.chat("You are Wilco, a helpful assistant for Indian teams. Reply briefly in the user's language.",
                                        body.prompt, max_tokens=300)
    except Exception as error:
        raise HTTPException(status_code=502, detail="Evon didn't answer. Check the Evon server.") from error
    return {"reply": reply, "model": settings.evon_model, "latency_ms": _ms(started)}


# ---- Voice updates: your typed update, spoken in a call you'll miss -------------

class VoiceUpdateRequest(BaseModel):
    meeting_url: str = Field(min_length=8, max_length=500)
    text: str = Field(min_length=2, max_length=800)
    # What the AI stand-in may answer for you when someone asks in the call.
    briefing: str | None = Field(default=None, max_length=3000)


def _serialize_update(row: VoiceUpdate) -> dict:
    return {"id": str(row.id), "meeting_url": row.meeting_url, "text": row.text,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "expires_at": row.expires_at.isoformat(), "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
            "briefing": row.briefing, "qa": row.qa or []}


@router.get("/voice-updates")
async def my_voice_updates(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.scalars(select(VoiceUpdate).where(VoiceUpdate.user_id == user.id)
                             .order_by(VoiceUpdate.created_at.desc()).limit(20))).all()
    return [_serialize_update(row) for row in rows]


@router.post("/voice-updates")
@limiter.limit("10/minute")
async def create_voice_update(request: Request, body: VoiceUpdateRequest, user: User = Depends(require_full_account),
                              db: AsyncSession = Depends(get_db)) -> dict:
    if await db.get(VoiceClone, user.id) is None:
        raise HTTPException(status_code=409, detail="Record your voice first, so Wilco can speak your update.")
    try:
        _platform, code, url = capture_service.normalize_meeting_url(body.meeting_url)
    except capture_service.InvalidMeetingUrl as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    row = VoiceUpdate(user_id=user.id, meeting_code=code, meeting_url=url, text=body.text.strip(),
                      briefing=(body.briefing or "").strip() or None, qa=[],
                      expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(hours=VOICE_UPDATE_HOURS))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _serialize_update(row)


@router.delete("/voice-updates/{update_id}")
async def delete_voice_update(update_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    await db.execute(delete(VoiceUpdate).where(VoiceUpdate.id == update_id, VoiceUpdate.user_id == user.id))
    await db.commit()
    return {"deleted": True}
