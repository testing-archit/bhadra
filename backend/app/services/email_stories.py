"""What each Wilco email says. One renderer per kind; each returns
{"subject", "html", "text", "tag"} or None to skip (nothing worth sending,
or the moment has passed). Rendered at send time from current data, so an
email never shows a task that was finished in the meantime, and never shows a
meeting the reader can't open."""

import datetime
import re
import urllib.parse
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    CalendarEvent,
    Decision,
    EmailOutbox,
    Meeting,
    MeetingAttendee,
    MeetingInsight,
    MeetingTask,
    User,
)
from app.dependencies import meeting_visibility_clause, user_can_read_meeting
from app.services import email_service
from app.services.due_phrase import english_due_phrase
from app.services.email_templates import (
    app_url,
    avatar,
    bullet_list,
    callout,
    esc,
    heading,
    layout,
    markdown_lite,
    paragraph,
    small,
)

LOCAL = email_service.LOCAL_TZ
MAX_ITEMS = 8
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def first_name(user: User | None) -> str:
    name = (user.name or "").strip() if user else ""
    return name.split()[0] if name else "there"


def when(value: datetime.datetime | None, *, time: bool = True) -> str:
    if value is None:
        return ""
    local = value.astimezone(LOCAL)
    return local.strftime("%a %-d %b, %-I:%M %p") if time else local.strftime("%a %-d %b")


def _finish(user: User | None, kind: str, subject: str, title: str, body: str, *, preheader: str, cta=None, reason: str = "", tag: str | None = None, to: str | None = None, shared: bool = False) -> dict:
    category = email_service.KINDS[kind][0]
    switchable = email_service.CATEGORIES[category][2]
    unsubscribe = None
    # A shared (To + CC) email gets no one-click unsubscribe: it would switch
    # off the To person's email whoever clicked. "Manage" is per reader.
    if user is not None and switchable and not shared:
        unsubscribe = app_url(f"/unsubscribe?token={email_service.unsubscribe_token(user.id, category)}")
    html, text = layout(
        title=title, body=body, preheader=preheader, cta=cta, footer_reason=reason,
        unsubscribe_url=unsubscribe, manage_url=app_url("/settings#email") if user is not None else None,
    )
    return {"subject": subject, "html": html, "text": text, "tag": tag or kind, **({"to": to} if to else {})}


def _id_in(link: str | None, pattern: str = _UUID) -> uuid.UUID | None:
    match = re.search(pattern, link or "")
    return uuid.UUID(match.group(0)) if match else None


async def _people(db: AsyncSession, meeting_id: uuid.UUID) -> list[MeetingAttendee]:
    return list(
        (
            await db.execute(select(MeetingAttendee).where(MeetingAttendee.meeting_id == meeting_id).order_by(MeetingAttendee.created_at))
        ).scalars().all()
    )


def _avatars(people: list[MeetingAttendee], limit: int = 8) -> str:
    shown = "".join(avatar(p.display_name, p.email, 26) for p in people[:limit])
    more = small(f" +{len(people) - limit}") if len(people) > limit else ""
    return f'<p style="margin:0 0 16px;">{shown}{more}</p>' if shown else ""


def _mine_clause(user: User):
    """Tasks that are this person's: resolved to their account, or (older
    tasks) named by their full name, first name, email or email handle."""
    names = {user.email.lower(), user.email.split("@")[0].lower()}
    if user.name:
        names |= {user.name.strip().lower(), user.name.strip().split()[0].lower()}
    return or_(MeetingTask.owner_user_id == user.id, func.lower(func.trim(MeetingTask.owner)).in_(names))


def _task_line(task: MeetingTask, meeting_title: str | None = None) -> str:
    due = ""
    if task.due_date:
        due = f" · due {task.due_date.strftime('%a %-d %b')}"
    elif english_due_phrase(task.deadline):
        due = f" · {esc(english_due_phrase(task.deadline))}"
    where = f" · {esc(meeting_title)}" if meeting_title else ""
    return f"{esc(task.description)}{small(due + where) if (due or where) else ''}"


