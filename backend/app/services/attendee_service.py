"""Turning a list of names into the people allowed to read a meeting.

A meeting's attendees come from very different places — a picker in the web
app, calendar invitees, colleagues who asked for the notetaker, speaker names
scraped out of Google Meet captions, and the account that did the recording —
so they arrive as loose dictionaries. Everything here reduces that to:

* an internal attendee with **granted** access (invited, asked for the notes,
  or shared with by the organizer / an admin) — they can read the meeting;
* an internal attendee with **pending** access — the notetaker saw them in the
  call but they weren't on the invite; the organizer or an admin decides;
* an external guest, who has no account and never gains access.
"""

import datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Meeting, MeetingAttendee, Notification, User

MAX_ATTENDEES = 100


def _clean(value) -> str:
    return str(value).strip() if value is not None else ""


def normalize_input(raw: list) -> list[dict]:
    """Accept either bare strings (a name, or an email) or objects with
    user_id/name/email, and return uniform dicts. Order is preserved and
    duplicates are dropped on the first of name/email/user_id that repeats."""
    normalized: list[dict] = []
    seen: set[str] = set()
    for item in raw or []:
        if isinstance(item, str):
            text = _clean(item)
            if not text:
                continue
            entry = {"user_id": None, "name": text, "email": text if "@" in text else None}
        elif isinstance(item, dict):
            entry = {
                "user_id": _clean(item.get("user_id")) or None,
                "name": _clean(item.get("name")),
                "email": _clean(item.get("email")).lower() or None,
            }
            # Optional hints from trusted server-side callers (bot ingest).
            if item.get("access") in {"granted", "pending"}:
                entry["access"] = item["access"]
            if item.get("source"):
                entry["source"] = _clean(item["source"])
            if not entry["name"] and entry["email"]:
                entry["name"] = entry["email"]
            if not entry["name"] and not entry["user_id"]:
                continue
        else:
            continue
        key = (entry["user_id"] or entry["email"] or entry["name"]).lower()
        if key in seen:
            # A later duplicate can only strengthen access, never weaken it.
            if entry.get("access") == "granted":
                for earlier in normalized:
                    if (earlier["user_id"] or earlier["email"] or earlier["name"]).lower() == key:
                        earlier["access"] = "granted"
            continue
        seen.add(key)
        normalized.append(entry)
        if len(normalized) >= MAX_ATTENDEES:
            break
    return normalized


async def resolve(db: AsyncSession, raw: list) -> list[dict]:
    """Match each attendee to a Charcha account by id, then email, then an
    exact case-insensitive name match.

    Name matching is deliberately exact and deliberately skipped when the name
    is ambiguous: two active users called "Ravi" mean neither of them is
    granted access off a bare first name. Guessing here would hand someone a
    meeting they were never in, which is the exact failure this whole feature
    is meant to prevent.
    """
    entries = normalize_input(raw)
    if not entries:
        return []

    users = (
        await db.execute(select(User).where(User.status == "active"))
    ).scalars().all()
    by_id = {str(u.id): u for u in users}
    by_email = {u.email.lower(): u for u in users if u.email}
    by_name: dict[str, User | None] = {}
    for user in users:
        if not user.name or not user.name.strip():
            continue
        key = user.name.strip().lower()
        # None marks an ambiguous name — see the docstring.
        by_name[key] = None if key in by_name else user

    resolved: list[dict] = []
    for entry in entries:
        match = None
        if entry["user_id"]:
            match = by_id.get(entry["user_id"])
        if match is None and entry["email"]:
            match = by_email.get(entry["email"])
        if match is None and entry["name"]:
            match = by_name.get(entry["name"].strip().lower())
        resolved.append(
            {
                "user_id": str(match.id) if match else None,
                "name": (match.name or match.email) if match else entry["name"],
                "email": (match.email if match else entry["email"]),
                "kind": "internal" if match else "external",
                **{key: entry[key] for key in ("access", "source") if key in entry},
            }
        )
    return resolved


