"""Linked Google Calendars: the notetaker follows people to their meetings.

Each person links their own calendar once (OAuth, read-only events scope).
A background loop (`run_forever`, started from app.main) re-reads every
linked calendar on a short interval and, just before an event with a Google
Meet link starts, asks for the notetaker through
`capture_service.request_capture` — the same single queue the web app, the
extension and calendar invites use. So:

* a meeting on ten colleagues' calendars is still recorded once; all ten are
  subscribers and invitees, so all ten can read the notes;
* an external client's Meet on someone's company calendar is recorded too
  (the notetaker asks the external host to admit it);
* a declined, cancelled or switched-off event is never joined.
"""

import asyncio
import datetime
import logging
import re
import secrets
import urllib.parse
import uuid

import httpx
import jwt
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.db import async_session, engine
from app.database.models import CAPTURE_ACTIVE_STATUSES, CalendarConnection, CalendarEvent, CaptureRequest, Notification, User
from app.services import capture_service, secret_box, usage_ledger

logger = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
WATCH_URL = f"{EVENTS_URL}/watch"
STOP_URL = "https://www.googleapis.com/calendar/v3/channels/stop"
# Google allows event channels up to a week; renew a day before they lapse.
WATCH_TTL = datetime.timedelta(days=7)
WATCH_RENEW_BEFORE = datetime.timedelta(days=1)
SCOPES = ["openid", "email", "https://www.googleapis.com/auth/calendar.events.readonly"]

# Meet also opens rooms at meet.google.com/meet/<code>; always return the plain room URL.
MEET_LINK_RE = re.compile(r"https://meet\.google\.com/(?:meet/)?([a-z]{3}-[a-z]{4}-[a-z]{3})")


def _room_url(match: re.Match) -> str:
    return f"https://meet.google.com/{match.group(1)}"
UNSUPPORTED_LINKS = {"zoom.us/": "Zoom", "teams.microsoft.com/": "Microsoft Teams", "teams.live.com/": "Microsoft Teams", "webex.com/": "Webex"}
# How far ahead events are read and shown.
LOOKAHEAD = datetime.timedelta(days=7)
# Past events are kept (and re-read) this far back, for the calendar view
# on the Meetings page.
LOOKBEHIND = datetime.timedelta(days=30)
LOOP_SECONDS = 20
# Any value; only has to be the same for every API process.
ADVISORY_LOCK_KEY = 7_311_204_118
AUTO_JOIN_MODES = {"all", "organized", "manual"}
# A start time that shifts by less than this isn't treated as a move.
MOVE_TOLERANCE = datetime.timedelta(minutes=2)


class CalendarError(RuntimeError):
    pass


def configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def redirect_uri() -> str:
    base = settings.public_api_url.rstrip("/") or "http://localhost:8080"
    return f"{base}/api/calendar/callback"


def app_url(path: str) -> str:
    base = settings.public_app_url.rstrip("/") or (settings.allowed_origin_list[0] if settings.allowed_origin_list else "http://localhost:3000")
    return f"{base}{path}"


# ---------------------------------------------------------------- OAuth

def make_state(user_id: uuid.UUID) -> str:
    return jwt.encode(
        {"sub": str(user_id), "purpose": "calendar-link", "nonce": secrets.token_urlsafe(8), "exp": _now() + datetime.timedelta(minutes=15)},
        settings.jwt_secret,
        algorithm="HS256",
    )


