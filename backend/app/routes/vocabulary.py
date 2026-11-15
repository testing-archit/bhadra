"""Vocabulary: the names and terms transcription gets wrong.

Shared by the whole company. Anyone can add a keyword or a "heard as →
actually" rule (and so can their edits, automatically — see
vocabulary_service); the person who added an entry or an admin can delete it.

Teammates lists whose names are listened for — every account, the guests
someone added, and guests who keep turning up in your meetings — each with
the spellings transcription has written for them. Suggestions are the
mishearings Wilco noticed by itself; anyone who can read one of the
meetings it came from can accept or dismiss it.
"""

import datetime
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.config import settings
from app.database.models import KnownPerson, Meeting, MeetingAttendee, TermCorrection, TermSuggestion, User
from app.dependencies import get_current_user, is_admin, meeting_visibility_clause
from app.services import vocabulary_service

router = APIRouter(prefix="/api/vocabulary", tags=["vocabulary"])

MAX_TERM_CHARS = 80


def _clean(value: str) -> str:
    return " ".join(value.split())


class VocabularyCreate(BaseModel):
    # The right spelling ("Sky Lattice").
    term: str = Field(min_length=1, max_length=MAX_TERM_CHARS)
    # What transcription writes instead ("Sky Tech", "Skytech"). Empty: a
    # keyword Prisma is told to listen for.
    heard_as: list[str] = Field(default_factory=list, max_length=10)
    # Also fix meetings that already have the wrong spelling.
    fix_past: bool = True

    @field_validator("term")
    @classmethod
    def clean_term(cls, value: str) -> str:
        value = _clean(value)
        if not value:
            raise ValueError("Enter the correct spelling")
        return value

    @field_validator("heard_as")
    @classmethod
    def clean_heard_as(cls, values: list[str]) -> list[str]:
        cleaned = [_clean(value)[:MAX_TERM_CHARS] for value in values]
        return list(dict.fromkeys(value for value in cleaned if value))


class VocabularyUpdate(BaseModel):
    enabled: bool | None = None
    term: str | None = Field(default=None, max_length=MAX_TERM_CHARS)