# ---------------------------------------------------------------- account & security

async def password_reset(db, row, user):
    link = app_url(f"/reset-password?token={urllib.parse.quote(row.payload['token'])}")
    body = (
        paragraph(f"Hi {esc(first_name(user))},")
        + paragraph("Someone asked to reset the password for your Wilco account. If it was you, choose a new one below.")
        + paragraph(f"This link works once and expires in {email_service.RESET_MINUTES} minutes.", muted=True)
        + callout(paragraph("Didn't ask for this? You can ignore this email — your password stays the same and nobody can use this link without access to your inbox.", size=14))
    )
    return _finish(user, "password_reset", "Reset your Wilco password", "Reset your password", body,
                   preheader="Choose a new password for Wilco. The link expires in an hour.", cta=("Choose a new password", link),
                   reason=f"Sent to {user.email} because a password reset was requested for this address.")


async def password_reset_google(db, row, user):
    token = (row.payload or {}).get("token")
    if token:
        # A Google account can add a password too (e.g. to sign in to the
        # Chrome extension with email + password).
        link = app_url(f"/reset-password?token={urllib.parse.quote(token)}")
        body = (
            paragraph(f"Hi {esc(first_name(user))},")
            + paragraph("You sign in to Wilco with Google, and you don't have a Wilco password yet. If you'd like one — "
                        "to sign in with your email and a password, for example in the Chrome extension — set it below. "
                        "Continue with Google keeps working either way.")
            + paragraph(f"This link works once and expires in {email_service.RESET_MINUTES} minutes.", muted=True)
            + callout(paragraph("Didn't ask for this? You can ignore this email — nothing changes and nobody can use this link without access to your inbox.", size=14))
        )
        return _finish(user, "password_reset_google", "Set a password for Wilco", "Set a Wilco password", body,
                       preheader="Add a password to your Google sign-in. The link expires in an hour.", cta=("Set a password", link),
                       reason=f"Sent to {user.email} because a password reset was requested for this address.")
    body = (
        paragraph(f"Hi {esc(first_name(user))},")
        + paragraph("Someone asked to reset the password for your Wilco account, but you sign in with Google — there's no Wilco password to reset.")
        + paragraph("Use <strong>Continue with Google</strong> on the sign-in page with this address. If you can't get into your Google account, Google's own recovery will help.")
        + paragraph("Didn't ask for this? You can safely ignore it.", muted=True)
    )
    return _finish(user, "password_reset_google", "You sign in to Wilco with Google", "No password to reset", body,
                   preheader="Your Wilco account uses Google sign-in.", cta=("Go to sign in", app_url("/login")),
                   reason=f"Sent to {user.email} because a password reset was requested for this address.")


async def password_changed(db, row, user):
    how = row.payload.get("how", "reset")
    at = when(datetime.datetime.fromisoformat(row.payload["at"])) if row.payload.get("at") else ""
    body = (
        paragraph(f"Hi {esc(first_name(user))},")
        + paragraph(f"The password for your Wilco account was {'reset with an emailed link' if how == 'reset' else 'changed from Settings'}{' on ' + esc(at) if at else ''}. Everywhere you were signed in has been signed out.")
        + callout(paragraph("<strong>Wasn't you?</strong> Reset your password now and tell your Wilco admin — someone may have access to your email.", size=14), tone="warning")
    )
    return _finish(user, "password_changed", "Your Wilco password was changed", "Your password was changed", body,
                   preheader="If this wasn't you, reset it now.", cta=("Reset it again", app_url("/forgot-password")),
                   reason="Security notices are always sent.")