async def apply_to_meeting(
    db: AsyncSession,
    meeting_id: uuid.UUID,
    attendees: list[dict],
    owner_user_id: uuid.UUID | None = None,
    source: str = "manual",
    replace: bool = True,
) -> tuple[list[dict], list[uuid.UUID]]:
    """Write `attendees` onto the meeting.

    Returns the stored attendees and the ids of the colleagues who gained
    access in this call — the caller uses the second value to tell them, since
    being added to a meeting is the moment its transcript becomes readable to
    them and nothing else would surface that.

    The owner is always included: whoever recorded a meeting can always read it
    (that is also enforced independently in `meeting_visibility_clause`, so a
    missing row here can never lock them out).
    """
    existing = (
        await db.execute(
            select(MeetingAttendee).where(MeetingAttendee.meeting_id == meeting_id)
        )
    ).scalars().all()

    # Everyone who could already read the meeting before this call, so the
    # notification below goes only to people for whom access is actually new.
    # Taken before a replace deletes the rows, or everyone counts as new.
    previously_internal = {row.user_id for row in existing if row.user_id and row.access == "granted"}

    if replace:
        for row in existing:
            await db.delete(row)
        await db.flush()
        existing = []

    already_internal = {row.user_id for row in existing if row.user_id}
    already_external = {(row.display_name or "").lower() for row in existing if not row.user_id}

    rows: list[MeetingAttendee] = list(existing)
    if owner_user_id is not None and owner_user_id not in already_internal:
        owner = await db.get(User, owner_user_id)
        rows.append(
            MeetingAttendee(
                meeting_id=meeting_id,
                user_id=owner_user_id,
                display_name=(owner.name or owner.email) if owner else "Recorder",
                email=owner.email if owner else None,
                kind="internal",
                source="recorder",
            )
        )
        already_internal.add(owner_user_id)

    by_user = {row.user_id: row for row in rows if row.user_id}
    for entry in attendees:
        if entry.get("user_id"):
            user_id = uuid.UUID(entry["user_id"])
            access = entry.get("access") or "granted"
            if user_id in already_internal:
                # Seen twice (e.g. present in the call *and* invited): the
                # stronger claim wins, and a pending row is never downgraded to.
                row = by_user.get(user_id)
                if row is not None and access == "granted" and row.access != "granted":
                    row.access = "granted"
                    row.source = entry.get("source") or source
                continue
            already_internal.add(user_id)
            row = MeetingAttendee(
                meeting_id=meeting_id,
                user_id=user_id,
                display_name=entry.get("name") or entry.get("email") or "Unknown",
                email=entry.get("email"),
                kind="internal",
                source=entry.get("source") or source,
                access=access,
            )
            by_user[user_id] = row
            rows.append(row)
        else:
            name = (entry.get("name") or "").strip()
            if not name or name.lower() in already_external:
                continue
            already_external.add(name.lower())
            rows.append(
                MeetingAttendee(
                    meeting_id=meeting_id,
                    user_id=None,
                    display_name=name,
                    email=entry.get("email"),
                    kind="external",
                    source=entry.get("source") or source,
                )
            )

    for row in rows:
        if row not in existing:
            db.add(row)
    await db.flush()

    added = [
        row.user_id
        for row in rows
        if row.user_id
        and row.access == "granted"
        and row.user_id not in previously_internal
        and row.user_id != owner_user_id
    ]
    return [serialize(row) for row in rows], added


async def notify_new_attendees(
    db: AsyncSession, meeting_id: uuid.UUID, user_ids: list[uuid.UUID], meeting_title: str | None = None
) -> None:
    """Tell people they were added to a meeting. Best-effort: a failure here
    must never roll back the attendee change itself, which is the part that
    actually matters."""
    if not user_ids:
        return
    if meeting_title is None:
        meeting = await db.get(Meeting, meeting_id)
        meeting_title = meeting.title if meeting else "a meeting"
    for user_id in user_ids:
        db.add(
            Notification(
                user_id=user_id,
                type="meeting_access",
                message=f'You were added to "{meeting_title}" and can now read it.',
                link=f"/meetings/{meeting_id}",
            )
        )


def serialize(row: MeetingAttendee) -> dict:
    return {
        "id": str(row.id),
        "user_id": str(row.user_id) if row.user_id else None,
        "name": row.display_name,
        "email": row.email,
        "kind": row.kind,
        "source": row.source,
        # Externals never have access; internal rows say whether they do yet.
        "access": row.access if row.user_id else "none",
    }


async def list_for_meeting(db: AsyncSession, meeting_id: uuid.UUID) -> list[dict]:
    rows = (
        await db.execute(
            select(MeetingAttendee)
            .where(MeetingAttendee.meeting_id == meeting_id)
            .order_by(MeetingAttendee.kind, MeetingAttendee.display_name)
        )
    ).scalars().all()
    return [serialize(row) for row in rows]


async def set_access(
    db: AsyncSession, meeting: Meeting, attendee_id: uuid.UUID, access: str
) -> MeetingAttendee | None:
    """Grant (or take back) an internal attendee's access. The recorder can
    never be locked out of their own meeting."""
    row = await db.get(MeetingAttendee, attendee_id)
    if row is None or row.meeting_id != meeting.id or row.user_id is None:
        return None
    if access != "granted" and row.user_id == meeting.user_id:
        raise ValueError("The person who recorded this meeting always keeps access")
    if row.access != access:
        row.access = access
        if access == "granted":
            row.shared_at = _now()
            await notify_new_attendees(db, meeting.id, [row.user_id], meeting.title)
    await db.flush()
    return row


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