def _payload(entry: TermCorrection, creator: str | None = None, meeting_title: str | None = None) -> dict:
    return {
        "id": str(entry.id),
        "heard_as": entry.wrong,
        "term": entry.right,
        "kind": "keyword" if entry.wrong is None else "correction",
        "source": entry.source,
        "note": entry.note,
        "enabled": entry.disabled_at is None,
        "times_confirmed": entry.times_confirmed,
        "times_applied": entry.times_applied,
        "created_by": creator,
        "created_by_id": str(entry.created_by) if entry.created_by else None,
        "source_meeting_id": str(entry.source_meeting_id) if entry.source_meeting_id else None,
        "source_meeting_title": meeting_title,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


@router.get("")
async def list_vocabulary(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(
        select(TermCorrection, User.name)
        .outerjoin(User, User.id == TermCorrection.created_by)
        .order_by(func.lower(TermCorrection.right), TermCorrection.wrong.nulls_first())
    )).all()
    # The list is company-wide; where a correction was learned is only shown
    # to people who can open that meeting (its title can be confidential).
    readable = await _readable_meetings(db, user, {entry.source_meeting_id for entry, _ in rows if entry.source_meeting_id})
    return [
        _payload(entry, creator, readable.get(entry.source_meeting_id)) if entry.source_meeting_id in readable
        else {**_payload(entry, creator), "source_meeting_id": None}
        for entry, creator in rows
    ]


@router.post("", status_code=201)
async def add_vocabulary(
    body: VocabularyCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    heard_as = [value for value in body.heard_as if value.lower() != body.term.lower()]
    if body.heard_as and not heard_as:
        raise HTTPException(status_code=422, detail="“Heard as” must differ from the correct spelling")
    protected = await vocabulary_service.protected_names(db)
    real = [value for value in heard_as if value.lower() in protected]
    if real:
        raise HTTPException(
            status_code=422,
            detail=f"“{real[0]}” is someone's name at the company, so it can't be treated as a mishearing.",
        )

    entries: list[TermCorrection] = []
    if not heard_as:
        entry = (await db.execute(
            select(TermCorrection).where(TermCorrection.wrong.is_(None), func.lower(TermCorrection.right) == body.term.lower())
        )).scalar_one_or_none()
        if entry is None:
            entry = TermCorrection(right=body.term, source="manual", created_by=user.id)
            db.add(entry)
        entry.disabled_at = None
        entries.append(entry)
    for wrong in heard_as:
        entry = (await db.execute(
            select(TermCorrection).where(func.lower(TermCorrection.wrong) == wrong.lower())
        )).scalar_one_or_none()
        if entry is None:
            entry = TermCorrection(wrong=wrong, right=body.term, source="manual", created_by=user.id)
            db.add(entry)
        else:
            entry.right = body.term
            entry.source = "manual"
        entry.disabled_at = None
        entries.append(entry)
    await db.commit()
    for entry in entries:
        await db.refresh(entry)

    rules = [(wrong, body.term) for wrong in heard_as]
    if rules and body.fix_past:
        background_tasks.add_task(vocabulary_service.fix_past_meetings, rules, user.id)
    return [_payload(entry, user.name) for entry in entries]


async def _entry(db: AsyncSession, entry_id: uuid.UUID) -> TermCorrection:
    entry = await db.get(TermCorrection, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Vocabulary entry not found")
    return entry


@router.patch("/{entry_id}")
async def update_vocabulary(
    entry_id: uuid.UUID,
    body: VocabularyUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    entry = await _entry(db, entry_id)
    if body.term is not None:
        term = _clean(body.term)
        if not term or (entry.wrong and term.lower() == entry.wrong.lower()):
            raise HTTPException(status_code=422, detail="Enter a different correct spelling")
        entry.right = term
        entry.source = "manual"
    if body.enabled is not None:
        entry.disabled_at = None if body.enabled else datetime.datetime.now(datetime.UTC)
    await db.commit()
    await db.refresh(entry)
    return _payload(entry)


@router.delete("/{entry_id}")
async def delete_vocabulary(
    entry_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    entry = await _entry(db, entry_id)
    if not is_admin(user) and entry.created_by != user.id:
        raise HTTPException(status_code=403, detail="Only the person who added this, or an admin, can delete it. You can switch it off instead.")
    await db.delete(entry)
    await db.commit()
    return {"ok": True}


# --- teammates -------------------------------------------------------------

# A guest counts as regular after this many of your meetings in this window.
GUEST_MIN_MEETINGS = 2
GUEST_WINDOW_DAYS = 180
MAX_GUESTS = 50


class PersonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_TERM_CHARS)
    email: str | None = Field(default=None, max_length=320)
    note: str | None = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = _clean(value)
        if not value or "@" in value:
            raise ValueError("Enter the person's name")
        return value


def _heard_as(rules: list[TermCorrection], name: str) -> list[dict]:
    return [
        {"id": str(rule.id), "heard_as": rule.wrong, "enabled": rule.disabled_at is None, "source": rule.source}
        for rule in rules
        if rule.right.lower() == name.lower()
    ]


@router.get("/people")
async def list_people(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Whose names are listened for, with what transcription has heard for
    each: accounts, guests someone added, the server's roster, and guests
    in two or more of *your* meetings (only meetings you can read)."""
    rules = list((await db.execute(select(TermCorrection).where(TermCorrection.wrong.is_not(None)))).scalars().all())
    people: list[dict] = []
    taken: set[str] = set()

    def add(entry: dict) -> None:
        taken.add(entry["name"].lower())
        people.append({**entry, "heard_as": _heard_as(rules, entry["name"])})

    accounts = (await db.execute(
        select(User).where(User.status == "active", User.name.is_not(None)).order_by(func.lower(User.name))
    )).scalars().all()
    for account in accounts:
        if account.name.strip() and account.name.strip().lower() not in taken:
            add({"id": str(account.id), "name": account.name.strip(), "email": account.email, "kind": "account", "note": account.job_title, "meetings": None, "can_delete": False})

    known = (await db.execute(
        select(KnownPerson, User.name).outerjoin(User, User.id == KnownPerson.created_by).order_by(func.lower(KnownPerson.name))
    )).all()
    for person, creator in known:
        if person.name.lower() not in taken:
            add({
                "id": str(person.id), "name": person.name, "email": person.email, "kind": "added",
                "note": person.note or (f"Added by {creator}" if creator else None), "meetings": None,
                "can_delete": is_admin(user) or person.created_by == user.id,
            })

    # A roster first name ("Archit") that is already someone's account is them.
    first_names = {person["name"].split()[0].lower() for person in people}
    for name in settings.team_roster_list:
        if name.lower() not in taken and name.lower() not in first_names:
            add({"id": f"roster:{name}", "name": name, "email": None, "kind": "roster", "note": "From the server's TEAM_ROSTER setting", "meetings": None, "can_delete": False})

    since = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=GUEST_WINDOW_DAYS)
    rows = (await db.execute(
        select(MeetingAttendee.display_name, func.count(func.distinct(MeetingAttendee.meeting_id)))
        .join(Meeting, Meeting.id == MeetingAttendee.meeting_id)
        .where(
            MeetingAttendee.user_id.is_(None),
            Meeting.deleted_at.is_(None),
            Meeting.date >= since,
            meeting_visibility_clause(user),
        )
        .group_by(MeetingAttendee.display_name)
    )).all()
    guests: dict[str, list] = {}
    for display_name, count in rows:
        name = _clean(display_name or "")
        if not name or "@" in name or name.lower() == settings.notetaker_email.lower():
            continue
        entry = guests.setdefault(name.lower(), [name, 0])
        entry[1] += count
    regular = sorted((g for key, g in guests.items() if g[1] >= GUEST_MIN_MEETINGS and key not in taken), key=lambda g: (-g[1], g[0].lower()))
    for name, count in regular[:MAX_GUESTS]:
        add({"id": f"guest:{name}", "name": name, "email": None, "kind": "guest", "note": None, "meetings": count, "can_delete": False})
    return people


@router.post("/people", status_code=201)
async def add_person(body: PersonCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """List a guest without a Wilco account — a client, vendor or regular
    visitor — so their name is listened for in every meeting."""
    existing = (await db.execute(select(KnownPerson).where(func.lower(KnownPerson.name) == body.name.lower()))).scalar_one_or_none()
    account = (await db.execute(
        select(User.id).where(func.lower(User.name) == body.name.lower(), User.status == "active")
    )).first()
    if account is not None:
        raise HTTPException(status_code=409, detail=f"{body.name} already has a Wilco account, so their name is listened for already.")
    if existing is None:
        existing = KnownPerson(
            name=body.name, email=(body.email or "").strip() or None, note=_clean(body.note or "") or None, created_by=user.id
        )
        db.add(existing)
        await db.commit()
        await db.refresh(existing)
    return {
        "id": str(existing.id), "name": existing.name, "email": existing.email, "kind": "added", "note": existing.note,
        "meetings": None, "can_delete": True, "heard_as": [],
    }


@router.delete("/people/{person_id}")
async def delete_person(person_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    person = await db.get(KnownPerson, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    if not is_admin(user) and person.created_by != user.id:
        raise HTTPException(status_code=403, detail="Only the person who added them, or an admin, can remove them.")
    await db.delete(person)
    await db.commit()
    return {"ok": True}


# --- suggestions -------------------------------------------------------------


class SuggestionAccept(BaseModel):
    # Also fix meetings that already have the misheard spelling.
    fix_past: bool = True


async def _readable_meetings(db: AsyncSession, user: User, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = (await db.execute(
        select(Meeting.id, Meeting.title).where(Meeting.id.in_(ids), Meeting.deleted_at.is_(None), meeting_visibility_clause(user))
    )).all()
    return {meeting_id: title for meeting_id, title in rows}


def _meeting_ids(suggestion: TermSuggestion) -> list[uuid.UUID]:
    ids = []
    for value in suggestion.meeting_ids or []:
        try:
            ids.append(uuid.UUID(value))
        except (TypeError, ValueError):
            continue
    return ids


def _suggestion_payload(suggestion: TermSuggestion, readable: dict[uuid.UUID, str]) -> dict:
    mine = [meeting_id for meeting_id in _meeting_ids(suggestion) if meeting_id in readable]
    latest = suggestion.last_meeting_id if suggestion.last_meeting_id in readable else (mine[-1] if mine else None)
    return {
        "id": str(suggestion.id),
        "heard_as": suggestion.wrong,
        "term": suggestion.right,
        "reason": suggestion.reason,
        "status": suggestion.status,
        "occurrences": suggestion.occurrences,
        "meetings": len(suggestion.meeting_ids or []),
        "auto_apply_at": vocabulary_service.auto_apply_threshold(suggestion.reason == "captions"),
        "meeting_id": str(latest) if latest else None,
        "meeting_title": readable.get(latest) if latest else None,
    }


@router.get("/suggestions")
async def list_suggestions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Pending mishearings Wilco noticed, from meetings you can read."""
    pending = (await db.execute(
        select(TermSuggestion).where(TermSuggestion.status == "pending").order_by(TermSuggestion.updated_at.desc()).limit(200)
    )).scalars().all()
    readable = await _readable_meetings(db, user, {mid for s in pending for mid in _meeting_ids(s)})
    return [
        _suggestion_payload(suggestion, readable)
        for suggestion in pending
        if any(mid in readable for mid in _meeting_ids(suggestion))
    ]


async def _suggestion(db: AsyncSession, user: User, suggestion_id: uuid.UUID) -> TermSuggestion:
    suggestion = await db.get(TermSuggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if not await _readable_meetings(db, user, set(_meeting_ids(suggestion))):
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if suggestion.status != "pending":
        raise HTTPException(status_code=409, detail="Someone already decided on this suggestion")
    return suggestion


@router.post("/suggestions/{suggestion_id}/accept")
async def accept_suggestion(
    suggestion_id: uuid.UUID,
    body: SuggestionAccept,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    suggestion = await _suggestion(db, user, suggestion_id)
    entry = await vocabulary_service.accept_suggestion(db, suggestion, user)
    rule = (suggestion.wrong, entry.right)
    await db.commit()
    await db.refresh(entry)
    if body.fix_past:
        background_tasks.add_task(vocabulary_service.fix_past_meetings, [rule], user.id)
    return _payload(entry, user.name)


@router.post("/suggestions/{suggestion_id}/dismiss")
async def dismiss_suggestion(
    suggestion_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    suggestion = await _suggestion(db, user, suggestion_id)
    suggestion.status = "dismissed"
    suggestion.decided_by = user.id
    suggestion.decided_at = datetime.datetime.now(datetime.UTC)
    await db.commit()
    return {"ok": True}
