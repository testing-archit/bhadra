"""Transactional email through Brevo.

How it works:

* Anything that should email someone writes an `EmailOutbox` row in the
  same transaction as the event — directly (`enqueue`), or automatically for
  in-app notifications of the kinds in NOTIFICATION_KINDS (a SQLAlchemy
  after_flush hook), so a rolled-back action never emails anyone.
* `run_forever` (started from app.main; one process via a Postgres advisory
  lock) renders and sends queued rows. Rendering happens at send time from
  current data, and the person's current preferences decide whether it goes.
* Brevo's free plan allows 300 emails a day. Non-security email stops at
  `email_daily_limit - email_security_reserve`; password resets and invites
  always go. Anything held back is retried after midnight UTC.
* `dedupe_key` is unique: the same event never emails twice.
"""

import asyncio
import datetime
import hashlib
import logging
import secrets
import uuid
import zoneinfo

import httpx
import jwt
from sqlalchemy import event, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import settings
from app.database.db import async_session, engine
from app.database.models import EmailOutbox, Meeting, MeetingAttendee, Notification, PasswordResetToken, User

logger = logging.getLogger(__name__)

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
ADVISORY_LOCK_KEY = 7_311_204_119
LOOP_SECONDS = 15
BATCH = 20
MAX_ATTEMPTS = 5
LOCAL_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")
# Scheduled emails go out at this local time unless the person picked
# another (SEND_HOURS) in Settings → Email.
DAILY_HOUR = 9
SEND_HOURS = range(6, 12)
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DEFAULT_SCHEDULE = {"reminder_days": list(range(7)), "digest_day": 0, "hour": DAILY_HOUR}

# category -> (label, description, can be switched off)
CATEGORIES: dict[str, tuple[str, str, bool]] = {
    "security": ("Account and security", "Password resets, invitations, sign-in changes and calendar connection problems.", False),
    "briefs": ("Pre-meeting briefs", "Your brief, ~10 minutes before a meeting on your linked calendar.", True),
    "notes": ("Meeting notes ready", "When notes from a meeting you were in are ready, and recurring-meeting check-ins.", True),
    "tasks": ("Tasks assigned to you", "When a meeting or a colleague gives you a task.", True),
    "reminders": ("Due-date reminders", "A morning list of your tasks due today or overdue.", True),
    "sharing": ("Access and sharing", "When notes are shared with you, or someone asks for access.", True),
    "digest": ("Weekly digest", "Monday morning: last week's meetings and decisions, and what's on your plate.", True),
    "admin": ("Admin alerts", "Notetaker problems that need an admin (admins only).", True),
}
DEFAULT_PREFS = {key: True for key in CATEGORIES}

# kind -> (category, priority)
KINDS: dict[str, tuple[str, int]] = {
    "password_reset": ("security", 0),
    "password_reset_google": ("security", 0),
    "password_changed": ("security", 0),
    "invite": ("security", 0),
    "welcome": ("security", 1),
    "calendar_error": ("security", 1),
    "notetaker_signed_out": ("admin", 1),
    "pre_meeting_brief": ("briefs", 1),
    "notes_ready": ("notes", 2),
    "series_review": ("notes", 2),
    "tasks_assigned": ("tasks", 2),
    "task_assigned": ("tasks", 2),
    "meeting_access": ("sharing", 2),
    "meeting_access_pending": ("sharing", 2),
    "daily_reminders": ("reminders", 2),
    "weekly_digest": ("digest", 3),
}
# kind -> (label, description) for Settings → Email. password_reset_google
# is one setting with password_reset, so it isn't listed on its own.
KIND_INFO: dict[str, tuple[str, str]] = {
    "password_reset": ("Password reset", "When you ask to reset your password."),
    "password_changed": ("Password changed", "Confirms a password change."),
    "invite": ("Invitation", "When an admin invites you."),
    "welcome": ("Welcome", "Once, when your account is created."),
    "calendar_error": ("Calendar disconnected", "When your linked calendar stops syncing, at most once a day."),
    "notetaker_signed_out": ("Notetaker signed out", "When Meet turns the notetaker away, at most every 12 hours."),
    "pre_meeting_brief": ("Pre-meeting brief", "~10 minutes before each event on your linked calendar."),
    "notes_ready": ("Notes ready", "Once per meeting, when its notes are ready."),
    "series_review": ("Recurring-meeting check-in", "When tasks from last time sounded finished in a recurring meeting you recorded."),
    "tasks_assigned": ("Tasks from a meeting", "One per meeting that gives you tasks."),
    "task_assigned": ("Task assigned by a colleague", "Each time a colleague assigns you a task."),
    "daily_reminders": ("Due and overdue tasks", "Only on days you have something due or overdue."),
    "meeting_access": ("Notes shared with you", "When someone gives you access to a meeting."),
    "meeting_access_pending": ("Colleagues waiting for access", "When colleagues who weren't invited joined your meeting."),
    "weekly_digest": ("Weekly digest", "Last week's meetings and decisions, and what's on your plate."),
}
assert set(KIND_INFO) == set(KINDS) - {"password_reset_google"}, "every email kind needs a settings label"
# In-app notification types that also send an email. task_due_soon is left
# out on purpose: it's covered by the one morning reminder email instead.
NOTIFICATION_KINDS = {
    "calendar_error", "notetaker_signed_out", "pre_meeting_brief", "series_review", "tasks_assigned",
    "task_assigned", "meeting_access", "meeting_access_pending",
}


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def configured() -> bool:
    return bool(settings.brevo_api_key)