def read_state(state: str) -> uuid.UUID:
    try:
        payload = jwt.decode(state, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as error:
        raise CalendarError("The calendar link expired. Try connecting again.") from error
    if payload.get("purpose") != "calendar-link":
        raise CalendarError("Invalid calendar link request")
    return uuid.UUID(payload["sub"])


def authorization_url(user_id: uuid.UUID, login_hint: str | None = None) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        # offline + consent: Google only returns a refresh token this way.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": make_state(user_id),
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_code(code: str) -> tuple[str, str]:
    """(refresh_token, google_email)."""
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
        if response.status_code != 200:
            raise CalendarError(f"Google refused the calendar link ({response.json().get('error', response.status_code)})")
        tokens = response.json()
        if "calendar.events.readonly" not in tokens.get("scope", ""):
            raise CalendarError("Calendar access wasn't granted. Tick the calendar box on Google's consent screen.")
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise CalendarError("Google didn't return long-lived access. Remove Charcha from your Google account's third-party access and connect again.")
        info = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
        email = info.json().get("email", "") if info.status_code == 200 else ""
    return refresh_token, email.lower()


async def access_token(connection: CalendarConnection) -> str:
    refresh_token = secret_box.decrypt(connection.refresh_token_encrypted)
    if not refresh_token:
        raise CalendarError("The stored calendar link can't be read any more. Reconnect your calendar.")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token",
            },
        )
    if response.status_code != 200:
        error = response.json().get("error", "") if response.headers.get("content-type", "").startswith("application/json") else ""
        if error in {"invalid_grant", "unauthorized_client"}:
            raise CalendarError("Google revoked Charcha's calendar access. Reconnect your calendar.")
        raise CalendarError(f"Couldn't refresh calendar access ({response.status_code})")
    return response.json()["access_token"]


async def revoke(connection: CalendarConnection) -> None:
    token = secret_box.decrypt(connection.refresh_token_encrypted)
    if not token:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(REVOKE_URL, data={"token": token})
    except httpx.HTTPError:
        logger.warning("Could not revoke a calendar token at Google; deleting it locally anyway")


# ---------------------------------------------------------------- push

def push_address() -> str | None:
    base = settings.public_api_url.rstrip("/")
    # Google only calls HTTPS addresses with a valid certificate.
    return f"{base}/api/calendar/push" if base.startswith("https://") else None


def watch_active(connection: CalendarConnection, now: datetime.datetime | None = None) -> bool:
    now = now or _now()
    return bool(connection.watch_channel_id and connection.watch_expires_at and connection.watch_expires_at > now)


async def stop_watch(connection: CalendarConnection, token: str) -> None:
    """Best effort: an unstopped channel just expires on its own."""
    if not (connection.watch_channel_id and connection.watch_resource_id):
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                STOP_URL,
                json={"id": connection.watch_channel_id, "resourceId": connection.watch_resource_id},
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError:
        logger.info("Could not stop calendar channel %s; it will expire", connection.watch_channel_id)
    connection.watch_channel_id = connection.watch_resource_id = connection.watch_token = None
    connection.watch_expires_at = None


async def ensure_watch(connection: CalendarConnection, token: str) -> None:
    """Keep a live push channel on this calendar, renewing it before it
    lapses. A refusal is recorded and the calendar falls back to polling
    every calendar_poll_seconds — never an error for the sync itself."""
    address = push_address()
    now = _now()
    if address is None or (watch_active(connection, now) and connection.watch_expires_at > now + WATCH_RENEW_BEFORE):
        return
    previous = (connection.watch_channel_id, connection.watch_resource_id)
    channel_id, channel_token = str(uuid.uuid4()), secrets.token_urlsafe(24)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                WATCH_URL,
                json={
                    "id": channel_id,
                    "type": "web_hook",
                    "address": address,
                    "token": channel_token,
                    "params": {"ttl": str(int(WATCH_TTL.total_seconds()))},
                },
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as error:
        connection.watch_error = f"Couldn't reach Google to set up live updates: {type(error).__name__}"
        return
    if response.status_code != 200:
        detail = ""
        if response.headers.get("content-type", "").startswith("application/json"):
            detail = ((response.json().get("error") or {}).get("message")) or ""
        connection.watch_error = f"Google refused live updates ({response.status_code}{': ' + detail if detail else ''}); polling every {settings.calendar_poll_seconds} s instead"
        logger.warning("Calendar watch refused for %s: %s", connection.google_email, connection.watch_error)
        return
    body = response.json()
    expires_ms = int(body.get("expiration") or 0)
    if previous[0] and previous[1]:
        # Replace, don't stack: the old channel would keep calling until it lapsed.
        old = CalendarConnection(watch_channel_id=previous[0], watch_resource_id=previous[1])
        await stop_watch(old, token)
    connection.watch_channel_id = channel_id
    connection.watch_resource_id = body.get("resourceId")
    connection.watch_token = channel_token
    connection.watch_expires_at = (
        datetime.datetime.fromtimestamp(expires_ms / 1000, tz=datetime.UTC) if expires_ms else now + WATCH_TTL
    )
    connection.watch_error = None