async def invite(db, row, user):
    by = row.payload.get("invited_by") or "Your admin"
    link = app_url(f"/reset-password?token={urllib.parse.quote(row.payload['token'])}&invite=1")
    body = (
        paragraph(f"Hi {esc(first_name(user))},")
        + paragraph(f"{esc(by)} added you to <strong>Wilco</strong>, Bhadra's meeting memory. It joins your Google Meet calls, writes the notes, and keeps every decision and task searchable.")
        + paragraph("Set your password to get started — or skip it and use <strong>Continue with Google</strong> with this address.")
        + paragraph(f"The link works once and expires in {email_service.INVITE_DAYS} days.", muted=True)
    )
    return _finish(user, "invite", f"{by} invited you to Wilco", "You're invited to Wilco", body,
                   preheader="Set your password, or sign in with Google.", cta=("Set your password", link),
                   reason=f"Sent to {user.email} because an admin created a Wilco account for this address.")


async def welcome(db, row, user):
    tips = bullet_list([
        "<strong>Send the notetaker</strong> into a Google Meet or Teams call — paste the link on Home, or use the Chrome extension.",
        "<strong>Link Google Calendar</strong> in Settings and it joins your meetings by itself, with a brief before each one.",
        "<strong>Ask Wilco</strong> anything about past meetings — answers cite the meeting they came from.",
    ])
    body = (
        paragraph(f"Hi {esc(first_name(user))}, welcome to Wilco.")
        + paragraph("Wilco remembers your meetings so you don't have to. Three things to try first:")
        + tips
    )
    return _finish(user, "welcome", "Welcome to Wilco", "Welcome to Wilco", body,
                   preheader="Three things to try in your first week.", cta=("Open Wilco", app_url("/dashboard")),
                   reason=f"Sent to {user.email} because a Wilco account was created for this address.")


async def calendar_error(db, row, user):
    body = (
        paragraph(f"Hi {esc(first_name(user))},")
        + paragraph(esc(row.payload.get("message") or "Wilco can no longer read your Google Calendar."))
        + paragraph("Until you reconnect it, the notetaker won't join your calendar meetings by itself and you won't get pre-meeting briefs.", muted=True)
    )
    return _finish(user, "calendar_error", "Reconnect your Google Calendar to Wilco", "Your calendar stopped syncing", body,
                   preheader="The notetaker can't follow your calendar until you reconnect.", cta=("Reconnect calendar", app_url("/settings#calendar")),
                   reason="Sent because your linked calendar stopped syncing.")


async def notetaker_signed_out(db, row, user):
    steps = bullet_list([
        "Sign the notetaker account back in to Google and refresh its saved login (backend/bot/README.md, step 3).",
        "Or allow guests in the affected meetings' host controls.",
    ])
    body = (
        paragraph(f"Hi {esc(first_name(user))},")
        + paragraph("The Wilco notetaker is signed out of Google, so Google Meet is turning it away from meetings that only admit signed-in accounts. Those meetings aren't being recorded.")
        + heading("To fix it")
        + steps
    )
    return _finish(user, "notetaker_signed_out", "Action needed: the Wilco notetaker is signed out", "The notetaker is signed out", body,
                   preheader="Meetings that need a signed-in account aren't being recorded.", cta=("Open Admin → Notetaker", app_url("/admin?tab=notetaker")),
                   reason="Sent to Wilco admins.")


# ---------------------------------------------------------------- meetings

async def pre_meeting_brief(db, row, user):
    event_id = _id_in(row.payload.get("link"))
    event = await db.get(CalendarEvent, event_id) if event_id else None
    if event is None or event.cancelled or not event.brief or event.brief.get("status") != "ready":
        return None
    if event.start_at < email_service._now():
        row.last_error = "The meeting had already started"
        return None
    brief = event.brief
    tags = {m["tag"]: m["title"] for m in brief.get("meetings", [])}
    tasks = []
    for t in brief.get("open_tasks", [])[:MAX_ITEMS]:
        resolved = datetime.date.fromisoformat(t["due_date"]) if t.get("due_date") else None
        due = english_due_phrase(t.get("deadline"), resolved)
        tasks.append(f"{esc(t['description'])}{small(' · ' + esc(t.get('owner') or 'owner not stated') + (' · due ' + esc(due) if due else ''))}")
    sources = " · ".join(f"{esc(m['tag'])} {esc(m['title'])}" for m in brief.get("meetings", []))
    minutes = max(1, round((event.start_at - email_service._now()).total_seconds() / 60))
    body = (
        paragraph(f"<strong>{esc(event.title)}</strong> {small('· ' + esc(when(event.start_at)))}")
        + markdown_lite(brief.get("text") or "", tags)
        + (heading("Open tasks") + bullet_list(tasks) if tasks else "")
        + (paragraph(small("From " + sources)) if sources else "")
    )
    cta = ("Join the meeting", event.meeting_url) if event.meeting_url else ("Open in Wilco", app_url(f"/dashboard?brief={event.id}"))
    return _finish(user, "pre_meeting_brief", f"Brief: {event.title} starts in {minutes} min", "Your pre-meeting brief", body,
                   preheader=f"{event.title} at {when(event.start_at)} — where things stand and what's open.", cta=cta,
                   reason="Built only from earlier meetings you can open. Sent because this meeting is on your linked calendar.")