# ---------------------------------------------------------------- preferences

def prefs_for(user: User) -> dict[str, bool]:
    stored = user.email_prefs or {}
    return {key: bool(stored.get(key, DEFAULT_PREFS[key])) if CATEGORIES[key][2] else True for key in CATEGORIES}


def kind_prefs_for(user: User) -> dict[str, bool]:
    """Per-email switches inside each group. Security email is always on."""
    stored = (user.email_prefs or {}).get("kinds") or {}
    return {kind: bool(stored.get(kind, True)) if CATEGORIES[KINDS[kind][0]][2] else True for kind in KINDS}


def schedule_for(user: User) -> dict:
    stored = (user.email_prefs or {}).get("schedule") or {}
    days = stored.get("reminder_days", DEFAULT_SCHEDULE["reminder_days"])
    digest_day = stored.get("digest_day", DEFAULT_SCHEDULE["digest_day"])
    hour = stored.get("hour", DEFAULT_SCHEDULE["hour"])
    return {
        "reminder_days": sorted({d for d in days if isinstance(d, int) and 0 <= d <= 6}),
        "digest_day": digest_day if isinstance(digest_day, int) and 0 <= digest_day <= 6 else DEFAULT_SCHEDULE["digest_day"],
        "hour": hour if hour in SEND_HOURS else DAILY_HOUR,
    }


def wants(user: User, kind: str) -> bool:
    if kind == "password_reset_google":
        kind = "password_reset"
    category = KINDS[kind][0]
    return prefs_for(user)[category] and kind_prefs_for(user)[kind]


def unsubscribe_token(user_id: uuid.UUID, category: str) -> str:
    return jwt.encode({"sub": str(user_id), "cat": category, "purpose": "unsubscribe"}, settings.jwt_secret, algorithm="HS256")


def read_unsubscribe_token(token: str) -> tuple[uuid.UUID, str]:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    if payload.get("purpose") != "unsubscribe" or payload.get("cat") not in CATEGORIES:
        raise jwt.InvalidTokenError("not an unsubscribe token")
    return uuid.UUID(payload["sub"]), payload["cat"]


# ---------------------------------------------------------------- queueing

def _row(kind: str, user_id: uuid.UUID | None, payload: dict, dedupe_key: str | None, send_after: datetime.datetime | None) -> dict:
    _, priority = KINDS[kind]
    return dict(
        kind=kind, user_id=user_id, payload=payload, dedupe_key=dedupe_key, priority=priority,
        status="queued", send_after=send_after or _now(),
    )


async def enqueue(
    db: AsyncSession,
    kind: str,
    user_id: uuid.UUID | None,
    payload: dict | None = None,
    *,
    dedupe_key: str | None = None,
    send_after: datetime.datetime | None = None,
) -> None:
    """Queue an email in the caller's transaction. A dedupe_key that already
    exists is silently ignored."""
    await db.execute(
        pg_insert(EmailOutbox)
        .values(**_row(kind, user_id, payload or {}, dedupe_key, send_after))
        .on_conflict_do_nothing(constraint="uq_email_dedupe")
    )