_wake = asyncio.Event()


async def handle_push(db: AsyncSession, channel_id: str, channel_token: str, state: str) -> bool:
    """Google says this calendar changed. Mark it for an immediate re-read
    and wake the loop. Returns whether the channel was ours."""
    connection = (
        await db.execute(select(CalendarConnection).where(CalendarConnection.watch_channel_id == channel_id))
    ).scalar_one_or_none()
    if connection is None or not connection.watch_token or not secrets.compare_digest(connection.watch_token, channel_token or ""):
        return False
    if state != "sync":  # "sync" is only the handshake when the channel opens
        connection.last_synced_at = None
        await db.commit()
        _wake.set()
    return True


# ---------------------------------------------------------------- events

def find_meet_link(event: dict) -> str | None:
    match = MEET_LINK_RE.match(event.get("hangoutLink") or "")
    if match:
        return _room_url(match)
    for entry in (event.get("conferenceData") or {}).get("entryPoints") or []:
        if entry.get("entryPointType") == "video":
            match = MEET_LINK_RE.match(entry.get("uri") or "")
            if match:
                return _room_url(match)
    for value in (event.get("location") or "", event.get("description") or ""):
        match = MEET_LINK_RE.search(value)
        if match:
            return _room_url(match)
    return None


def find_unsupported(event: dict) -> str | None:
    haystack = " ".join(
        [event.get("location") or "", event.get("description") or ""]
        + [entry.get("uri") or "" for entry in (event.get("conferenceData") or {}).get("entryPoints") or []]
    ).lower()
    for needle, name in UNSUPPORTED_LINKS.items():
        if needle in haystack:
            return name
    return None


def parse_event(event: dict, own_email: str) -> dict | None:
    """A storable dict, or None for events the notetaker must never join:
    cancelled, all-day, declined by this person, or with no video link at all."""
    if event.get("status") == "cancelled":
        return None
    start = (event.get("start") or {}).get("dateTime")
    end = (event.get("end") or {}).get("dateTime")
    if not start or not end:
        return None
    meet_url = find_meet_link(event)
    unsupported = None if meet_url else find_unsupported(event)
    if not meet_url and not unsupported:
        return None

    own_email = own_email.lower()
    invitees: list[dict] = []
    declined = False
    for attendee in event.get("attendees") or []:
        if attendee.get("resource"):  # meeting rooms
            continue
        email = (attendee.get("email") or "").lower()
        if email == settings.notetaker_email.lower():
            continue
        if attendee.get("self") or email == own_email:
            declined = attendee.get("responseStatus") == "declined"
        invitees.append({"email": email or None, "name": attendee.get("displayName") or ""})
    if declined:
        return None
    organizer = event.get("organizer") or {}
    organizer_email = (organizer.get("email") or "").lower() or None
    if own_email and not any(item["email"] == own_email for item in invitees):
        # Events you created alone have no attendee list; you're still in them.
        invitees.insert(0, {"email": own_email, "name": ""})

    return {
        "google_event_id": event["id"],
        "recurring_event_id": event.get("recurringEventId"),
        "title": (event.get("summary") or "").strip()[:300] or "Untitled meeting",
        "start_at": datetime.datetime.fromisoformat(start),
        "end_at": datetime.datetime.fromisoformat(end),
        "meeting_url": meet_url,
        "meeting_code": meet_url.rsplit("/", 1)[-1] if meet_url else None,
        "unsupported_platform": unsupported,
        "organizer_email": organizer_email,
        "is_organizer": bool(organizer.get("self")) or (organizer_email is not None and organizer_email == own_email),
        "invitees": invitees,
    }


