"""Capture requests: sending the notetaker bot into a live meeting by URL.

The capture provider is this repo's own notetaker (backend/bot). It joins
Google Meet and Microsoft Teams; Zoom and Webex links are recognised and
refused with an honest reason rather than accepted and left to fail.

Status moves only on evidence the bot reports. Events are deduplicated by the
bot's event id, and a late or out-of-order event can never move a request
backwards or out of a final state.
"""

import datetime
import hashlib
import re
import time
import uuid
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, unquote, urlsplit

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import CAPTURE_ACTIVE_STATUSES, CaptureRequest, CaptureSubscriber, ServiceHeartbeat, User

MEET_URL_RE = re.compile(
    r"^(?:https?://)?meet\.google\.com/(?:meet/)?([a-z]{3}-[a-z]{4}-[a-z]{3})(?:[/?#].*)?$", re.IGNORECASE
)
TEAMS_HOSTS = {"teams.microsoft.com", "teams.live.com", "teams.cloud.microsoft"}
TEAMS_MEET_PATH_RE = re.compile(r"^/meet/(\d{6,20})/?$")
TEAMS_JOIN_PATH_RE = re.compile(r"^/l/meetup-join/([^/]+)/([^/]+)/?$")
TEAMS_THREAD_RE = re.compile(r"^19:[\w.=-]+@thread\.[a-z0-9.]+$", re.IGNORECASE)
UNSUPPORTED_PLATFORMS = {
    "zoom.us": "Zoom",
    "webex.com": "Webex",
}

# Forward-only order for in-progress states.
PROGRESS_RANK = {"requested": 0, "joining": 1, "waiting_for_admission": 2, "capturing": 3}
FINAL_STATUSES = {"stopped", "completed", "denied", "timed_out", "failed", "cancelled"}
ALL_STATUSES = set(PROGRESS_RANK) | FINAL_STATUSES
STATUS_LABELS = {
    "requested": "Waiting for the notetaker to pick it up",
    "joining": "Notetaker is opening the meeting",
    "waiting_for_admission": "Waiting for the host to admit the notetaker",
    "capturing": "Recording",
    "stopped": "Left the meeting — processing the recording",
    "completed": "Done",
    "denied": "The host did not admit the notetaker",
    "timed_out": "Timed out",
    "failed": "Failed",
    "cancelled": "Cancelled",
}


class InvalidMeetingUrl(ValueError):
    pass


def _normalize_teams_url(value: str) -> tuple[str, str] | None:
    """(meeting code, canonical URL) for a Teams join link, else None.

    The canonical URL is rebuilt from the validated parts, on a known host, so
    the notetaker's browser can only be sent to Teams. It keeps the passcode
    (`p`) or tenant (`context`): the meeting can't be joined without them. They
    stay out of the code, which identifies the meeting and is shown in places
    the passcode shouldn't be.
    """
    try:
        parts = urlsplit(value if "://" in value else f"https://{value}")
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"}:
        return None
    # Outlook rewrites links in mail through Safe Links.
    if host.endswith(".safelinks.protection.outlook.com"):
        inner = parse_qs(parts.query).get("url")
        return _normalize_teams_url(inner[0]) if inner else None
    if host not in TEAMS_HOSTS:
        return None

    path, query = parts.path, parts.query
    # The same link, wrapped by the launcher page or the web client's router.
    target = parse_qs(query).get("url", [""])[0] if path.endswith("/launcher.html") else parts.fragment
    if target.startswith("/"):
        path, _, query = target.removeprefix("/_#").partition("?")
    params = parse_qs(query)

    match = TEAMS_MEET_PATH_RE.match(path)
    if match:
        meeting_id = match.group(1)
        passcode = params.get("p", [""])[0]
        suffix = f"?p={quote(passcode, safe='')}" if passcode else ""
        return f"teams-{meeting_id}", f"https://{host}/meet/{meeting_id}{suffix}"

    match = TEAMS_JOIN_PATH_RE.match(path)
    if match:
        thread, message = unquote(match.group(1)), unquote(match.group(2))
        if not TEAMS_THREAD_RE.match(thread) or not message.isdigit():
            return None
        context = params.get("context", [""])[0]
        suffix = f"?context={quote(context, safe='')}" if context else ""
        # Thread ids are long and case-sensitive. A recurring series reuses
        # one, so its occurrences share a code just as a Meet room's do.
        digest = hashlib.sha256(f"{thread}/{message}".encode()).hexdigest()[:20]
        return f"teams-{digest}", f"https://{host}/l/meetup-join/{quote(thread, safe='')}/{message}{suffix}"
    return None


