"""Ingest for the calendar-invited notetaker bot (backend/bot).

People add the notetaker's Google account to a calendar event the way they
would add fred@fireflies.ai; the bot joins the Meet, records it, and posts the
audio plus Meet's captions here. There is no signed-in Charcha user on the
other end, so this route authenticates the bot with a shared secret and then
files the meeting under the event's organizer — or, when the organizer has no
Charcha account, the first invitee who does.
"""

import asyncio
import datetime
import hmac
import json
import logging
import re
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.db import get_db
from app.database.models import CaptureEvent, CaptureRequest, LiveCaption as LiveCaptionRow, Meeting, MeetingInsight, RecordingSession, ServiceHeartbeat, User
from app.routes import meetings
from app.routes.recordings import _session_dir, _speaker_activity
from app.services import attendee_service, board_service, capture_service, live_assist, notetaker_monitor, processing_service, series_service, usage_ledger, speaker_mapping, transcriber, transcript_service, voice_identity

router = APIRouter(prefix="/api/bot", tags=["bot"])
logger = logging.getLogger(__name__)

# Below this the recording is a few seconds of silence (the bot was let in
# and immediately removed) — not worth a Prisma call.
MIN_AUDIO_BYTES = 16 * 1024
# How long before its scheduled start a queued visit may be handed out.
CLAIM_EARLY = datetime.timedelta(minutes=5)


class BotAttendee(BaseModel):
    email: str | None = Field(default=None, max_length=320)
    name: str = Field(default="", max_length=200)


class BotCaption(BaseModel):
    speaker: str = Field(default="", max_length=200)
    text: str = Field(default="", max_length=20000)
    # Seconds from the start of the uploaded audio.
    start: float = 0.0
    end: float = 0.0


class BotMeetingMetadata(BaseModel):
    event_id: str = Field(max_length=1024)
    event_start: str = Field(max_length=64)
    title: str = Field(default="", max_length=500)
    organizer_email: str | None = Field(default=None, max_length=320)
    attendees: list[BotAttendee] = Field(default_factory=list, max_length=200)
    captions: list[BotCaption] = Field(default_factory=list, max_length=20000)
    duration_seconds: int = Field(default=0, ge=0)
    language: str = "hinglish"
    bot_display_name: str = Field(default="", max_length=200)
    # Set when this visit came from "add the notetaker to a live meeting"
    # rather than a calendar invite.
    capture_request_id: uuid.UUID | None = None


def require_bot(authorization: str = Header("")) -> None:
    if not settings.bot_api_secret:
        raise HTTPException(status_code=503, detail="Notetaker bot is not configured")
    supplied = authorization.removeprefix("Bot ").strip()
    if not hmac.compare_digest(supplied.encode(), settings.bot_api_secret.encode()):
        raise HTTPException(status_code=401, detail="Invalid bot credentials")


async def _active_user_by_email(db: AsyncSession, email: str | None) -> User | None:
    email = (email or "").strip().lower()
    if not email or email == settings.notetaker_email.lower():
        return None
    return (
        await db.execute(select(User).where(func.lower(User.email) == email, User.status == "active"))
    ).scalar_one_or_none()


async def _resolve_owner(db: AsyncSession, meta: BotMeetingMetadata) -> User | None:
    notetaker = settings.notetaker_email.lower()
    candidates = [meta.organizer_email or ""] + [a.email or "" for a in meta.attendees]
    for email in (c.strip().lower() for c in candidates):
        if not email or email == notetaker:
            continue
        user = (
            await db.execute(
                select(User).where(func.lower(User.email) == email, User.status == "active")
            )
        ).scalar_one_or_none()
        if user is not None:
            return user
    return None