async def fetch_events(token: str, time_min: datetime.datetime, time_max: datetime.datetime) -> list[dict]:
    events: list[dict] = []
    params = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "timeMin": time_min.isoformat(),
        "timeMax": time_max.isoformat(),
        "maxResults": "250",
        "conferenceDataVersion": "1",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        for _ in range(4):  # at most 1,000 events in the window
            response = await client.get(EVENTS_URL, params=params, headers={"Authorization": f"Bearer {token}"})
            if response.status_code == 401:
                raise CalendarError("Google rejected the calendar access token")
            if response.status_code != 200:
                raise CalendarError(f"Couldn't read the calendar ({response.status_code})")
            body = response.json()
            events.extend(body.get("items") or [])
            if not body.get("nextPageToken"):
                break
            params["pageToken"] = body["nextPageToken"]
    return events


def should_record(event: CalendarEvent, connection: CalendarConnection) -> bool:
    if event.cancelled or not event.meeting_code:
        return False
    if event.record_override is not None:
        return event.record_override
    if connection.auto_join == "all":
        return True
    if connection.auto_join == "organized":
        return event.is_organizer
    return False


async def sync_connection(db: AsyncSession, connection: CalendarConnection) -> int:
    """Re-read one person's calendar window and store what's on it. Returns
    the number of joinable events. Marks the connection as needing a
    reconnect (and tells the person once) when Google refuses."""
    now = _now()
    try:
        token = await access_token(connection)
        raw = await fetch_events(token, now - LOOKBEHIND, now + LOOKAHEAD)
        await ensure_watch(connection, token)
    except (CalendarError, httpx.HTTPError) as error:
        message = str(error) or "Couldn't reach Google Calendar"
        newly_broken = connection.status != "error"
        connection.last_error = message
        connection.last_synced_at = now
        if "Reconnect" in message:
            connection.status = "error"
            if newly_broken:
                db.add(Notification(user_id=connection.user_id, type="calendar_error", message=f"Charcha stopped following your calendar: {message}", link="/settings#calendar"))
        await db.commit()
        return 0

    parsed = {item["google_event_id"]: item for item in (parse_event(event, connection.google_email) for event in raw) if item}
    existing = {
        row.google_event_id: row
        for row in (await db.execute(select(CalendarEvent).where(CalendarEvent.user_id == connection.user_id))).scalars().all()
    }
    for event_id, item in parsed.items():
        row = existing.get(event_id)
        if row is None:
            db.add(CalendarEvent(user_id=connection.user_id, **item))
        else:
            old_start, old_end = row.start_at, row.end_at
            for key, value in item.items():
                setattr(row, key, value)
            row.cancelled = False
            if row.start_at != old_start or row.end_at != old_end:
                await _follow_move(db, row, old_start, now)
    # Gone from the calendar (cancelled, declined, deleted): never join it,
    # and give up this person's claim on a visit that hasn't started.
    for event_id, row in existing.items():
        if event_id in parsed or row.end_at < now - LOOKBEHIND:
            continue
        if row.start_at > now - LOOKBEHIND and not row.cancelled:
            row.cancelled = True
            await _release_if_queued(db, row)
    await db.execute(delete(CalendarEvent).where(CalendarEvent.user_id == connection.user_id, CalendarEvent.end_at < now - LOOKBEHIND))
    connection.status = "active"
    connection.last_error = None
    connection.last_synced_at = now
    await db.commit()
    return sum(1 for item in parsed.values() if item["meeting_code"])