def normalize_meeting_url(raw: str) -> tuple[str, str, str]:
    """(platform, meeting code, canonical URL) or InvalidMeetingUrl."""
    value = (raw or "").strip()
    match = MEET_URL_RE.match(value)
    if match:
        code = match.group(1).lower()
        return "google_meet", code, f"https://meet.google.com/{code}"
    teams = _normalize_teams_url(value)
    if teams:
        return "microsoft_teams", teams[0], teams[1]
    lowered = value.lower()
    if any(host in lowered for host in TEAMS_HOSTS):
        raise InvalidMeetingUrl("That Teams link isn't a meeting link. Copy the whole join link from the invite.")
    for host, name in UNSUPPORTED_PLATFORMS.items():
        if host in lowered:
            raise InvalidMeetingUrl(
                f"{name} meetings aren't supported yet — the notetaker can only join Google Meet and Microsoft Teams. "
                "Upload the recording afterwards instead."
            )
    raise InvalidMeetingUrl("Paste a Google Meet or Microsoft Teams meeting link")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


async def notetaker_online(db: AsyncSession) -> bool:
    beat = await db.get(ServiceHeartbeat, "notetaker")
    if beat is None:
        return False
    return _now() - beat.last_seen_at < datetime.timedelta(seconds=settings.notetaker_offline_after_seconds)


# Read endpoints polled by every open tab only sweep this often; writes (a
# new request, the notetaker's claim) always sweep.
EXPIRY_SWEEP_SECONDS = 30
# A visit that left the call has this long for its recording to be ingested.
STOPPED_TIMEOUT = datetime.timedelta(minutes=30)
_last_sweep = 0.0


async def expire_unclaimed(db: AsyncSession, *, throttle: bool = False) -> None:
    """Time out requests nobody will pick up, instead of leaving them in
    "requested" forever (and blocking that meeting code).

    A request waiting only because every notetaker is busy in another call is
    *not* stale — it joins as soon as one frees up — so while the notetaker is
    checking in, requests get the longer queue window; when it is offline they
    time out after the short claim window.

    With throttle=True (status reads) it runs at most every
    EXPIRY_SWEEP_SECONDS per process: the timeouts are measured in minutes,
    and the UPDATE was most of the cost of the polled status endpoints.
    """
    global _last_sweep
    if throttle and time.monotonic() - _last_sweep < EXPIRY_SWEEP_SECONDS:
        return
    _last_sweep = time.monotonic()
    # Left the call but the recording never arrived (upload lost, rejected,
    # or the notetaker restarted mid-upload): close it with a reason.
    await db.execute(
        update(CaptureRequest)
        .where(CaptureRequest.status == "stopped", CaptureRequest.updated_at < _now() - STOPPED_TIMEOUT)
        .values(
            status="failed",
            status_detail="The notetaker left, but its recording never reached Charcha, so there are no notes.",
            updated_at=_now(),
        )
    )
    online = await notetaker_online(db)
    minutes = settings.capture_queue_timeout_minutes if online else settings.capture_claim_timeout_minutes
    cutoff = _now() - datetime.timedelta(minutes=minutes)
    detail = (
        f"Every notetaker stayed busy in other meetings for {minutes} minutes, so this one was skipped."
        if online
        else f"No notetaker picked this up within {minutes} minutes. The notetaker service may be offline."
    )
    await db.execute(
        update(CaptureRequest)
        .where(
            CaptureRequest.status == "requested",
            # Calendar requests are created just before the start time; they
            # count from when the meeting begins, not from when they were queued.
            func.coalesce(CaptureRequest.scheduled_start, CaptureRequest.created_at) < cutoff,
        )
        .values(status="timed_out", status_detail=detail, updated_at=_now())
    )