@router.post("/ingest", dependencies=[Depends(require_bot)])
async def bot_ingest(
    request: Request,
    background_tasks: BackgroundTasks,
    metadata: str = Form(...),
    audio: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        meta = BotMeetingMetadata.model_validate_json(metadata)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=f"Invalid metadata: {error}")
    if meta.language not in meetings.SUPPORTED_LANGUAGES:
        meta.language = "hinglish"

    capture: CaptureRequest | None = None
    if meta.capture_request_id is not None:
        capture = await db.get(CaptureRequest, meta.capture_request_id)
    owner = await _resolve_owner(db, meta)
    if capture is not None:
        # Someone asked for this visit by URL; it belongs to them, whatever
        # the bot believes the organizer was.
        owner = await db.get(User, capture.user_id)
    if owner is None:
        # Nobody on the invite has a Charcha account — there is no one to file
        # the meeting under and no one who could ever read it.
        logger.info("Bot meeting %s skipped: no internal attendee", meta.event_id)
        await _finish_without_notes(db, capture, "Nobody on the invite has a Charcha account, so there was no one to save the notes for.")
        return {"status": "skipped", "reason": "no_internal_attendee"}

    # Transcription and notes for this meeting are billed to its owner.
    usage_ledger.attribute(user_id=owner.id)
    bot_names = {meta.bot_display_name} if meta.bot_display_name else set()
    captions = [
        {**c.model_dump(), "speaker": speaker_mapping.speaker_display_name(c.speaker)} for c in meta.captions
    ]
    audio_bytes = await audio.read() if audio is not None else b""
    if len(audio_bytes) > meetings.MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio file exceeds the 100 MB limit")
    mime_type = (audio.content_type if audio else None) or "audio/webm"

    detailed: dict | None = None
    transcription_error: Exception | None = None
    speaker_names: dict[str, str] = {}
    transcript = ""
    if len(audio_bytes) >= MIN_AUDIO_BYTES:
        caption_speakers = {c["speaker"] for c in captions if c["speaker"]} - bot_names
        try:
            detailed = await transcriber.transcribe_audio_detailed(
                audio_bytes, mime_type, meta.language,
                expected_speakers=len(caption_speakers) or None,
                # The names on the invite and the names Meet showed speaking.
                people=[a.name for a in meta.attendees if a.name] + sorted(caption_speakers),
            )
            speaker_names = speaker_mapping.name_speakers(detailed["turns"], captions, bot_names)
            try:
                candidate_emails = {a.email.strip().lower() for a in meta.attendees if a.email}
                candidates = await db.scalars(select(User.id).where(func.lower(User.email).in_(candidate_emails)))
                voice_names = await voice_identity.match_known_voices(
                    db, audio_bytes, detailed["turns"], set(candidates) | {owner.id}
                )
                for speaker, name in voice_names.items():
                    speaker_names.setdefault(speaker, name)
            except Exception:
                logger.exception("Voice matching skipped for bot meeting %s", meta.event_id)
            transcript = transcriber.format_transcript(detailed["turns"], speaker_names)
            detailed["transcript"] = transcript
        except Exception as error:
            # Captions are a worse transcript, but a meeting saved from them
            # beats a meeting lost to a Prisma outage. The audio is still
            # stored below, so transcription can be retried from it.
            logger.exception("Prisma failed for bot meeting %s; using captions", meta.event_id)
            detailed = None
            transcription_error = error
    if not transcript.strip():
        transcript = speaker_mapping.captions_transcript(captions, bot_names)
    if not transcript.strip():
        seconds = meta.duration_seconds
        await _finish_without_notes(
            db, capture,
            "Nothing was said while the notetaker was in the call"
            + (f" ({seconds} s)" if seconds and seconds < 120 else "") + ", so there are no notes.",
        )
        raise HTTPException(status_code=422, detail="Nothing was said in this meeting")

    # Who may read the notes (see attendee_service):
    #  * granted — calendar invitees, and every colleague who asked for this
    #    visit (the requester plus anyone who subscribed to it);
    #  * pending — people the notetaker *saw* in the call (caption speakers)
    #    who were not on the invite; the organizer or an admin decides.
    notetaker = settings.notetaker_email.lower()
    attendees: list = [
        {"email": a.email, "name": a.name, "access": "granted", "source": "calendar"}
        for a in meta.attendees
        if (a.email or "").lower() != notetaker
    ]
    if capture is not None:
        for subscriber_id in await capture_service.subscriber_ids(db, capture.id):
            attendees.append({"user_id": str(subscriber_id), "access": "granted", "source": "requested"})
    attendees += [
        {"name": name, "access": "pending", "source": "meet"}
        for name in sorted(
            set(speaker_names.values()) | ({c["speaker"] for c in captions if c["speaker"]} - bot_names)
        )
    ]

    owner_id = owner.id
    duration_minutes = round(meta.duration_seconds / 60)
    meeting_code = capture.meeting_code if capture is not None else None
    series_key = series_service.series_key_for(capture.series_key if capture is not None else None, meeting_code)
    template = capture.template if capture is not None else "auto"
    if template == "auto":
        # Nobody chose a notes style: reuse the series' one, or detect the type.
        template = await series_service.resolve_template(db, series_key, transcript)
    result = await meetings.ingest_meeting(
        request=request,
        background_tasks=background_tasks,
        meeting_title=meta.title,
        duration_minutes=duration_minutes,
        spreadsheet_id=None,
        google_sheets_token=None,
        tasks_sheet_name=None,
        notes_sheet_name=None,
        meeting_language=meta.language,
        transcript=transcript,
        audio=None,
        # Stable per calendar occurrence, so a bot retry after a timeout
        # returns the stored meeting instead of creating a second one.
        client_meeting_id=f"bot:{meta.event_id}:{meta.event_start}",
        attendees=json.dumps(attendees),
        template=template,
        source="capture" if capture is not None else "bot",
        user=owner,
        db=db,
    )
    meeting_row = await db.get(Meeting, uuid.UUID(result["meeting_id"]))
    if meeting_row is not None and not result.get("deduplicated"):
        meeting_row.meeting_code = meeting_code
        meeting_row.series_key = series_key
        if series_key:
            background_tasks.add_task(series_service.review_carry_over, meeting_row.id)
        organizer = await _active_user_by_email(db, meta.organizer_email)
        if organizer is not None:
            meeting_row.organizer_user_id = organizer.id
        managers = [owner_id] + ([organizer.id] if organizer is not None else [])
        await attendee_service.notify_pending(db, meeting_row, managers)
        await db.commit()

    if capture is not None:
        capture = await db.get(CaptureRequest, capture.id)
        capture.meeting_id = uuid.UUID(result["meeting_id"])
        if capture.live_tasks and not result.get("deduplicated"):
            await _attach_live_tasks(db, capture, capture.meeting_id)
        if meeting_row is not None:
            await board_service.finalize_capture_board(db, capture, meeting_row)
        if capture_service.can_transition(capture.status, "completed"):
            capture.status = "completed"
            capture.status_detail = None
        await db.commit()

    if len(audio_bytes) >= MIN_AUDIO_BYTES and not result.get("deduplicated"):
        # Always keep the audio — playback, click-to-seek and a later
        # transcription retry all depend on it, Prisma outage or not.
        await _store_recording(db, owner_id, result, meta, audio_bytes, mime_type, detailed, speaker_names, captions, bot_names)
        if detailed is None and transcription_error is not None:
            await processing_service.set_stage(
                uuid.UUID(result["meeting_id"]), "transcription", "failed",
                error=f"Audio transcription failed, so Meet's captions were used instead: {transcription_error}",
            )
    return {"status": "ingested", **result}