async def _follow_move(db: AsyncSession, event: CalendarEvent, old_start: datetime.datetime, now: datetime.datetime) -> None:
    """The event was moved or resized after the notetaker was queued for it.

    * still queued — the visit follows the new times (the claim endpoint won't
      hand it out more than CLAIM_EARLY before its start);
    * notetaker already in the call — it keeps recording until the new end
      (the bot re-reads scheduled_end);
    * that visit already finished and the meeting moved into the future — it is
      queued again at the new time.
    A brief written for the old time is rewritten near the new one."""
    moved = abs((event.start_at - old_start).total_seconds()) > MOVE_TOLERANCE.total_seconds()
    if moved and event.brief_generated_at is not None and event.start_at > now + datetime.timedelta(
        minutes=settings.pre_meeting_brief_lead_minutes
    ):
        event.brief, event.brief_generated_at = None, None
    if event.capture_request_id is None:
        return
    capture = await db.get(CaptureRequest, event.capture_request_id)
    if capture is None:
        event.capture_request_id = None
        return
    if capture.status == "requested":
        capture.scheduled_start, capture.scheduled_end = event.start_at, event.end_at
    elif capture.status in CAPTURE_ACTIVE_STATUSES:
        capture.scheduled_end = event.end_at
    elif moved and event.start_at > now:
        event.capture_request_id = None


async def _release_if_queued(db: AsyncSession, event: CalendarEvent) -> None:
    """Drop this person's claim on a calendar-created visit that hasn't joined
    yet; it is cancelled outright when nobody else still wants it."""
    if event.capture_request_id is None:
        return
    capture = await db.get(CaptureRequest, event.capture_request_id)
    if capture is None or capture.status != "requested":
        return
    if await capture_service.release(db, capture, event.user_id):
        capture.status = "cancelled"
        capture.status_detail = "The meeting was removed from the calendar, or switched off"
    event.capture_request_id = None


async def dispatch_due(db: AsyncSession) -> int:
    """Queue the notetaker for every linked-calendar meeting starting now.
    Returns how many visits were requested or joined."""
    now = _now()
    lead = datetime.timedelta(seconds=settings.calendar_join_lead_seconds)
    rows = (
        await db.execute(
            select(CalendarEvent, CalendarConnection)
            .join(CalendarConnection, CalendarConnection.user_id == CalendarEvent.user_id)
            .where(
                CalendarConnection.status == "active",
                CalendarEvent.capture_request_id.is_(None),
                CalendarEvent.cancelled.is_(False),
                CalendarEvent.meeting_code.isnot(None),
                CalendarEvent.start_at <= now + lead,
                CalendarEvent.end_at > now,
            )
            .order_by(CalendarEvent.start_at)
        )
    ).all()
    # Plain values: request_capture may roll back after losing a race to a
    # colleague's identical request, which expires any loaded rows.
    due = [
        dict(
            event_id=event.id,
            user_id=event.user_id,
            meeting_url=event.meeting_url,
            title=event.title,
            invitees=event.invitees or [],
            organizer_email=event.organizer_email,
            start_at=event.start_at,
            end_at=event.end_at,
            series_key=f"gcal:{event.recurring_event_id}" if event.recurring_event_id else None,
            explicit=event.record_override is True,
        )
        for event, connection in rows
        if should_record(event, connection)
    ]
    count = 0
    for item in due:
        user = await db.get(User, item["user_id"])
        if user is None or user.status != "active":
            continue
        if not item["explicit"] and await _series_keeps_refusing(db, user, item):
            continue
        try:
            outcome = await capture_service.request_capture(
                db,
                user,
                item["meeting_url"],
                title=item["title"],
                source="calendar",
                invitees=item["invitees"],
                organizer_email=item["organizer_email"],
                scheduled_start=item["start_at"],
                scheduled_end=item["end_at"],
                series_key=item["series_key"],
                template="auto",
            )
        except capture_service.InvalidMeetingUrl:
            continue
        event = await db.get(CalendarEvent, item["event_id"])
        if event is not None:
            event.capture_request_id = outcome.capture.id
            await db.commit()
        count += 1
    return count