async def mark_shared(db: AsyncSession, meeting_id: uuid.UUID, user_ids: list[uuid.UUID]) -> None:
    """People the attendee editor just gave access to: a deliberate share."""
    if not user_ids:
        return
    rows = (
        await db.execute(
            select(MeetingAttendee).where(MeetingAttendee.meeting_id == meeting_id, MeetingAttendee.user_id.in_(user_ids))
        )
    ).scalars().all()
    for row in rows:
        if row.access == "granted" and row.shared_at is None:
            row.shared_at = _now()
    await db.flush()


async def share_with_user(db: AsyncSession, meeting: Meeting, user: User) -> MeetingAttendee:
    """Give a colleague access who wasn't picked up as an attendee at all."""
    row = (
        await db.execute(
            select(MeetingAttendee).where(MeetingAttendee.meeting_id == meeting.id, MeetingAttendee.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        row = MeetingAttendee(
            meeting_id=meeting.id,
            user_id=user.id,
            display_name=user.name or user.email,
            email=user.email,
            kind="internal",
            source="shared",
            access="granted",
            shared_at=_now(),
        )
        db.add(row)
        await notify_new_attendees(db, meeting.id, [user.id], meeting.title)
    elif row.access != "granted":
        row.access, row.shared_at = "granted", _now()
        await notify_new_attendees(db, meeting.id, [user.id], meeting.title)
    elif row.shared_at is None:
        # Already in it from the calendar invite: sharing it anyway is what
        # lets someone outside the company get its emails.
        row.shared_at = _now()
    await db.flush()
    return row


async def notify_pending(db: AsyncSession, meeting: Meeting, manager_ids: list[uuid.UUID]) -> None:
    """Tell the people who can share a meeting that colleagues were in the
    call without being on the invite, so nobody is left out silently."""
    pending = (
        await db.execute(
            select(MeetingAttendee).where(
                MeetingAttendee.meeting_id == meeting.id,
                MeetingAttendee.user_id.isnot(None),
                MeetingAttendee.access == "pending",
            )
        )
    ).scalars().all()
    if not pending:
        return
    names = ", ".join(row.display_name for row in pending[:3]) + (f" and {len(pending) - 3} more" if len(pending) > 3 else "")
    for manager_id in dict.fromkeys(manager_ids):
        db.add(
            Notification(
                user_id=manager_id,
                type="meeting_access_pending",
                message=f'{names} joined "{meeting.title}" without being on the invite. Share the notes with them?',
                link=f"/meetings/{meeting.id}#people",
            )
        )


async def link_new_account(db: AsyncSession, user: User) -> set[uuid.UUID]:
    """A colleague who signs up after being invited to meetings: their invite
    rows were stored as external guests (no account yet), so they couldn't
    open those meetings. Link the invites carrying their email when it is on
    the recorder's own domain — a client who later gets an account stays
    external. Returns the meetings that changed."""
    email = (user.email or "").strip().lower()
    domain = email.rpartition("@")[2]
    if not domain:
        return set()
    recorder = User.__table__.alias("recorder")
    rows = (await db.execute(
        select(MeetingAttendee, recorder.c.email)
        .join(Meeting, Meeting.id == MeetingAttendee.meeting_id)
        .join(recorder, recorder.c.id == Meeting.user_id)
        .where(MeetingAttendee.user_id.is_(None), func.lower(MeetingAttendee.email) == email)
    )).all()
    changed: set[uuid.UUID] = set()
    for row, recorder_email in rows:
        if (recorder_email or "").lower().rpartition("@")[2] != domain:
            continue
        existing = (await db.execute(
            select(MeetingAttendee).where(MeetingAttendee.meeting_id == row.meeting_id, MeetingAttendee.user_id == user.id)
        )).scalar_one_or_none()
        if existing is not None:
            if row.access == "granted":
                existing.access = "granted"
            await db.delete(row)
        else:
            row.user_id, row.kind = user.id, "internal"
            if row.display_name.strip().lower() == email and user.name:
                row.display_name = user.name
        changed.add(row.meeting_id)
    if changed:
        await db.flush()
        await relink_task_owners(db, changed)
    return changed


async def relink_task_owners(db: AsyncSession, meeting_ids: set[uuid.UUID] | None = None) -> int:
    """Tasks whose stated owner had no account when they were written get
    one once the name resolves. A task that has an owner account is never
    changed."""
    from app.database.models import MeetingTask
    from app.services.insight_service import resolve_owner_user_id

    query = select(MeetingTask).where(MeetingTask.owner_user_id.is_(None), MeetingTask.owner.isnot(None))
    if meeting_ids is not None:
        query = query.where(MeetingTask.meeting_id.in_(meeting_ids))
    linked = 0
    for task in (await db.execute(query)).scalars().all():
        owner_id = await resolve_owner_user_id(db, task.meeting_id, task.owner)
        if owner_id is not None:
            task.owner_user_id, linked = owner_id, linked + 1
    return linked