async def _finish_without_notes(db: AsyncSession, capture: CaptureRequest | None, reason: str) -> None:
    """The visit ended but produced no meeting. Say so, instead of leaving it
    on "Left the meeting — processing" forever."""
    if capture is None:
        return
    capture = await db.get(CaptureRequest, capture.id)
    if capture is not None and capture_service.can_transition(capture.status, "failed"):
        capture.status, capture.status_detail = "failed", reason
        await db.commit()


async def _store_recording(
    db: AsyncSession,
    owner_id: uuid.UUID,
    result: dict,
    meta: BotMeetingMetadata,
    audio_bytes: bytes,
    mime_type: str,
    detailed: dict | None,
    speaker_names: dict[str, str],
    captions: list[dict],
    bot_names: set[str],
) -> None:
    """Attach the audio (and its diarization, when there is one) to the
    meeting exactly as an extension recording would be, so playback and the
    speaker editor work — pre-seeding the diarization cache so it is never
    paid for twice. Without a diarization, the caption lines keep their
    timings so clicking a line still seeks the audio."""
    meeting_id = uuid.UUID(result["meeting_id"])
    try:
        recording = RecordingSession(
            user_id=owner_id,
            meeting_id=meeting_id,
            title=result["title"],
            meeting_type="online",
            language=meta.language,
            participants=sorted(set(speaker_names.values())) or None,
            status="processed",
            mime_type=mime_type,
            duration_seconds=meta.duration_seconds,
            chunk_count=1,
            total_bytes=len(audio_bytes),
            ended_at=datetime.datetime.now(datetime.UTC),
        )
        db.add(recording)
        await db.flush()

        directory = _session_dir(recording.id)
        (directory / "recording.webm").write_bytes(audio_bytes)
        # Meet's captions are the only record of who Meet heard speaking; kept
        # so a misnamed transcript can be traced afterwards.
        (directory / "captions.json").write_text(json.dumps(captions, ensure_ascii=False), encoding="utf-8")
        if detailed is None:
            meeting = await db.get(Meeting, meeting_id)
            if meeting is not None:
                await transcript_service.replace_segments(
                    db, meeting, _caption_segments(captions, bot_names), language=meta.language
                )
            await db.commit()
            return
        (directory / "recording.diarization.json").write_text(
            json.dumps(detailed, ensure_ascii=False), encoding="utf-8"
        )
        (directory / "recording.txt").write_text(detailed["transcript"], encoding="utf-8")
        if speaker_names:
            (directory / "speaker_names.json").write_text(
                json.dumps(speaker_names, ensure_ascii=False), encoding="utf-8"
            )

        insight = await db.get(MeetingInsight, meeting_id)
        if insight is not None:
            insight.speaker_activity = _speaker_activity(detailed["turns"], speaker_names)
        meeting = await db.get(Meeting, meeting_id)
        if meeting is not None:
            # Same text the meeting was ingested with, now with timestamps;
            # evidence re-anchors by its (identical) quotes.
            await transcript_service.sync_from_turns(db, meeting, detailed["turns"], speaker_names)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("Bot meeting %s saved without its recording", meeting_id)