async def notes_ready(db, row, user):
    meeting = await db.get(Meeting, uuid.UUID(row.payload["meeting_id"]))
    if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, meeting.id):
        return None
    insight = await db.get(MeetingInsight, meeting.id)
    overview = (insight.overview if insight and insight.overview else None) or (meeting.summary or "")
    decisions = (
        await db.execute(
            select(Decision).where(Decision.meeting_id == meeting.id, Decision.deleted_at.is_(None)).order_by(Decision.created_at).limit(5)
        )
    ).scalars().all()
    tasks = (
        await db.execute(
            select(MeetingTask).where(MeetingTask.meeting_id == meeting.id, MeetingTask.deleted_at.is_(None)).order_by(MeetingTask.created_at)
        )
    ).scalars().all()
    people = await _people(db, meeting.id)
    if "cc" in (row.payload or {}):
        return _notes_for_everyone(meeting, overview, decisions, tasks, people, user)
    mine = [t for t in tasks if t.owner_user_id == user.id]
    others = [t for t in tasks if t.owner_user_id != user.id]
    body = (
        paragraph(f"{esc(when(meeting.date))}{' · ' + str(meeting.duration_minutes) + ' min' if meeting.duration_minutes else ''}", muted=True, size=14)
        + _avatars(people)
        + (paragraph(esc(overview[:900] + ("…" if len(overview) > 900 else ""))) if overview else "")
        + (callout(heading("Your tasks", 14).replace("margin:22px", "margin:0") + bullet_list([_task_line(t) for t in mine[:MAX_ITEMS]])) if mine else "")
        + (heading("Decisions") + bullet_list([esc(d.decision) for d in decisions]) if decisions else "")
        + (heading("Other action items") + bullet_list([f"{esc(t.description)}{small(' · ' + esc(t.owner or 'no owner'))}" for t in others[:MAX_ITEMS]]) if others else "")
        + (paragraph(small(f"and {len(others) - MAX_ITEMS} more in Wilco")) if len(others) > MAX_ITEMS else "")
    )
    subject = f"Notes ready: {meeting.title}" + (f" — {len(mine)} task{'s' if len(mine) != 1 else ''} for you" if mine else "")
    return _finish(user, "notes_ready", subject, meeting.title, body,
                   preheader=(overview[:140] if overview else "Summary, decisions and action items are in Wilco."),
                   cta=("Open the notes", app_url(f"/meetings/{meeting.id}")),
                   reason="Sent because you were in this meeting or asked for its notes.")