def can_transition(current: str, new: str) -> bool:
    if new not in ALL_STATUSES or current == new:
        return False
    if current in FINAL_STATUSES:
        # The only move out of a final state: the recording of a meeting the
        # bot left was ingested.
        return current == "stopped" and new in {"completed", "failed"}
    if new in FINAL_STATUSES:
        return True
    return PROGRESS_RANK[new] > PROGRESS_RANK[current]


def serialize(request: CaptureRequest) -> dict:
    return {
        "id": str(request.id),
        "platform": request.platform,
        "meeting_url": request.meeting_url,
        "meeting_code": request.meeting_code,
        "title": request.title,
        "template": request.template,
        "status": request.status,
        "status_label": STATUS_LABELS.get(request.status, request.status),
        "status_detail": request.status_detail,
        "active": request.status in CAPTURE_ACTIVE_STATUSES,
        "stop_requested": request.stop_requested_at is not None,
        "meeting_id": str(request.meeting_id) if request.meeting_id else None,
        "created_at": request.created_at.isoformat() if request.created_at else None,
        "updated_at": request.updated_at.isoformat() if request.updated_at else None,
    }


async def active_for_code(db: AsyncSession, code: str) -> CaptureRequest | None:
    return (
        await db.execute(
            select(CaptureRequest).where(
                CaptureRequest.meeting_code == code, CaptureRequest.status.in_(CAPTURE_ACTIVE_STATUSES)
            )
        )
    ).scalar_one_or_none()


@dataclass
class CaptureOutcome:
    capture: CaptureRequest
    # True when this call attached the user to a notetaker visit that already
    # existed for this meeting — someone else asked first, nothing new joins.
    joined_existing: bool
    # True when this user was already subscribed (a retry or double click).
    already_subscribed: bool


