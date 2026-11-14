"""Link a Google Calendar so the notetaker follows you to your meetings."""

import datetime
import logging
import urllib.parse
import uuid

import httpx

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.database.models import CAPTURE_ACTIVE_STATUSES, CalendarConnection, CalendarEvent, CaptureRequest, Meeting, User
from app.dependencies import get_current_user, meeting_visibility_clause
from app.services import calendar_service, capture_service, secret_box

router = APIRouter(prefix="/api/calendar", tags=["calendar"])
logger = logging.getLogger(__name__)


class ConnectionUpdate(BaseModel):
    auto_join: str


class EventUpdate(BaseModel):
    # True = record this one, False = skip it, None = follow my rule.
    record: bool | None = None


def _serialize_connection(connection: CalendarConnection | None) -> dict | None:
    if connection is None:
        return None
    return {
        "google_email": connection.google_email,
        "auto_join": connection.auto_join,
        "status": connection.status,
        "last_error": connection.last_error,
        "last_synced_at": connection.last_synced_at.isoformat() if connection.last_synced_at else None,
        # True while Google pushes changes the moment they happen.
        "live_updates": calendar_service.watch_active(connection),
        "live_updates_error": connection.watch_error,
    }


@router.get("")
async def calendar_state(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return {
        "configured": calendar_service.configured(),
        "connection": _serialize_connection(await db.get(CalendarConnection, user.id)),
    }


@router.post("/connect")
async def start_connect(user: User = Depends(get_current_user)) -> dict:
    if not calendar_service.configured():
        raise HTTPException(status_code=503, detail="Google Calendar linking isn't set up on this server yet")
    return {"url": calendar_service.authorization_url(user.id, login_hint=user.email)}


@router.get("/callback", include_in_schema=False)
async def oauth_callback(
    state: str = "", code: str = "", error: str = "", db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    """Google sends the browser here after the consent screen; we store the
    link and send the person back to Settings with the outcome."""
    def back(outcome: str, message: str = "") -> RedirectResponse:
        query = urllib.parse.urlencode({"calendar": outcome, **({"message": message[:200]} if message else {})})
        return RedirectResponse(calendar_service.app_url(f"/settings?{query}#calendar"), status_code=303)

    if error:
        return back("cancelled" if error == "access_denied" else "error", "" if error == "access_denied" else error)
    try:
        user_id = calendar_service.read_state(state)
        refresh_token, google_email = await calendar_service.exchange_code(code)
    except calendar_service.CalendarError as failure:
        return back("error", str(failure))
    user = await db.get(User, user_id)
    if user is None or user.status != "active":
        return back("error", "Your Charcha account isn't active")

    connection = await db.get(CalendarConnection, user_id)
    if connection is None:
        connection = CalendarConnection(user_id=user_id, google_email=google_email or user.email, refresh_token_encrypted="")
        db.add(connection)
    connection.google_email = google_email or user.email
    connection.refresh_token_encrypted = secret_box.encrypt(refresh_token)
    connection.status = "active"
    connection.last_error = None
    connection.last_synced_at = None
    await db.commit()
    # First sync right away so Settings shows the upcoming meetings.
    await calendar_service.sync_connection(db, connection)
    return back("connected")


@router.patch("")
async def update_connection(
    body: ConnectionUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    if body.auto_join not in calendar_service.AUTO_JOIN_MODES:
        raise HTTPException(status_code=422, detail="auto_join must be all, organized or manual")
    connection = await db.get(CalendarConnection, user.id)
    if connection is None:
        raise HTTPException(status_code=404, detail="No calendar is linked")
    connection.auto_join = body.auto_join
    await db.commit()
    # A rule change can switch off meetings that were already queued.
    for event in (await db.execute(select(CalendarEvent).where(CalendarEvent.user_id == user.id, CalendarEvent.capture_request_id.isnot(None)))).scalars().all():
        if event.record_override is None:
            await calendar_service.apply_override(db, event, None)
    return _serialize_connection(connection)


@router.post("/sync")
async def sync_now(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    connection = await db.get(CalendarConnection, user.id)
    if connection is None:
        raise HTTPException(status_code=404, detail="No calendar is linked")
    await calendar_service.sync_connection(db, connection)
    await calendar_service.dispatch_due(db)
    return _serialize_connection(connection)


@router.post("/push", include_in_schema=False)
async def google_push(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    """Google Calendar push notification: a linked calendar changed. Checked
    against the channel's own secret token; always answered 200 quickly
    (Google retries anything else), the re-read happens in the loop."""
    channel_id = request.headers.get("x-goog-channel-id", "")
    token = request.headers.get("x-goog-channel-token", "")
    state = request.headers.get("x-goog-resource-state", "")
    if channel_id:
        await calendar_service.handle_push(db, channel_id, token, state)
    return Response(status_code=200)


@router.delete("")
async def disconnect(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    connection = await db.get(CalendarConnection, user.id)
    if connection is None:
        return {"ok": True}
    for event in (await db.execute(select(CalendarEvent).where(CalendarEvent.user_id == user.id))).scalars().all():
        await calendar_service._release_if_queued(db, event)
    try:
        await calendar_service.stop_watch(connection, await calendar_service.access_token(connection))
    except (calendar_service.CalendarError, httpx.HTTPError):
        pass  # the channel expires by itself; the link is removed either way
    await calendar_service.revoke(connection)
    await db.execute(delete(CalendarEvent).where(CalendarEvent.user_id == user.id))
    await db.delete(connection)
    await db.commit()
    return {"ok": True}


@router.get("/events")
async def upcoming_events(
    days: int = 2, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """The person's upcoming meetings and what the notetaker will do in each,
    including when a colleague's calendar already covers the same meeting."""
    connection = await db.get(CalendarConnection, user.id)
    if connection is None:
        return []
    now = datetime.datetime.now(datetime.UTC)
    events = (
        await db.execute(
            select(CalendarEvent)
            .where(
                CalendarEvent.user_id == user.id,
                CalendarEvent.cancelled.is_(False),
                # A meeting running past its calendar end stays listed while
                # the notetaker is still in it.
                or_(
                    CalendarEvent.end_at > now,
                    CalendarEvent.capture_request_id.in_(
                        select(CaptureRequest.id).where(CaptureRequest.status.in_(CAPTURE_ACTIVE_STATUSES))
                    ),
                ),
                CalendarEvent.start_at < now + datetime.timedelta(days=max(1, min(days, 7))),
            )
            .order_by(CalendarEvent.start_at)
            .limit(50)
        )
    ).scalars().all()

    codes = [event.meeting_code for event in events if event.meeting_code]
    # Other colleagues set to record the same meeting (their calendars).
    covered: dict[str, int] = {}
    if codes:
        for code, count in (
            await db.execute(
                select(CalendarEvent.meeting_code, func.count(func.distinct(CalendarEvent.user_id)))
                .where(CalendarEvent.meeting_code.in_(codes), CalendarEvent.user_id != user.id, CalendarEvent.cancelled.is_(False))
                .group_by(CalendarEvent.meeting_code)
            )
        ).all():
            covered[code] = count

    out = []
    for event in events:
        capture = await db.get(CaptureRequest, event.capture_request_id) if event.capture_request_id else None
        out.append(
            {
                "id": str(event.id),
                "title": event.title,
                "start_at": event.start_at.isoformat(),
                "end_at": event.end_at.isoformat(),
                "meeting_url": event.meeting_url,
                "unsupported_platform": event.unsupported_platform,
                "is_organizer": event.is_organizer,
                "invitee_count": len(event.invitees or []),
                "record_override": event.record_override,
                "will_record": calendar_service.should_record(event, connection),
                "colleagues_on_it": covered.get(event.meeting_code or "", 0),
                "capture": capture_service.serialize(capture) if capture else None,
                # Only a written brief is shown; "empty" means there was nothing
                # earlier to brief from, which isn't worth a row of UI.
                "brief": event.brief if event.brief and event.brief.get("status") in {"ready", "failed"} else None,
            }
        )
    return out


@router.get("/schedule")
async def schedule(
    past_days: int = 14, future_days: int = 14, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """The person's own Google Calendar, past and upcoming, for the Meetings
    page — each event with what Charcha did about it and, once recorded, a
    link to the notes. Notes are matched by the notetaker visit, else by the
    same Meet link around the same time, and only when the person can read
    them."""
    connection = await db.get(CalendarConnection, user.id)
    if connection is None:
        return {"connection": None, "events": []}
    now = datetime.datetime.now(datetime.UTC)
    start = now - datetime.timedelta(days=max(0, min(past_days, 30)))
    end = now + datetime.timedelta(days=max(1, min(future_days, 7)))
    events = (
        await db.execute(
            select(CalendarEvent)
            .where(
                CalendarEvent.user_id == user.id, CalendarEvent.cancelled.is_(False),
                CalendarEvent.end_at > start, CalendarEvent.start_at < end,
            )
            .order_by(CalendarEvent.start_at)
            .limit(400)
        )
    ).scalars().all()

    captures = {
        c.id: c
        for c in (
            await db.execute(select(CaptureRequest).where(CaptureRequest.id.in_([e.capture_request_id for e in events if e.capture_request_id])))
        ).scalars().all()
    } if events else {}
    codes = {e.meeting_code for e in events if e.meeting_code}
    readable: dict[str, list[Meeting]] = {}
    if codes:
        for meeting in (
            await db.execute(
                select(Meeting).where(
                    Meeting.meeting_code.in_(codes), Meeting.deleted_at.is_(None),
                    Meeting.date > start - datetime.timedelta(hours=3), meeting_visibility_clause(user),
                )
            )
        ).scalars().all():
            readable.setdefault(meeting.meeting_code, []).append(meeting)
    by_capture_meeting = {}
    capture_meeting_ids = [c.meeting_id for c in captures.values() if c.meeting_id]
    if capture_meeting_ids:
        for meeting in (
            await db.execute(select(Meeting).where(Meeting.id.in_(capture_meeting_ids), Meeting.deleted_at.is_(None), meeting_visibility_clause(user)))
        ).scalars().all():
            by_capture_meeting[meeting.id] = meeting

    def notes_for(event: CalendarEvent) -> Meeting | None:
        capture = captures.get(event.capture_request_id) if event.capture_request_id else None
        if capture and capture.meeting_id in by_capture_meeting:
            return by_capture_meeting[capture.meeting_id]
        window = (event.start_at - datetime.timedelta(hours=1), event.end_at + datetime.timedelta(hours=3))
        for meeting in readable.get(event.meeting_code or "", []):
            if window[0] <= meeting.date <= window[1]:
                return meeting
        return None

    out = []
    for event in events:
        capture = captures.get(event.capture_request_id) if event.capture_request_id else None
        notes = notes_for(event)
        # Live while it's on, or while the notetaker is still in an overrunning call.
        if (capture and capture.status in CAPTURE_ACTIVE_STATUSES) or event.start_at <= now < event.end_at:
            when = "live"
        else:
            when = "past" if event.end_at <= now else "upcoming"
        names = [(item.get("name") or (item.get("email") or "").split("@")[0]) for item in (event.invitees or [])]
        out.append(
            {
                "id": str(event.id),
                "title": event.title,
                "start_at": event.start_at.isoformat(),
                "end_at": event.end_at.isoformat(),
                "when": when,
                "meeting_url": event.meeting_url,
                "platform": "Google Meet" if event.meeting_code else event.unsupported_platform,
                "unsupported_platform": event.unsupported_platform,
                "is_organizer": event.is_organizer,
                "organizer_email": event.organizer_email,
                "recurring": bool(event.recurring_event_id),
                "invitee_count": len(event.invitees or []),
                "invitee_names": [n for n in names if n][:6],
                "will_record": calendar_service.should_record(event, connection),
                "record_override": event.record_override,
                "capture": capture_service.serialize(capture) if capture else None,
                "notes": {"id": str(notes.id), "title": notes.title} if notes else None,
                "brief_ready": bool(event.brief and event.brief.get("status") == "ready"),
            }
        )
    return {"connection": _serialize_connection(connection), "events": out}


@router.patch("/events/{event_id}")
async def update_event(
    event_id: uuid.UUID, body: EventUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    event = await db.get(CalendarEvent, event_id)
    if event is None or event.user_id != user.id:
        raise HTTPException(status_code=404, detail="Event not found")
    await calendar_service.apply_override(db, event, body.record)
    # Switched on for a meeting that's already starting: queue it now.
    await calendar_service.dispatch_due(db)
    connection = await db.get(CalendarConnection, user.id)
    return {"id": str(event.id), "record_override": event.record_override, "will_record": calendar_service.should_record(event, connection)}