def _notification_dedupe(note: Notification) -> str:
    day = _now().date().isoformat()
    if note.type in {"calendar_error", "notetaker_signed_out"}:
        return f"{note.type}:{note.user_id}:{day}"
    if note.type == "task_assigned":
        digest = hashlib.sha1((note.message or "").encode()).hexdigest()[:12]
        return f"{note.type}:{note.user_id}:{note.link}:{digest}"
    return f"{note.type}:{note.user_id}:{note.link}"


@event.listens_for(Session, "after_flush")
def _queue_notification_emails(session: Session, _flush_context) -> None:
    """Every in-app notification of an emailed kind queues its email in the
    same transaction (rolled back together)."""
    notes = [obj for obj in session.new if isinstance(obj, Notification) and obj.type in NOTIFICATION_KINDS]
    if not notes:
        return
    connection = session.connection()
    for note in notes:
        connection.execute(
            pg_insert(EmailOutbox)
            .values(**_row(note.type, note.user_id, {"message": note.message, "link": note.link}, _notification_dedupe(note), None))
            .on_conflict_do_nothing(constraint="uq_email_dedupe")
        )


# ---------------------------------------------------------------- password links

RESET_MINUTES = 60
INVITE_DAYS = 7


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_password_link(db: AsyncSession, user: User, purpose: str = "reset") -> str:
    """A new single-use link; earlier unused links of the same purpose stop
    working. Returns the raw token (only ever placed in the email)."""
    now = _now()
    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None), PasswordResetToken.purpose == purpose)
        .values(used_at=now)
    )
    token = secrets.token_urlsafe(32)
    lifetime = datetime.timedelta(days=INVITE_DAYS) if purpose == "invite" else datetime.timedelta(minutes=RESET_MINUTES)
    db.add(PasswordResetToken(user_id=user.id, token_hash=_hash(token), purpose=purpose, expires_at=now + lifetime))
    return token


async def redeem_password_link(db: AsyncSession, token: str) -> User | None:
    """The user the link belongs to, marking it used — or None when it is
    unknown, used or expired."""
    row = (
        await db.execute(select(PasswordResetToken).where(PasswordResetToken.token_hash == _hash(token)).with_for_update())
    ).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at < _now():
        return None
    user = await db.get(User, row.user_id)
    if user is None or user.status != "active":
        return None
    row.used_at = _now()
    # Any other outstanding link for this person dies with it.
    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=_now())
    )
    return user


# ---------------------------------------------------------------- sending

async def _sent_today(db: AsyncSession) -> int:
    """Recipients emailed today — the provider's daily limit counts each
    address, so a shared email with CCs counts once per person on it."""
    midnight = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    recipients = 1 + func.coalesce(func.jsonb_array_length(EmailOutbox.payload["sent_cc"]), 0)
    return await db.scalar(
        select(func.coalesce(func.sum(recipients), 0)).where(EmailOutbox.status == "sent", EmailOutbox.sent_at >= midnight)
    ) or 0


def _shared(row: EmailOutbox) -> bool:
    """One email for several people (To + CC), e.g. a meeting's notes."""
    return isinstance(row.payload, dict) and "cc" in row.payload


async def may_email_about_meeting(db: AsyncSession, user: User, meeting_id: uuid.UUID) -> bool:
    """Whether this person may be emailed about this meeting. Colleagues on
    INTERNAL_EMAIL_DOMAINS: yes, as their access allows. Anyone else only when
    they recorded it, asked for its notetaker themselves, or the recorder,
    organizer or an admin deliberately shared it with them in Wilco — a
    calendar invite or being heard in the call is not enough."""
    domains = settings.internal_email_domain_list
    if not domains or (user.email or "").strip().lower().rpartition("@")[2] in domains:
        return True
    if await db.scalar(select(Meeting.id).where(Meeting.id == meeting_id, Meeting.user_id == user.id)):
        return True
    return bool(
        await db.scalar(
            select(MeetingAttendee.id).where(
                MeetingAttendee.meeting_id == meeting_id,
                MeetingAttendee.user_id == user.id,
                MeetingAttendee.access == "granted",
                (MeetingAttendee.shared_at.isnot(None)) | (MeetingAttendee.source == "requested"),
            ).limit(1)
        )
    )