def _notes_for_everyone(meeting, overview, decisions, tasks, people, user):
    """The shared version of "notes ready": one email To + CC everyone with
    access, so tasks are grouped by person instead of "your tasks"."""
    by_owner: dict[str, list] = {}
    for task in tasks:
        by_owner.setdefault((task.owner or "").strip() or "No owner yet", []).append(task)
    owners = sorted(by_owner, key=lambda name: (name == "No owner yet", name.lower()))
    shown = 0
    task_html = ""
    for name in owners:
        if shown >= MAX_ITEMS:
            break
        items = by_owner[name][: MAX_ITEMS - shown]
        shown += len(items)
        task_html += heading(esc(name), 14) + bullet_list([_task_line(t) for t in items])
    body = (
        paragraph(f"{esc(when(meeting.date))}{' · ' + str(meeting.duration_minutes) + ' min' if meeting.duration_minutes else ''}", muted=True, size=14)
        + _avatars(people)
        + (paragraph(esc(overview[:900] + ("…" if len(overview) > 900 else ""))) if overview else "")
        + (heading("Action items") + task_html if task_html else "")
        + (paragraph(small(f"and {len(tasks) - shown} more in Wilco")) if len(tasks) > shown else "")
        + (heading("Decisions") + bullet_list([esc(d.decision) for d in decisions]) if decisions else "")
    )
    return _finish(user, "notes_ready", f"Notes ready: {meeting.title}", meeting.title, body,
                   preheader=(overview[:140] if overview else "Summary, decisions and action items are in Wilco."),
                   cta=("Open the notes", app_url(f"/meetings/{meeting.id}")),
                   reason="Sent to everyone with access to this meeting — see To and CC.", shared=True)


async def series_review(db, row, user):
    body = paragraph(f"Hi {esc(first_name(user))},") + paragraph(esc(row.payload.get("message")))
    return _finish(user, "series_review", "Confirm what got done since the last meeting", "Since last time", body,
                   preheader=row.payload.get("message", ""), cta=("Review and confirm", app_url(row.payload.get("link") or "/meetings")),
                   reason="Sent for recurring meetings you're part of. Nothing is closed until someone confirms it.")


async def tasks_assigned(db, row, user):
    meeting_id = _id_in(row.payload.get("link"))
    if meeting_id is None:
        return None
    # The "notes ready" email for this meeting already lists their tasks.
    covered = await db.scalar(
        select(func.count()).select_from(EmailOutbox).where(
            EmailOutbox.kind == "notes_ready",
            or_(EmailOutbox.user_id == user.id, EmailOutbox.payload.contains({"cc": [str(user.id)]})),
            EmailOutbox.payload["meeting_id"].astext == str(meeting_id), EmailOutbox.status.in_(("queued", "sent")),
        )
    )
    if covered:
        row.last_error = "Covered by the meeting's notes-ready email"
        return None
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None or meeting.deleted_at is not None or not await user_can_read_meeting(db, user, meeting.id):
        return None
    tasks = (
        await db.execute(
            select(MeetingTask).where(
                MeetingTask.meeting_id == meeting_id, MeetingTask.owner_user_id == user.id,
                MeetingTask.deleted_at.is_(None), MeetingTask.status != "done",
            )
        )
    ).scalars().all()
    if meeting is None or not tasks:
        return None
    body = (
        paragraph(f"Hi {esc(first_name(user))},")
        + paragraph(f"You were given {len(tasks)} task{'s' if len(tasks) != 1 else ''} in <strong>{esc(meeting.title)}</strong> {small('· ' + esc(when(meeting.date, time=False)))}.")
        + bullet_list([_task_line(t) for t in tasks[:MAX_ITEMS]])
    )
    return _finish(user, "tasks_assigned", f"{len(tasks)} task{'s' if len(tasks) != 1 else ''} for you from {meeting.title}", "New tasks for you", body,
                   preheader="; ".join(t.description for t in tasks[:3]), cta=("See your tasks", app_url(row.payload.get("link") or "/tasks?owner=me")),
                   reason="Sent because a meeting named you as the owner.")


async def _simple(user, kind, subject, title, row, cta_label, reason):
    body = paragraph(f"Hi {esc(first_name(user))},") + paragraph(esc(row.payload.get("message")))
    return _finish(user, kind, subject, title, body, preheader=row.payload.get("message", ""),
                   cta=(cta_label, app_url(row.payload.get("link") or "/dashboard")), reason=reason)


async def task_assigned(db, row, user):
    return await _simple(user, "task_assigned", "A task was assigned to you", "A task for you", row, "Open the task", "Sent because a colleague assigned you a task.")