# A recurring meeting whose last this-many notetaker visits all waited in the
# lobby unadmitted is skipped (production, 2026-10: daily series knocking every
# morning, nobody ever letting it in). Turning an occurrence on, or a visit
# that gets in, resumes it.
REFUSED_VISITS_TO_SKIP = 3


async def _series_keeps_refusing(db: AsyncSession, user: User, item: dict) -> bool:
    from app.services import notetaker_monitor

    if not item["series_key"]:
        return False
    recent = (
        await db.execute(
            select(CaptureRequest)
            .where(
                CaptureRequest.series_key == item["series_key"],
                CaptureRequest.status.notin_(CAPTURE_ACTIVE_STATUSES),
            )
            .order_by(CaptureRequest.created_at.desc())
            .limit(REFUSED_VISITS_TO_SKIP)
        )
    ).scalars().all()
    if len(recent) < REFUSED_VISITS_TO_SKIP or any(
        notetaker_monitor.failure_reason(visit.status, visit.status_detail) != "not_admitted"
        or visit.status not in notetaker_monitor.FAILURE_STATUSES
        for visit in recent
    ):
        return False
    link = "/dashboard"
    message = (
        f"Charcha stopped sending the notetaker to “{item['title'] or 'a recurring meeting'}”: nobody admitted it "
        f"the last {REFUSED_VISITS_TO_SKIP} times. Turn the meeting on under Coming up to try again."
    )
    told = (
        await db.execute(
            select(Notification.id).where(
                Notification.user_id == user.id,
                Notification.type == "notetaker_skipped",
                Notification.message == message,
                Notification.created_at > recent[0].created_at,
            ).limit(1)
        )
    ).first()
    if not told:
        db.add(Notification(user_id=user.id, type="notetaker_skipped", message=message, link=link))
        await db.commit()
    return True


async def apply_override(db: AsyncSession, event: CalendarEvent, record: bool | None) -> None:
    """A person switched one meeting on or off (None = back to their rule)."""
    event.record_override = record
    connection = await db.get(CalendarConnection, event.user_id)
    if connection is not None and not should_record(event, connection):
        await _release_if_queued(db, event)
    await db.commit()


# ---------------------------------------------------------------- briefs

async def _invitee_people(db: AsyncSession, event: CalendarEvent) -> tuple[list[uuid.UUID], list[str]]:
    """(colleague account ids, external guest emails) on the invite, without
    the person themselves or the notetaker."""
    emails = {
        (item.get("email") or "").strip().lower()
        for item in event.invitees or []
    } - {"", settings.notetaker_email.lower()}
    if not emails:
        return [], []
    users = (
        await db.execute(select(User).where(func.lower(User.email).in_(emails), User.status == "active"))
    ).scalars().all()
    internal = {u.email.lower(): u.id for u in users}
    colleagues = [uid for email, uid in internal.items() if uid != event.user_id]
    own = {email for email, uid in internal.items() if uid == event.user_id}
    external = sorted(emails - set(internal) - own)
    return colleagues, external