async def _recipients(db: AsyncSession, row: EmailOutbox) -> list[User]:
    """Everyone a shared email still goes to, To first: active, wanting this
    kind of email, and (for meeting emails) still able to open the meeting.
    If the To person dropped out, the next one takes their place."""
    from app.dependencies import user_can_read_meeting

    ids = [row.user_id, *[uuid.UUID(i) for i in row.payload.get("cc", [])]]
    meeting_id = row.payload.get("meeting_id")
    people: list[User] = []
    for user_id in dict.fromkeys(i for i in ids if i):
        user = await db.get(User, user_id)
        if user is None or user.status != "active" or not wants(user, row.kind):
            continue
        if (user.email or "").lower().endswith("@demo.wilco.invalid"):
            continue  # no-sign-up demo accounts have no mailbox
        if meeting_id and not (
            await user_can_read_meeting(db, user, uuid.UUID(meeting_id))
            and await may_email_about_meeting(db, user, uuid.UUID(meeting_id))
        ):
            continue
        people.append(user)
    return people


async def _post(to_email: str, to_name: str | None, rendered: dict, headers: dict, cc: list[User] | None = None) -> str:
    body = {
        "sender": {"name": settings.email_from_name, "email": settings.email_from},
        "replyTo": {"email": settings.email_reply_to, "name": "Bhadra"},
        "to": [{"email": to_email, **({"name": to_name} if to_name else {})}],
        **({"cc": [{"email": u.email, **({"name": u.name} if u.name else {})} for u in cc]} if cc else {}),
        "subject": rendered["subject"],
        "htmlContent": rendered["html"],
        "textContent": rendered["text"],
        "headers": headers,
        "tags": [rendered.get("tag", "charcha")],
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            BREVO_URL, json=body, headers={"api-key": settings.brevo_api_key, "accept": "application/json"}
        )
    if response.status_code >= 400:
        raise BrevoError(response.status_code, response.text[:300])
    return response.json().get("messageId", "")


class BrevoError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"Brevo {status}: {detail}")
        self.status = status


async def _deliverable_user(db: AsyncSession, row: EmailOutbox) -> User | None:
    """The recipient, or marks the row skipped (account gone or suspended,
    or the person switched this kind of email off). For a shared email: the
    first remaining recipient, skipped only when nobody is left."""
    if _shared(row):
        people = await _recipients(db, row)
        if not people:
            row.status, row.last_error = "skipped", "Nobody left to send it to"
            return None
        return people[0]
    user = await db.get(User, row.user_id) if row.user_id else None
    if row.user_id and (user is None or user.status != "active"):
        row.status, row.last_error = "skipped", "Account missing or suspended"
    elif user is not None and not wants(user, row.kind):
        row.status, row.last_error = "skipped", "Switched off in email preferences"
    return user


async def send_one(db: AsyncSession, row: EmailOutbox) -> None:
    """Render and send one queued row, recording the outcome on it."""
    from app.services import email_stories

    user = await _deliverable_user(db, row)
    if row.status == "skipped":
        return
    cc: list[User] = (await _recipients(db, row))[1:] if _shared(row) else []
    rendered = await email_stories.render(db, row, user)
    if rendered is None:
        row.status = "skipped"
        row.last_error = row.last_error or "Nothing to send"
        return
    to_email = rendered.get("to") or (user.email if user else None)
    row.to_email, row.subject = to_email, rendered["subject"]
    category = KINDS[row.kind][0]
    headers = {"X-Wilco-Kind": row.kind}
    # A shared email has no one-click unsubscribe: it would switch off the
    # To person's email, whoever clicked. Each reader manages their own.
    if user is not None and CATEGORIES[category][2] and not _shared(row):
        unsubscribe = f"{settings.public_api_url.rstrip('/') or 'https://charcha.example.com'}/api/email/unsubscribe?token={unsubscribe_token(user.id, category)}"
        headers["List-Unsubscribe"] = f"<{unsubscribe}>"
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    if not configured():
        row.status, row.last_error = "skipped", "BREVO_API_KEY is not set"
        return
    row.attempts += 1
    try:
        row.provider_message_id = await _post(to_email, user.name if user else None, rendered, headers, cc)
        row.status, row.sent_at, row.last_error = "sent", _now(), None
        if _shared(row):
            # Who it actually went to (and what counts against the daily limit).
            row.payload = {**row.payload, "sent_to": user.id and str(user.id), "sent_cc": [str(u.id) for u in cc]}
    except (BrevoError, httpx.HTTPError) as error:
        row.last_error = str(error)[:500]
        permanent = isinstance(error, BrevoError) and error.status in {400, 401, 403}
        if permanent or row.attempts >= MAX_ATTEMPTS:
            row.status = "failed"
        else:
            row.send_after = _now() + datetime.timedelta(minutes=2 ** row.attempts)