async def meeting_access(db, row, user):
    return await _simple(user, "meeting_access", "Meeting notes were shared with you", "Notes shared with you", row, "Open the notes", "Sent because someone gave you access to these notes.")


async def meeting_access_pending(db, row, user):
    return await _simple(user, "meeting_access_pending", "Colleagues are waiting for access to your notes", "Share these notes?", row,
                         "Review who can see them", "Sent because you recorded or organised this meeting.")


# ---------------------------------------------------------------- scheduled

async def daily_reminders(db, row, user):
    today = datetime.datetime.now(LOCAL).date()
    rows = (
        await db.execute(
            select(MeetingTask, Meeting.title)
            .join(Meeting, Meeting.id == MeetingTask.meeting_id)
            .where(
                MeetingTask.deleted_at.is_(None), Meeting.deleted_at.is_(None), MeetingTask.status != "done",
                MeetingTask.due_date.isnot(None), MeetingTask.due_date <= today, _mine_clause(user),
                meeting_visibility_clause(user),
            )
            .order_by(MeetingTask.due_date)
        )
    ).all()
    if not rows:
        return None
    overdue = [(t, title) for t, title in rows if t.due_date < today]
    due = [(t, title) for t, title in rows if t.due_date == today]
    body = paragraph(f"Good morning {esc(first_name(user))},")
    if due:
        body += heading(f"Due today ({len(due)})") + bullet_list([_task_line(t, title) for t, title in due[:MAX_ITEMS]])
    if overdue:
        body += heading(f"Overdue ({len(overdue)})") + bullet_list([_task_line(t, title) for t, title in overdue[:MAX_ITEMS]])
    parts = [f"{len(due)} due today" if due else "", f"{len(overdue)} overdue" if overdue else ""]
    summary = " and ".join(p for p in parts if p)
    return _finish(user, "daily_reminders", f"Your tasks: {summary}", "Today's tasks", body,
                   preheader=summary, cta=("Open your tasks", app_url("/tasks?owner=me")),
                   reason="A morning reminder, only on days you have something due or overdue.")