# --- live capture requests ----------------------------------------------------


class ClaimRequest(BaseModel):
    capacity: int = Field(default=1, ge=0, le=10)
    # Reported by notetakers new enough to know them; shown in Admin → Notetaker.
    instance: str | None = Field(default=None, max_length=100)
    max_concurrent: int | None = Field(default=None, ge=0, le=50)
    active: int | None = Field(default=None, ge=0, le=50)
    has_auth: bool | None = None
    # What this notetaker can join. One from before Teams sends nothing, and
    # must not be handed a link it would fail on while a deploy waits for it
    # to be idle.
    platforms: list[str] = Field(default_factory=lambda: ["google_meet"], max_length=10)


class CaptureEventIn(BaseModel):
    event_id: str = Field(min_length=8, max_length=200)
    status: str
    detail: str | None = Field(default=None, max_length=2000)
    occurred_at: datetime.datetime


async def _heartbeat(db: AsyncSession, detail: dict | None = None, instance: str | None = None) -> None:
    """The shared "notetaker" row says whether any notetaker is online; each
    named instance also keeps its own row for Admin → Notetaker."""
    now = datetime.datetime.now(datetime.UTC)
    names = ["notetaker"] + ([f"{notetaker_monitor.INSTANCE_PREFIX}{instance}"] if instance else [])
    for name in names:
        values = {"last_seen_at": now} if detail is None else {"last_seen_at": now, "detail": detail}
        await db.execute(
            pg_insert(ServiceHeartbeat)
            .values(name=name, **values)
            .on_conflict_do_update(index_elements=["name"], set_=values)
        )