async def send_due(db: AsyncSession) -> int:
    """Send what's due, highest priority first, within today's quota."""
    sent_today = await _sent_today(db)
    rows = (
        await db.execute(
            select(EmailOutbox)
            .where(EmailOutbox.status == "queued", EmailOutbox.send_after <= _now())
            .order_by(EmailOutbox.priority, EmailOutbox.created_at)
            .limit(BATCH)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    count = 0
    tomorrow = (_now() + datetime.timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    for row in rows:
        cap = settings.email_daily_limit if row.priority == 0 else settings.email_daily_limit - settings.email_security_reserve
        # Something nobody will receive doesn't wait for quota.
        await _deliverable_user(db, row)
        if row.status == "skipped":
            await db.commit()
            continue
        if sent_today >= cap:
            row.send_after = tomorrow
            continue
        try:
            await send_one(db, row)
        except Exception as error:  # a broken template must not stop the queue
            logger.exception("Email %s (%s) could not be rendered", row.id, row.kind)
            row.status, row.last_error = "failed", f"{type(error).__name__}: {str(error)[:300]}"
        if row.status == "sent":
            # The daily limit counts every recipient, CCs included.
            sent_today += 1 + len((row.payload or {}).get("sent_cc") or [])
            count += 1
        await db.commit()
    await db.commit()
    return count


# ---------------------------------------------------------------- scheduled

async def schedule_daily(db: AsyncSession) -> int:
    """At each person's chosen local hour (DAILY_HOUR by default): the morning
    reminder on their chosen weekdays (only sent with tasks due today or
    overdue) and the weekly digest on their chosen day. Dedupe keys make this
    safe to run every loop tick; the digest's is per ISO week, so moving the
    day mid-week never sends a second one."""
    local = _now().astimezone(LOCAL_TZ)
    if local.hour not in SEND_HOURS:
        return 0
    day = local.date().isoformat()
    weekday = local.weekday()
    users = (await db.execute(select(User).where(User.status == "active"))).scalars().all()
    count = 0
    for user in users:
        schedule = schedule_for(user)
        if schedule["hour"] != local.hour:
            continue
        count += 1
        if weekday in schedule["reminder_days"] and wants(user, "daily_reminders"):
            await enqueue(db, "daily_reminders", user.id, {"date": day}, dedupe_key=f"daily_reminders:{user.id}:{day}")
        if weekday == schedule["digest_day"] and wants(user, "weekly_digest"):
            week = local.date().isocalendar()
            await enqueue(db, "weekly_digest", user.id, {"date": day}, dedupe_key=f"weekly_digest:{user.id}:{week.year}-W{week.week}")
    await db.commit()
    return count


async def run_once() -> None:
    async with engine.connect() as lock_conn:
        locked = await lock_conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": ADVISORY_LOCK_KEY})
        if not locked:
            await lock_conn.rollback()
            return
        try:
            async with async_session() as db:
                await schedule_daily(db)
                # Without a key, emails wait in the outbox instead of being dropped.
                if configured():
                    await send_due(db)
        finally:
            await lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_LOCK_KEY})
            await lock_conn.commit()


async def run_forever() -> None:
    if not configured():
        logger.info("Email is off: BREVO_API_KEY not set (emails stay queued in email_outbox)")
    while True:
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Email loop iteration failed; retrying")
        await asyncio.sleep(LOOP_SECONDS)