async def weekly_digest(db, row, user):
    now = email_service._now()
    local_today = now.astimezone(LOCAL).date()
    start = datetime.datetime.combine(local_today - datetime.timedelta(days=7), datetime.time(), LOCAL)
    end = datetime.datetime.combine(local_today, datetime.time(), LOCAL)
    visible = meeting_visibility_clause(user)
    meetings = (
        await db.execute(
            select(Meeting).where(Meeting.deleted_at.is_(None), Meeting.date >= start, Meeting.date < end, visible).order_by(Meeting.date.desc())
        )
    ).scalars().all()
    ids = [m.id for m in meetings]
    titles = {m.id: m.title for m in meetings}
    decisions = (
        await db.execute(select(Decision).where(Decision.meeting_id.in_(ids), Decision.deleted_at.is_(None)).order_by(Decision.created_at.desc()).limit(6))
    ).scalars().all() if ids else []
    open_tasks = (
        await db.execute(
            select(MeetingTask, Meeting.title)
            .join(Meeting, Meeting.id == MeetingTask.meeting_id)
            .where(MeetingTask.deleted_at.is_(None), Meeting.deleted_at.is_(None), MeetingTask.status != "done", _mine_clause(user), visible)
            .order_by(MeetingTask.due_date.nulls_last(), MeetingTask.created_at.desc())
        )
    ).all()
    overdue = sum(1 for t, _ in open_tasks if t.due_date and t.due_date < local_today)
    upcoming = (
        await db.execute(
            select(CalendarEvent).where(
                CalendarEvent.user_id == user.id, CalendarEvent.cancelled.is_(False),
                CalendarEvent.start_at >= now, CalendarEvent.start_at < now + datetime.timedelta(days=7),
            ).order_by(CalendarEvent.start_at).limit(6)
        )
    ).scalars().all()
    if not meetings and not open_tasks and not upcoming:
        return None
    stat = lambda n, label: (  # noqa: E731
        f'<td style="padding:10px 12px;border:1px solid #EBE5DA;border-radius:8px;text-align:center;" class="callout">'
        f'<span style="display:block;font:600 20px sans-serif;">{n}</span>{small(label)}</td>'
    )
    stats = (
        '<table role="presentation" cellpadding="0" cellspacing="6" width="100%" style="margin:4px 0 8px;"><tr>'
        + stat(len(meetings), "meetings") + stat(len(decisions), "decisions") + stat(len(open_tasks), "open tasks") + stat(overdue, "overdue")
        + "</tr></table>"
    )
    body = paragraph(f"Good morning {esc(first_name(user))}, here's your week in Wilco.") + stats
    if decisions:
        body += heading("Decisions last week") + bullet_list([f"{esc(d.decision)}{small(' · ' + esc(titles.get(d.meeting_id, '')))}" for d in decisions])
    if open_tasks:
        body += heading("On your plate") + bullet_list([_task_line(t, title) for t, title in open_tasks[:MAX_ITEMS]])
        if len(open_tasks) > MAX_ITEMS:
            body += paragraph(small(f"and {len(open_tasks) - MAX_ITEMS} more"))
    if upcoming:
        body += heading("Coming up") + bullet_list([f"{esc(e.title)}{small(' · ' + esc(when(e.start_at)))}" for e in upcoming])
    if meetings:
        body += heading("Meetings last week") + bullet_list(
            [f'<a href="{esc(app_url(f"/meetings/{m.id}"))}" style="color:#2E2A8C;">{esc(m.title)}</a>{small(" · " + esc(when(m.date, time=False)))}' for m in meetings[:MAX_ITEMS]]
        )
    plural = lambda n, word: f"{n} {word}{'' if n == 1 else 's'}"  # noqa: E731
    return _finish(user, "weekly_digest", f"Your week in Wilco: {plural(len(meetings), 'meeting')}, {plural(len(open_tasks), 'open task')}", "Your week in Wilco", body,
                   preheader=f"{len(decisions)} decisions, {overdue} overdue tasks, {len(upcoming)} meetings coming up.",
                   cta=("Open Wilco", app_url("/dashboard")),
                   reason=f"Sent every {email_service.WEEKDAYS[email_service.schedule_for(user)['digest_day']]} morning. Change the day in Settings → Email.")


RENDERERS = {
    "password_reset": password_reset,
    "password_reset_google": password_reset_google,
    "password_changed": password_changed,
    "invite": invite,
    "welcome": welcome,
    "calendar_error": calendar_error,
    "notetaker_signed_out": notetaker_signed_out,
    "pre_meeting_brief": pre_meeting_brief,
    "notes_ready": notes_ready,
    "series_review": series_review,
    "tasks_assigned": tasks_assigned,
    "task_assigned": task_assigned,
    "meeting_access": meeting_access,
    "meeting_access_pending": meeting_access_pending,
    "daily_reminders": daily_reminders,
    "weekly_digest": weekly_digest,
}
assert set(RENDERERS) == set(email_service.KINDS), "every email kind needs a story"


# Emails that exist because the reader is on a meeting. Someone outside the
# company gets them only once the meeting was deliberately shared with them
# (email_service.may_email_about_meeting) — notes_ready checks every To/CC
# recipient in email_service._recipients.
_ABOUT_A_MEETING = {"tasks_assigned", "meeting_access", "meeting_access_pending", "series_review"}


async def render(db: AsyncSession, row: EmailOutbox, user: User | None) -> dict | None:
    if row.kind in _ABOUT_A_MEETING and user is not None:
        meeting_id = _id_in(row.payload.get("link"), rf"(?<=/meetings/){_UUID}")
        if meeting_id and not await email_service.may_email_about_meeting(db, user, meeting_id):
            row.last_error = "Outside the company and the meeting wasn't shared with them in Wilco"
            return None
    return await RENDERERS[row.kind](db, row, user)
