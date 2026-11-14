"""Add the notetaker to a live meeting by pasting its link.

This is the user-facing half; the bot polls the other half in
app/routes/bot.py. Accepting a request only means it is queued — the UI shows
the bot's real progress (joining, waiting for admission, recording) as the
bot reports it.
"""

import datetime
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.db import get_db
from app.database.models import CaptureRequest, CaptureSubscriber, User
from app.dependencies import get_current_user, is_admin
from app.rate_limit import limiter
from app.routes.meeting_workspace import _notetaker_status
from app.services import ai_extractor, capture_service

router = APIRouter(prefix="/api/capture", tags=["capture"])


class CaptureCreate(BaseModel):
    meeting_url: str = Field(min_length=1, max_length=2000)
    title: str = Field(default="", max_length=200)
    template: str = "auto"
    consent_acknowledged: bool = False
    idempotency_key: str | None = Field(default=None, max_length=80)


async def _visible(db: AsyncSession, user: User, request_id: uuid.UUID) -> CaptureRequest:
    """A visit the user asked for (or subscribed to), or any visit for admins."""
    capture = await db.get(CaptureRequest, request_id)
    if capture is None:
        raise HTTPException(status_code=404, detail="Capture request not found")
    if capture.user_id == user.id or is_admin(user):
        return capture
    if user.id in await capture_service.subscriber_ids(db, capture.id):
        return capture
    raise HTTPException(status_code=404, detail="Capture request not found")


def _with_queue_note(data: dict) -> dict:
    if data["queue_position"]:
        data["status_detail"] = (
            f"All notetakers are in other meetings — {data['queue_position']} ahead of this one. "
            "It joins as soon as one is free."
        )
    return data


async def _describe_all(db: AsyncSession, captures: list[CaptureRequest], user: User) -> list[dict]:
    """serialize() plus what this person needs to know about sharing each."""
    return [_with_queue_note(data) for data in await capture_service.describe_many(db, captures, user)]


async def _describe(db: AsyncSession, capture: CaptureRequest, user: User) -> dict:
    return (await _describe_all(db, [capture], user))[0]


@router.get("/status")
async def capture_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return await _notetaker_status(db)


@router.post("/requests", status_code=201)
@limiter.limit("10/minute")
async def create_capture_request(
    request: Request,
    body: CaptureCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not settings.bot_api_secret:
        raise HTTPException(
            status_code=503,
            detail="Setup required: the meeting notetaker is not configured on this server (BOT_API_SECRET)",
        )
    if not body.consent_acknowledged:
        raise HTTPException(
            status_code=422,
            detail="Confirm that everyone in the meeting will be told it is being recorded",
        )
    if body.idempotency_key is not None and not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", body.idempotency_key):
        raise HTTPException(status_code=400, detail="Invalid idempotency key")

    if body.idempotency_key:
        existing = (
            await db.execute(
                select(CaptureRequest).where(
                    CaptureRequest.user_id == user.id, CaptureRequest.idempotency_key == body.idempotency_key
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {**await _describe(db, existing, user), "deduplicated": True, "joined_existing": False}

    try:
        outcome = await capture_service.request_capture(
            db,
            user,
            body.meeting_url,
            title=body.title,
            template="auto" if body.template == "auto" else ai_extractor.template_or_default(body.template),
            source="link",
            idempotency_key=body.idempotency_key,
        )
    except capture_service.InvalidMeetingUrl as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {
        **await _describe(db, outcome.capture, user),
        "deduplicated": outcome.already_subscribed,
        # Someone else already has the notetaker in (or on its way to) this
        # meeting: no second bot, and this person gets the same notes.
        "joined_existing": outcome.joined_existing,
    }


@router.get("/meet/{meeting_code}")
async def capture_for_meeting(
    meeting_code: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """What the in-Meet extension shows: is a notetaker already in this call
    (whoever asked for it), and does this person already get its notes?
    Knowing that a notetaker is in a call you are in reveals nothing new —
    it is in the participant list."""
    code = meeting_code.strip().lower()
    if not capture_service.MEET_URL_RE.match(f"meet.google.com/{code}"):
        raise HTTPException(status_code=422, detail="Not a Google Meet code")
    await capture_service.expire_unclaimed(db, throttle=True)
    await db.commit()
    active = await capture_service.active_for_code(db, code)
    if active is not None:
        return {"capture": await _describe(db, active, user)}
    # Otherwise the latest visit this person can see, so "notes ready" shows.
    recent = (
        await db.execute(
            select(CaptureRequest)
            .where(
                CaptureRequest.meeting_code == code,
                CaptureRequest.id.in_(
                    select(CaptureSubscriber.capture_request_id).where(CaptureSubscriber.user_id == user.id)
                ),
                CaptureRequest.updated_at > datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=12),
            )
            .order_by(CaptureRequest.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return {"capture": await _describe(db, recent, user) if recent else None}


@router.get("/requests")
async def list_capture_requests(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[dict]:
    await capture_service.expire_unclaimed(db, throttle=True)
    await db.commit()
    rows = (
        await db.execute(
            select(CaptureRequest)
            .where(
                CaptureRequest.id.in_(
                    select(CaptureSubscriber.capture_request_id).where(CaptureSubscriber.user_id == user.id)
                )
            )
            .order_by(CaptureRequest.created_at.desc())
            .limit(20)
        )
    ).scalars().all()
    return await _describe_all(db, list(rows), user)


@router.get("/requests/{request_id}")
async def get_capture_request(
    request_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    await capture_service.expire_unclaimed(db, throttle=True)
    await db.commit()
    return await _describe(db, await _visible(db, user, request_id), user)


@router.post("/requests/{request_id}/stop")
async def stop_capture(
    request_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """This person no longer needs the notetaker.

    If colleagues also asked for this meeting's notes, the notetaker stays for
    them and this person simply stops being one of its subscribers — one
    person can't silently cut everyone else's recording short (anyone in the
    call can still say "notetaker please leave"). When nobody is left, or an
    admin stops it, it leaves: a queued visit is cancelled outright; one in
    the call sees the flag within seconds and reports "stopped".
    """
    capture = await _visible(db, user, request_id)
    if capture.status not in capture_service.PROGRESS_RANK:
        return await _describe(db, capture, user)
    nobody_left = await capture_service.release(db, capture, user.id)
    now = datetime.datetime.now(datetime.UTC)
    if nobody_left or is_admin(user):
        if capture.status == "requested":
            capture.status = "cancelled"
            capture.status_detail = "Cancelled before the notetaker joined"
        else:
            capture.stop_requested_at = capture.stop_requested_at or now
    capture.updated_at = now
    await db.commit()
    data = await _describe(db, capture, user)
    data["kept_for_others"] = not (nobody_left or is_admin(user))
    return data