@router.post("/capture-requests/claim", dependencies=[Depends(require_bot)])
async def claim_capture_requests(body: ClaimRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Polled by the bot's scheduler every tick — doubling as its heartbeat.
    SKIP LOCKED means two bot replicas can never claim the same request."""
    instance = re.sub(r"[^A-Za-z0-9._-]", "", body.instance or "")[:100] or None
    await _heartbeat(
        db,
        {"capacity": body.capacity, "max_concurrent": body.max_concurrent, "active": body.active, "has_auth": body.has_auth},
        instance,
    )
    await capture_service.expire_unclaimed(db)
    jobs = []
    if body.capacity:
        not_before = datetime.datetime.now(datetime.UTC) + CLAIM_EARLY
        rows = (
            await db.execute(
                select(CaptureRequest)
                .where(
                    CaptureRequest.status == "requested",
                    CaptureRequest.platform.in_(body.platforms),
                    # A visit whose meeting was moved later waits for its new time.
                    or_(CaptureRequest.scheduled_start.is_(None), CaptureRequest.scheduled_start <= not_before),
                )
                .order_by(CaptureRequest.created_at)
                .limit(body.capacity)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        now = datetime.datetime.now(datetime.UTC)
        for capture in rows:
            requester = await db.get(User, capture.user_id)
            capture.status = "joining"
            capture.status_detail = "The notetaker picked up the request"
            capture.claimed_at = now
            capture.last_event_at = now
            jobs.append(
                {
                    "capture_request_id": str(capture.id),
                    "meet_url": capture.meeting_url,
                    "meeting_code": capture.meeting_code,
                    "title": capture.title or "",
                    "organizer_email": capture.organizer_email or (requester.email if requester else None),
                    "attendees": capture.invitees or [],
                    "event_id": f"capture-{capture.id}",
                    "event_start": now.isoformat(),
                    # Lets the bot cap its stay to the scheduled meeting.
                    "event_end": capture.scheduled_end.isoformat() if capture.scheduled_end else None,
                    # For the notice the notetaker posts in the call's chat.
                    "requested_by_name": (requester.name or requester.email.split("@")[0]) if requester else None,
                    "app_url": (settings.public_app_url or "").rstrip("/") or None,
                }
            )
    await db.commit()
    return {"jobs": jobs}


class LiveCaption(BaseModel):
    speaker: str = Field(default="", max_length=200)
    text: str = Field(default="", max_length=5000)
    start: float = 0.0


class LiveQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    captions: list[LiveCaption] = Field(default_factory=list, max_length=20_000)
    capture_request_id: uuid.UUID | None = None
    title: str = Field(default="", max_length=500)


class CaptionChunk(BaseModel):
    seq: int = Field(ge=1, le=100000)
    speaker: str = Field(default="", max_length=200)
    text: str = Field(min_length=1, max_length=2000)
    start: float = Field(ge=0, le=28800)
    end: float = Field(ge=0, le=28800)


class CaptionBatch(BaseModel):
    captions: list[CaptionChunk] = Field(max_length=50)


@router.post("/capture-requests/{request_id}/captions", dependencies=[Depends(require_bot)])
async def live_captions(
    request_id: uuid.UUID,
    body: CaptionBatch,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Persist finalized caption deltas; AI runs separately and infrequently."""
    capture = await db.get(CaptureRequest, request_id)
    if capture is None or capture.status not in {"capturing", "stopped"}:
        raise HTTPException(status_code=404, detail="Active capture not found")
    await board_service.ensure_for_capture(db, capture)
    rows = []
    for chunk in body.captions:
        if chunk.end < chunk.start:
            raise HTTPException(status_code=422, detail="Caption end precedes start")
        rows.append({
            "capture_request_id": request_id, "seq": chunk.seq,
            "speaker": chunk.speaker.strip() or "Someone", "text": chunk.text.strip(),
            "start_seconds": chunk.start, "end_seconds": chunk.end,
        })
    if rows:
        statement = pg_insert(LiveCaptionRow).values(rows).on_conflict_do_nothing(constraint="uq_live_caption_seq")
        await db.execute(statement)
    await db.commit()
    if rows:
        background_tasks.add_task(board_service.refresh_live_board, request_id)
    return {"accepted": len(rows)}


@router.post("/capture-requests/{request_id}/board/refresh", dependencies=[Depends(require_bot)])
async def request_live_board(
    request_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    capture = await db.get(CaptureRequest, request_id)
    if capture is None or capture.status not in {"capturing", "stopped"}:
        raise HTTPException(status_code=404, detail="Active capture not found")
    board = await board_service.ensure_for_capture(db, capture)
    await db.commit()
    background_tasks.add_task(board_service.refresh_live_board, request_id, force=True)
    return {"board_id": str(board.id), "url": f"{settings.public_app_url.rstrip('/')}/meetings/live/{request_id}"}


class LiveBoardCommand(BaseModel):
    command_id: uuid.UUID
    command: str = Field(min_length=1, max_length=1000)


@router.get("/capture-requests/{request_id}/board", dependencies=[Depends(require_bot)])
async def bot_board_state(request_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    capture = await db.get(CaptureRequest, request_id)
    if capture is None or capture.status != "capturing":
        raise HTTPException(status_code=404, detail="Active capture not found")
    board = await board_service.ensure_for_capture(db, capture)
    from app.services import figjam_service
    connection = await figjam_service.connection_for(db, request_id)
    await db.commit()
    return {**board_service.serialize(board), 'external_url': connection.file_url if connection else None}


@router.post("/capture-requests/{request_id}/board/commands", dependencies=[Depends(require_bot)])
async def bot_board_command(request_id: uuid.UUID, body: LiveBoardCommand, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await board_service.command_capture_board(db, request_id, body.command_id, body.command)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except board_service.BoardCommandConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/live-answer", dependencies=[Depends(require_bot)])
async def live_answer(body: LiveQuestion, db: AsyncSession = Depends(get_db)) -> dict:
    """A question typed in the call's chat, answered from that call's own
    captions so far (never company memory: guests can ask too)."""
    if body.capture_request_id:
        capture = await db.get(CaptureRequest, body.capture_request_id)
        if capture is not None:
            usage_ledger.attribute(user_id=capture.user_id)
    try:
        text = await asyncio.to_thread(
            live_assist.answer, body.question, [c.model_dump() for c in body.captions], body.title
        )
    except Exception:
        logger.exception("Live answer failed")
        text = "Sorry, I couldn't answer that just now. Try again in a moment."
    return {"answer": text}


class BotSpeech(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


@router.post("/speak", dependencies=[Depends(require_bot)])
async def bot_speak(body: BotSpeech) -> Response:
    """MP3 of an answer, for the notetaker to say in the call (Gnani Timbre)."""
    from app.services import tts_service

    try:
        async with asyncio.timeout(8):
            audio = await tts_service.synthesize(body.text, tts_service.language_for_text(body.text))
    except (tts_service.SpeechNotConfigured, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Response(content=audio, media_type="audio/mpeg")


class LiveTask(BaseModel):
    capture_request_id: uuid.UUID
    text: str = Field(min_length=2, max_length=1000)


@router.post("/live-task", dependencies=[Depends(require_bot)])
async def live_task(body: LiveTask, db: AsyncSession = Depends(get_db)) -> dict:
    """"Charcha, add task: ..." from the call's chat. Held on the visit until
    the meeting exists, then created as a real task (origin "live")."""
    capture = await db.get(CaptureRequest, body.capture_request_id)
    if capture is None:
        raise HTTPException(status_code=404, detail="Unknown capture request")
    usage_ledger.attribute(user_id=capture.user_id)
    task = await asyncio.to_thread(live_assist.parse_task, body.text)
    task["said_at"] = datetime.datetime.now(datetime.UTC).isoformat()
    capture = (await db.execute(select(CaptureRequest).where(CaptureRequest.id == capture.id)
        .with_for_update().execution_options(populate_existing=True))).scalar_one()
    capture.live_tasks = [*(capture.live_tasks or []), task]
    await db.commit()
    return {"reply": live_assist.task_confirmation(task), "task": task}


async def _attach_live_tasks(db: AsyncSession, capture: CaptureRequest, meeting_id: uuid.UUID) -> None:
    """Creates the tasks people added from the call's chat on its meeting."""
    from app.database.models import MeetingTask
    from app.services import insight_service

    for item in capture.live_tasks or []:
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        owner = str(item.get("owner") or "").strip() or None
        db.add(
            MeetingTask(
                meeting_id=meeting_id,
                owner=owner,
                description=description,
                deadline=str(item.get("deadline") or "").strip() or None,
                origin="live",
                owner_user_id=await insight_service.resolve_owner_user_id(db, meeting_id, owner),
            )
        )
    capture.live_tasks = None


@router.get("/capture-requests/{request_id}", dependencies=[Depends(require_bot)])
async def capture_request_state(request_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    capture = await db.get(CaptureRequest, request_id)
    if capture is None:
        raise HTTPException(status_code=404, detail="Unknown capture request")
    return {
        "status": capture.status,
        "stop_requested": capture.stop_requested_at is not None,
        # The bot re-reads this, so a calendar event extended mid-meeting
        # keeps it in the call.
        "scheduled_end": capture.scheduled_end.isoformat() if capture.scheduled_end else None,
    }


@router.post("/capture-requests/{request_id}/events", dependencies=[Depends(require_bot)])
async def capture_request_event(
    request_id: uuid.UUID, body: CaptureEventIn, db: AsyncSession = Depends(get_db)
) -> dict:
    """Record a lifecycle event. Duplicates are acknowledged and ignored;
    events that would move the request backwards (late, out of order, or
    after it finished) are kept for the record but not applied."""
    capture = await db.get(CaptureRequest, request_id, with_for_update=True)
    if capture is None:
        raise HTTPException(status_code=404, detail="Unknown capture request")
    if body.status not in capture_service.ALL_STATUSES:
        raise HTTPException(status_code=422, detail="Unknown status")
    occurred = body.occurred_at if body.occurred_at.tzinfo else body.occurred_at.replace(tzinfo=datetime.UTC)
    inserted = await db.execute(
        pg_insert(CaptureEvent)
        .values(
            capture_request_id=capture.id,
            provider_event_id=body.event_id,
            status=body.status,
            detail=body.detail,
            occurred_at=occurred,
        )
        .on_conflict_do_nothing(index_elements=["provider_event_id"])
        .returning(CaptureEvent.id)
    )
    event_id = inserted.scalar_one_or_none()
    if event_id is None:
        await db.commit()
        return {"applied": False, "duplicate": True, "status": capture.status}

    stale = capture.last_event_at is not None and occurred < capture.last_event_at and body.status not in capture_service.FINAL_STATUSES
    applied = not stale and capture_service.can_transition(capture.status, body.status)
    if applied:
        capture.status = body.status
        capture.status_detail = body.detail
        capture.last_event_at = max(occurred, capture.last_event_at or occurred)
        capture.updated_at = datetime.datetime.now(datetime.UTC)
        event = await db.get(CaptureEvent, event_id)
        event.applied = True
        await notetaker_monitor.alert_if_signed_out(db, body.status, body.detail)
    await _heartbeat(db)
    await db.commit()
    return {"applied": applied, "duplicate": False, "status": capture.status}


def _caption_segments(captions: list[dict], bot_names: set[str]) -> list[dict]:
    """Meet caption lines as timed transcript segments (seconds → ms)."""
    segments = []
    for caption in sorted(captions, key=lambda c: c.get("start", 0)):
        text = (caption.get("text") or "").strip()
        speaker = (caption.get("speaker") or "").strip()
        if not text or speaker in bot_names:
            continue
        segments.append(
            {
                "speaker_key": speaker,
                "speaker_label": speaker or None,
                "text": text,
                "start_ms": int(round(float(caption.get("start", 0)) * 1000)),
                "end_ms": int(round(float(caption.get("end", 0)) * 1000)),
                "confidence": None,
            }
        )
    return segments


class BotInvite(BaseModel):
    meet_url: str = Field(max_length=2000)
    title: str = Field(default="", max_length=500)
    organizer_email: str | None = Field(default=None, max_length=320)
    attendees: list[BotAttendee] = Field(default_factory=list, max_length=200)
    start: datetime.datetime | None = None
    end: datetime.datetime | None = None
    recurring_event_id: str | None = Field(default=None, max_length=1024)


@router.post("/invites", dependencies=[Depends(require_bot)])
async def bot_invite(body: BotInvite, db: AsyncSession = Depends(get_db)) -> dict:
    """The notetaker's own address was invited to an event that is about to
    start. It goes through the same queue as every other visit, so a meeting
    that a colleague's linked calendar (or a pasted link) already covers gets
    no second bot. Filed under the organizer, else the first invitee with a
    Charcha account; with nobody internal, there's no one to read the notes."""
    owner = await _active_user_by_email(db, body.organizer_email)
    if owner is None:
        for attendee in body.attendees:
            owner = await _active_user_by_email(db, attendee.email)
            if owner is not None:
                break
    if owner is None:
        return {"status": "skipped", "reason": "no_internal_attendee"}
    try:
        outcome = await capture_service.request_capture(
            db,
            owner,
            body.meet_url,
            title=body.title,
            source="invite",
            invitees=[a.model_dump() for a in body.attendees],
            organizer_email=body.organizer_email,
            scheduled_start=body.start,
            scheduled_end=body.end,
            template="auto",
            series_key=f"gcal:{body.recurring_event_id}" if body.recurring_event_id else None,
        )
    except capture_service.InvalidMeetingUrl as error:
        return {"status": "skipped", "reason": str(error)}
    return {"status": "queued", "capture_request_id": str(outcome.capture.id), "joined_existing": outcome.joined_existing}


class AgentCaption(BaseModel):
    speaker: str = Field(default="", max_length=100)
    text: str = Field(min_length=1, max_length=1500)
    start: float = Field(default=0, ge=0, le=28800, allow_inf_nan=False)


class AgentRequest(BaseModel):
    command_id: uuid.UUID
    command: str = Field(min_length=1, max_length=1000)
    tool: Literal["auto", "open_board", "edit_board", "add_task", "answer"] = "auto"
    board_active: bool = False
    present_after: bool = False
    board_provider: Literal['internal', 'figjam'] = 'internal'
    captions: list[AgentCaption] = Field(default_factory=list, max_length=120)


@router.post("/capture-requests/{request_id}/commands", status_code=202, dependencies=[Depends(require_bot)])
async def submit_agent_command(request_id: uuid.UUID, body: AgentRequest, db: AsyncSession = Depends(get_db)) -> dict:
    from app.services import meeting_agent
    try:
        payload = body.model_dump(exclude={"command_id"})
        job = await meeting_agent.submit(db, request_id, body.command_id, payload)
        return meeting_agent.serialize(job)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except meeting_agent.QueueFull as error:
        raise HTTPException(status_code=429, detail="The meeting agent is busy. Please wait for an active request to finish.", headers={"Retry-After": "2"}) from error


@router.get("/capture-requests/{request_id}/commands/{command_id}", dependencies=[Depends(require_bot)])
async def agent_command_state(request_id: uuid.UUID, command_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    from app.services import meeting_agent
    from app.database.models import MeetingAgentJob
    await meeting_agent.expire_deadlines(db, request_id)
    job = await db.scalar(select(MeetingAgentJob).where(MeetingAgentJob.capture_request_id == request_id,
                                                      MeetingAgentJob.command_id == command_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Command not found")
    return meeting_agent.serialize(job)


@router.post("/capture-requests/{request_id}/commands/{command_id}/cancel", dependencies=[Depends(require_bot)])
async def cancel_agent_command(request_id: uuid.UUID, command_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    from app.services import meeting_agent
    try:
        return meeting_agent.serialize(await meeting_agent.cancel(db, request_id, command_id))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/capture-requests/{request_id}/commands", dependencies=[Depends(require_bot)])
async def outstanding_agent_commands(request_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[dict]:
    from app.services import meeting_agent
    from app.database.models import MeetingAgentJob
    capture = await db.get(CaptureRequest, request_id)
    if capture is None or capture.status != "capturing":
        raise HTTPException(status_code=404, detail="Active capture not found")
    await meeting_agent.expire_deadlines(db, request_id)
    rows = (await db.scalars(select(MeetingAgentJob).where(
        MeetingAgentJob.capture_request_id == request_id, MeetingAgentJob.delivered_at.is_(None))
        .order_by(case((MeetingAgentJob.state.in_(["accepted", "running"]), 0), else_=1),
                  MeetingAgentJob.created_at).limit(64))).all()
    return [meeting_agent.serialize(job) for job in rows]


@router.post("/capture-requests/{request_id}/commands/{command_id}/delivered", dependencies=[Depends(require_bot)])
async def agent_command_delivered(request_id: uuid.UUID, command_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    from app.services import meeting_agent
    from app.database.models import MeetingAgentJob
    job = await db.scalar(select(MeetingAgentJob).where(MeetingAgentJob.capture_request_id == request_id,
        MeetingAgentJob.command_id == command_id).with_for_update())
    if job is None:
        raise HTTPException(status_code=404, detail="Command not found")
    if job.state not in meeting_agent.TERMINAL:
        raise HTTPException(status_code=409, detail="Command is still running")
    job.delivered_at = job.delivered_at or datetime.datetime.now(datetime.UTC)
    await db.commit()
    return {"delivered": True}