async def write_brief(db: AsyncSession, event: CalendarEvent) -> dict:
    """Build and store this person's brief for one event. Never raises: a
    failure is stored (and not retried) so a broken model call can't bill the
    same brief every loop tick."""
    from app.services import prep_service

    user = await db.get(User, event.user_id)
    now = _now()
    if user is None or user.status != "active":
        event.brief, event.brief_generated_at = {"status": "empty"}, now
        return event.brief
    colleagues, external = await _invitee_people(db, event)
    series_key = f"gcal:{event.recurring_event_id}" if event.recurring_event_id else None
    ctx = await prep_service.gather(db, user, colleagues, external_emails=external, series_key=series_key)
    brief: dict = {"status": "empty", **prep_service.serialize(ctx), "text": None, "error": None}
    if not ctx.empty:
        # Billed to the person whose brief it is.
        usage_ledger.current.set(usage_ledger.Attribution(user_id=user.id))
        try:
            brief["text"] = await prep_service.write_brief(ctx, f"Meeting title: {event.title}", feature="pre_meeting_brief")
            brief["status"] = "ready"
        except Exception as error:
            logger.exception("Pre-meeting brief failed for calendar event %s", event.id)
            brief["status"], brief["error"] = "failed", str(error)[:200]
        finally:
            usage_ledger.current.set(usage_ledger.Attribution())
    event.brief, event.brief_generated_at = brief, now
    if brief["status"] == "ready":
        minutes = max(1, round((event.start_at - now).total_seconds() / 60))
        db.add(
            Notification(
                user_id=event.user_id,
                type="pre_meeting_brief",
                message=f'"{event.title}" starts in {minutes} min. Your brief is ready.',
                link=f"/dashboard?brief={event.id}",
            )
        )
    return brief


async def prepare_briefs(db: AsyncSession) -> int:
    """Write the brief for every linked-calendar meeting starting within the
    lead time — Meet, Teams or Webex alike, since a brief needs no notetaker."""
    if not settings.gemini_api_key:
        return 0
    now = _now()
    lead = datetime.timedelta(minutes=settings.pre_meeting_brief_lead_minutes)
    events = (
        await db.execute(
            select(CalendarEvent)
            .join(CalendarConnection, CalendarConnection.user_id == CalendarEvent.user_id)
            .where(
                CalendarConnection.status == "active",
                CalendarEvent.cancelled.is_(False),
                CalendarEvent.brief_generated_at.is_(None),
                CalendarEvent.start_at > now,
                CalendarEvent.start_at <= now + lead,
            )
            .order_by(CalendarEvent.start_at)
        )
    ).scalars().all()
    for event in events:
        await write_brief(db, event)
        await db.commit()
    return len(events)


# ---------------------------------------------------------------- loop

async def run_once() -> None:
    # One API process does the work even if several are running. The lock is
    # tied to a database connection, so it lives on its own connection that
    # stays checked out for the whole pass (the session below may switch
    # connections between commits).
    async with engine.connect() as lock_conn:
        locked = await lock_conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": ADVISORY_LOCK_KEY})
        if not locked:
            await lock_conn.rollback()
            return
        try:
            await _sync_and_dispatch()
        finally:
            await lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_LOCK_KEY})
            await lock_conn.commit()


async def _sync_and_dispatch() -> None:
    async with async_session() as db:
        now = _now()
        with_push = now - datetime.timedelta(seconds=settings.calendar_sync_interval_seconds)
        without_push = now - datetime.timedelta(seconds=settings.calendar_poll_seconds)
        live = CalendarConnection.watch_expires_at > now
        connections = (
            await db.execute(
                select(CalendarConnection).where(
                    # Never synced, or Google pushed a change (both NULL);
                    # otherwise the safety-net interval, much shorter when
                    # push isn't working for this calendar.
                    (CalendarConnection.last_synced_at.is_(None))
                    | (live & (CalendarConnection.last_synced_at < with_push))
                    | (~func.coalesce(live, False) & (CalendarConnection.last_synced_at < without_push)),
                    # A broken link is retried hourly, not every few minutes.
                    (CalendarConnection.status == "active")
                    | (CalendarConnection.last_synced_at < now - datetime.timedelta(hours=1)),
                )
            )
        ).scalars().all()
        for connection in connections:
            await sync_connection(db, connection)
        await dispatch_due(db)
        await prepare_briefs(db)


async def run_forever() -> None:
    if not configured():
        logger.info("Google Calendar linking is off: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set")
        return
    while True:
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Calendar loop iteration failed; retrying")
        # Sleep, unless Google pushes a change first.
        _wake.clear()
        try:
            await asyncio.wait_for(_wake.wait(), LOOP_SECONDS)
        except TimeoutError:
            pass