async def subscribe(db: AsyncSession, capture: CaptureRequest, user_id: uuid.UUID, source: str) -> bool:
    """Add (or re-activate) a subscriber. Returns True if they were already
    actively subscribed."""
    existing = (
        await db.execute(
            select(CaptureSubscriber).where(
                CaptureSubscriber.capture_request_id == capture.id, CaptureSubscriber.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        was_active = existing.released_at is None
        existing.released_at = None
        return was_active
    await db.execute(
        pg_insert(CaptureSubscriber)
        .values(capture_request_id=capture.id, user_id=user_id, source=source)
        .on_conflict_do_nothing(constraint="uq_capture_subscriber")
    )
    return False


async def request_capture(
    db: AsyncSession,
    user: User,
    meeting_url: str,
    *,
    title: str = "",
    template: str = "general",
    source: str = "link",
    invitees: list[dict] | None = None,
    organizer_email: str | None = None,
    scheduled_start: datetime.datetime | None = None,
    scheduled_end: datetime.datetime | None = None,
    idempotency_key: str | None = None,
    series_key: str | None = None,
) -> CaptureOutcome:
    """The single way a notetaker visit is asked for — the web app, the
    extension, linked calendars and calendar invites all come through here.

    One meeting is recorded once. If a visit for this Meet code is already
    queued or in the call, the caller is added as a subscriber to it instead:
    they get the same notes, and no second bot, transcription or AI run is
    paid for. Raises InvalidMeetingUrl for links the notetaker can't join.
    """
    platform, code, url = normalize_meeting_url(meeting_url)
    # Read before the loop: losing the race below rolls back, which expires
    # every loaded row, and an expired attribute can't lazy-load under asyncio.
    user_id = user.id
    await expire_unclaimed(db)

    for _ in range(2):
        active = await active_for_code(db, code)
        if active is not None:
            already = await subscribe(db, active, user_id, source)
            # Calendar invitees from a later calendar are invitees too.
            if invitees:
                known = {(item.get("email") or "").lower() for item in active.invitees or []}
                extra = [item for item in invitees if (item.get("email") or "").lower() not in known]
                if extra:
                    active.invitees = [*(active.invitees or []), *extra]
            if title and not active.title:
                active.title = title[:200]
            if series_key and not active.series_key:
                active.series_key = series_key
            await db.commit()
            return CaptureOutcome(active, joined_existing=active.user_id != user_id, already_subscribed=already)

        capture = CaptureRequest(
            user_id=user_id,
            platform=platform,
            meeting_url=url,
            meeting_code=code,
            title=title.strip()[:200] or None,
            template=template,
            status="requested",
            idempotency_key=idempotency_key,
            consent_acknowledged_at=_now(),
            source=source,
            invitees=invitees or None,
            organizer_email=(organizer_email or "").lower() or None,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            series_key=series_key,
        )
        db.add(capture)
        try:
            await db.flush()
            await subscribe(db, capture, user_id, source)
            await db.commit()
            await db.refresh(capture)
            return CaptureOutcome(capture, joined_existing=False, already_subscribed=False)
        except IntegrityError:
            # Someone else's request for the same meeting won the race (the
            # partial unique index is the real guard) — join theirs instead.
            await db.rollback()
            # Callers keep using `user` (e.g. to describe the visit).
            await db.refresh(user)
    raise RuntimeError("Could not create or join a notetaker visit for this meeting")


async def release(db: AsyncSession, capture: CaptureRequest, user_id: uuid.UUID) -> bool:
    """A subscriber no longer needs the notetaker. Returns True when nobody
    is left holding it, i.e. the bot should actually leave (or never join)."""
    await db.execute(
        update(CaptureSubscriber)
        .where(
            CaptureSubscriber.capture_request_id == capture.id,
            CaptureSubscriber.user_id == user_id,
            CaptureSubscriber.released_at.is_(None),
        )
        .values(released_at=_now())
    )
    remaining = await db.scalar(
        select(func.count())
        .select_from(CaptureSubscriber)
        .where(CaptureSubscriber.capture_request_id == capture.id, CaptureSubscriber.released_at.is_(None))
    )
    return not remaining


async def subscriber_ids(db: AsyncSession, capture_id: uuid.UUID, *, include_released: bool = True) -> list[uuid.UUID]:
    query = select(CaptureSubscriber.user_id).where(CaptureSubscriber.capture_request_id == capture_id)
    if not include_released:
        query = query.where(CaptureSubscriber.released_at.is_(None))
    return list((await db.execute(query.order_by(CaptureSubscriber.created_at))).scalars().all())


async def queue_position(db: AsyncSession, capture: CaptureRequest) -> int:
    """How many requests are ahead of this one waiting for a free notetaker."""
    if capture.status != "requested":
        return 0
    return int(
        await db.scalar(
            select(func.count())
            .select_from(CaptureRequest)
            .where(CaptureRequest.status == "requested", CaptureRequest.created_at < capture.created_at)
        )
        or 0
    )


async def describe_many(db: AsyncSession, captures: list[CaptureRequest], user: User) -> list[dict]:
    """serialize() plus who asked, who's subscribed and queue position, for
    many visits in a constant number of queries (the polled list endpoints
    used to run three per row)."""
    if not captures:
        return []
    ids = [c.id for c in captures]
    subscribers: dict[uuid.UUID, list[uuid.UUID]] = {}
    for capture_id, user_id in (
        await db.execute(
            select(CaptureSubscriber.capture_request_id, CaptureSubscriber.user_id).where(
                CaptureSubscriber.capture_request_id.in_(ids), CaptureSubscriber.released_at.is_(None)
            )
        )
    ).all():
        subscribers.setdefault(capture_id, []).append(user_id)
    requester_ids = {c.user_id for c in captures if c.user_id != user.id}
    names = {
        u.id: (u.name or u.email)
        for u in ((await db.execute(select(User).where(User.id.in_(requester_ids)))).scalars().all() if requester_ids else [])
    }
    waiting = [c for c in captures if c.status == "requested"]
    queue: list[datetime.datetime] = []
    if waiting:
        queue = sorted(
            (await db.execute(select(CaptureRequest.created_at).where(CaptureRequest.status == "requested"))).scalars().all()
        )
    out = []
    for capture in captures:
        subs = subscribers.get(capture.id, [])
        data = serialize(capture)
        data.update(
            requested_by_you=capture.user_id == user.id,
            requested_by=names.get(capture.user_id),
            subscribed=user.id in subs,
            subscriber_count=len(subs),
            queue_position=sum(1 for created in queue if created < capture.created_at) if capture.status == "requested" else 0,
        )
        out.append(data)
    return out
