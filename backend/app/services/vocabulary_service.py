"""Learning from corrections, so a misheard name is fixed once.

When someone edits a task, decision, risk, transcript line or summary and
the edit swaps a misheard name or term for the right one ("Ras" → "Raj"):

1. the swap is applied across that meeting — transcript, summary, AI notes,
   follow-up draft and every other item — so nothing still says "Ras";
2. it is remembered company-wide (`term_corrections`): every new transcript
   gets it applied, and the right term is sent to Prisma as a keyterm so
   it is heard correctly in the first place.

An edit only counts as a correction when it is small and looks like a
mishearing: one to three words replaced, the new words capitalised (names,
products), the old and new spelling alike, and the old word not the name of
a real person — so reassigning a task from Archit to Satyendra is a
reassignment, never a "correction" of everyone called Archit.

It also learns without anyone editing (`learn_from_meeting`, after every
meeting's notes): a word that sounds like an invitee's name but isn't
spelled like it ("Arshit" in a meeting Archit was invited to), backed by
Meet's captions when the notetaker recorded them, becomes a suggestion on
the Vocabulary page — applied automatically once heard in enough meetings.

Names reach the transcriber and the notes model too: the people invited to
the meeting first, then the company's keywords, corrections and people
(accounts, plus the guests listed under Vocabulary → Teammates), then
keywords picked up from projects, Jira and meeting titles (`keyterms`,
`prompt_hint`). Before notes are written the transcript gets every
correction, and the notes get them again afterwards (`clean_extraction`), so
a summary never brings a fixed mishearing back.
"""

import asyncio
import datetime
import difflib
import logging
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Decision,
    KnownPerson,
    Meeting,
    MeetingAttendee,
    MeetingInsight,
    MeetingTask,
    Risk,
    Project,
    RecordingSession,
    TaskHistory,
    TermCorrection,
    TermSuggestion,
    TranscriptEdit,
    User,
)
from app.services import transcript_service

logger = logging.getLogger(__name__)

MAX_PHRASE_WORDS = 3
# More changed spots than this is a rewrite, not a fixed mishearing.
MAX_CHANGES_PER_EDIT = 3
# How alike the two spellings must be ("ras"/"raj" is 0.67).
MIN_SIMILARITY = 0.5
# Prisma keyterms sent per request, learned terms included.
MAX_KEYTERMS = 50
LOAD_TIMEOUT_SECONDS = 3.0

# Words that are often swapped on purpose and happen to look alike.
_NOT_A_MISHEARING = {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "today", "tomorrow", "yesterday",
}
_EDGE_PUNCT = re.compile(r"^[^\w]+|[^\w]+$")
_WORDLIKE = re.compile(r"^\w[\w'’.\-]*$")

Rule = tuple[str, str]  # (wrong, right)


def _strip(token: str) -> str:
    return _EDGE_PUNCT.sub("", token)


def _similarity(wrong: str, right: str) -> float:
    squash = lambda value: re.sub(r"\W+", "", value.lower())  # noqa: E731
    return difflib.SequenceMatcher(None, squash(wrong), squash(right)).ratio()


def _looks_misheard(old_words: list[str], new_words: list[str], protected: set[str] | frozenset[str]) -> bool:
    wrong, right = " ".join(old_words), " ".join(new_words)
    return not (
        wrong == right
        or len(old_words) > MAX_PHRASE_WORDS
        or len(new_words) > MAX_PHRASE_WORDS
        or not all(_WORDLIKE.match(word) for word in old_words + new_words)
        or not any(word[:1].isupper() for word in new_words)
        or any(word.lower() in _NOT_A_MISHEARING for word in old_words + new_words)
        or wrong.lower() in protected
        or any(word.lower() in protected for word in old_words)
        or _similarity(wrong, right) < MIN_SIMILARITY
    )


def _tokens(text: str) -> tuple[list[str], set[int]]:
    """Words without edge punctuation, and the indexes that start a sentence
    (capitalised there for grammar, not because they are names)."""
    words: list[str] = []
    starts: set[int] = set()
    sentence_start = True
    for raw in (text or "").split():
        word = _strip(raw)
        if not word:
            continue
        if sentence_start:
            starts.add(len(words))
        words.append(word)
        sentence_start = raw.rstrip("\"')”’)]").endswith((".", "!", "?", ":"))
    return words, starts


def _phrase_spans(a: list[str], b: list[str], starts: set[int], i1: int, i2: int, j1: int, j2: int):
    """The changed words alone first ("Ras" → "Raj"), then widened by the
    capitalised name words they share with their neighbours: "Tech" →
    "Lattice" is no mishearing, but "Sky Tech" → "Sky Lattice" is."""
    yield i1, i2, j1, j2
    name_word = lambda index: a[index][:1].isupper() and index not in starts  # noqa: E731
    for _ in range(MAX_PHRASE_WORDS - 1):
        if i1 > 0 and j1 > 0 and a[i1 - 1] == b[j1 - 1] and name_word(i1 - 1):
            i1, j1 = i1 - 1, j1 - 1
        elif i2 < len(a) and j2 < len(b) and a[i2] == b[j2] and name_word(i2):
            i2, j2 = i2 + 1, j2 + 1
        else:
            return
        yield i1, i2, j1, j2


def detect(old: str, new: str, protected: set[str] | frozenset[str] = frozenset()) -> list[Rule]:
    """The (wrong, right) swaps in an edit that look like fixed mishearings.
    `protected` holds lower-cased names of real people."""
    a, starts = _tokens(old)
    b, _ = _tokens(new)
    changes = [op for op in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op[0] != "equal"]
    if not changes or len(changes) > MAX_CHANGES_PER_EDIT:
        return []
    found: list[Rule] = []
    for tag, i1, i2, j1, j2 in changes:
        if tag != "replace":
            continue
        for i1, i2, j1, j2 in _phrase_spans(a, b, starts, i1, i2, j1, j2):
            old_words, new_words = a[i1:i2], b[j1:j2]
            if _looks_misheard(old_words, new_words, protected):
                found.append((" ".join(old_words), " ".join(new_words)))
                break
    return found


def _phrase(words: str) -> str:
    return r"\s+".join(re.escape(word) for word in words.split())


def _pattern(wrong: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + _phrase(wrong) + r"(?!\w)", re.IGNORECASE)


def _rule_pattern(wrong: str, right: str) -> re.Pattern:
    """Matches the right spelling (kept as it is) or the wrong one, so text
    already corrected is never corrected again — "Lattice" → "Sky Lattice"
    must not turn "Sky Lattice" into "Sky Sky Lattice"."""
    return re.compile(r"(?<!\w)(?:(?P<keep>" + _phrase(right) + r")|" + _phrase(wrong) + r")(?!\w)", re.IGNORECASE)


def apply_text(text: str | None, rules: list[Rule]) -> tuple[str | None, Counter]:
    """`text` with every rule applied (whole words, any capitalisation —
    "Skytech", "SkyTech" and "skytech" are one mishearing), and how many
    times each rule's wrong term was replaced. Applying it twice changes
    nothing more."""
    counts: Counter = Counter()
    if not text:
        return text, counts
    for wrong, right in rules:
        replaced = 0

        def swap(match: re.Match) -> str:
            nonlocal replaced
            if match.group("keep") is not None:
                return match.group(0)
            replaced += 1
            return right

        text = _rule_pattern(wrong, right).sub(swap, text)
        if replaced:
            counts[wrong] += replaced
    return text, counts


def apply_deep(value: Any, rules: list[Rule]) -> tuple[Any, Counter]:
    """apply_text over every string inside JSON-like data (a new object is
    returned, so ARRAY/JSONB columns register the change)."""
    if isinstance(value, str):
        return apply_text(value, rules)
    counts: Counter = Counter()
    if isinstance(value, list):
        out = []
        for item in value:
            item, n = apply_deep(item, rules)
            out.append(item)
            counts += n
        return out, counts
    if isinstance(value, dict):
        out_dict = {}
        for key, item in value.items():
            # Ids and timings are never words; leave them alone.
            if key in {"segment_id", "id", "seq", "start_ms", "end_ms", "verified"}:
                out_dict[key] = item
                continue
            item, n = apply_deep(item, rules)
            out_dict[key] = item
            counts += n
        return out_dict, counts
    return value, counts


def _name_keys(names: list[str | None]) -> set[str]:
    keys: set[str] = set()
    for name in names:
        name = (name or "").strip().lower()
        if name:
            keys.add(name)
            keys.update(part for part in name.split() if len(part) > 1)
    return keys


async def protected_names(db: AsyncSession, meeting_id: uuid.UUID | None = None) -> set[str]:
    """Lower-cased names (and name parts) of everyone with a Charcha account,
    the guests listed under Teammates, and the meeting's attendees — real
    people, never "misheard"."""
    names = list((await db.execute(select(User.name).where(User.name.is_not(None)))).scalars().all())
    names += list((await db.execute(select(KnownPerson.name))).scalars().all())
    if meeting_id is not None:
        names += list(
            (await db.execute(select(MeetingAttendee.display_name).where(MeetingAttendee.meeting_id == meeting_id)))
            .scalars()
            .all()
        )
    return _name_keys(names)


@dataclass
class Propagation:
    replaced: int = 0
    jira_task_ids: list[uuid.UUID] = field(default_factory=list)
    transcript_changed: bool = False


async def propagate(db: AsyncSession, meeting: Meeting, rules: list[Rule], user: User | None) -> Propagation:
    """Apply the rules to everything in one meeting that holds its words.
    `user` is None when Charcha applies them itself."""
    result = Propagation()
    user_id = user.id if user is not None else None
    now = datetime.datetime.now(datetime.UTC)
    notes_current = meeting.insights_revision is not None and meeting.insights_revision >= (meeting.transcript_revision or 1)

    segments = await transcript_service.load_segments(db, meeting.id)
    edits: list[tuple[Any, str, str]] = []
    for segment in segments:
        text, counts = apply_text(segment.text, rules)
        if counts:
            edits.append((segment, segment.text, text))
            segment.text = text
            segment.revision = (segment.revision or 1) + 1
            segment.edited_at = now
            segment.edited_by = user_id
            result.replaced += sum(counts.values())
    if edits:
        meeting.transcript_revision = (meeting.transcript_revision or 1) + 1
        meeting.transcript = transcript_service.render_transcript(segments)
        for segment, old, text in edits:
            db.add(TranscriptEdit(
                meeting_id=meeting.id, segment_id=segment.id, field="text", old_value=old, new_value=text,
                transcript_revision=meeting.transcript_revision, edited_by=user_id,
            ))
        # The notes are corrected below as well, so they stay current.
        if notes_current:
            meeting.insights_revision = meeting.transcript_revision
        result.transcript_changed = True
    elif not segments:
        meeting.transcript, counts = apply_text(meeting.transcript, rules)
        result.replaced += sum(counts.values())
        result.transcript_changed = bool(counts)

    for name in ("title", "summary"):
        value, counts = apply_text(getattr(meeting, name), rules)
        if counts:
            setattr(meeting, name, value)
            result.replaced += sum(counts.values())

    insight = await db.get(MeetingInsight, meeting.id)
    if insight is not None:
        for name in ("overview", "key_topics", "open_questions", "highlights", "next_steps", "sections", "template_sections", "follow_up_draft"):
            value, counts = apply_deep(getattr(insight, name), rules)
            if counts:
                setattr(insight, name, value)
                result.replaced += sum(counts.values())

    tasks = (await db.execute(
        select(MeetingTask).where(MeetingTask.meeting_id == meeting.id, MeetingTask.deleted_at.is_(None))
    )).scalars().all()
    for task in tasks:
        changed = False
        for name in ("description", "owner", "deadline"):
            old = getattr(task, name)
            value, counts = apply_text(old, rules)
            if counts:
                setattr(task, name, value)
                db.add(TaskHistory(task_id=task.id, changed_by=user_id, field=name, old_value=old, new_value=value, source="vocabulary"))
                result.replaced += sum(counts.values())
                changed = changed or name in {"description", "owner"}
                if name == "owner":
                    from app.services.insight_service import resolve_owner_user_id

                    task.owner_user_id = await resolve_owner_user_id(db, meeting.id, value)
        task.evidence, counts = apply_deep(task.evidence, rules)
        if changed and task.jira_issue_key:
            result.jira_task_ids.append(task.id)

    for model, names in ((Decision, ("decision", "reason", "alternatives", "participants", "evidence")), (Risk, ("description", "evidence"))):
        items = (await db.execute(
            select(model).where(model.meeting_id == meeting.id, model.deleted_at.is_(None))
        )).scalars().all()
        for item in items:
            for name in names:
                value, counts = apply_deep(getattr(item, name), rules)
                if counts:
                    setattr(item, name, value)
                    if name != "evidence":
                        result.replaced += sum(counts.values())
    await db.flush()
    return result


async def learn(db: AsyncSession, rules: list[Rule], user: User, meeting_id: uuid.UUID | None) -> None:
    now = datetime.datetime.now(datetime.UTC)
    for wrong, right in rules:
        existing = (await db.execute(
            select(TermCorrection).where(func.lower(TermCorrection.wrong) == wrong.lower())
        )).scalar_one_or_none()
        if existing is None:
            db.add(TermCorrection(wrong=wrong, right=right, source="learned", created_by=user.id, source_meeting_id=meeting_id))
        else:
            # A rule someone typed in stays theirs; an edit only confirms it.
            if existing.source != "manual":
                existing.right = right
            existing.times_confirmed += 1
            existing.disabled_at = None
        # Someone fixed by hand what Charcha only suspected.
        await db.execute(
            update(TermSuggestion)
            .where(func.lower(TermSuggestion.wrong) == wrong.lower(), TermSuggestion.status == "pending")
            .values(status="accepted", decided_by=user.id, decided_at=now)
        )
        # "Raj" → "Ras" undoes an earlier "Ras" → "Raj"; keep only the newest.
        await db.execute(
            update(TermCorrection)
            .where(func.lower(TermCorrection.wrong) == right.lower(), TermCorrection.disabled_at.is_(None))
            .values(disabled_at=now)
        )
    await db.flush()


async def correct_from_edit(
    db: AsyncSession, meeting_id: uuid.UUID, edits: list[tuple[str | None, str | None]], user: User
) -> tuple[list[dict], Propagation]:
    """Called after a person edits text in a meeting: find fixed
    mishearings, spread them through the meeting and remember them.
    Returns [{wrong, right}] for the response, and what was changed."""
    protected = await protected_names(db, meeting_id)
    rules: list[Rule] = []
    for old, new in edits:
        for rule in detect(old or "", new or "", protected):
            if rule not in rules:
                rules.append(rule)
    if not rules:
        return [], Propagation()
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        return [], Propagation()
    propagation = await propagate(db, meeting, rules, user)
    await learn(db, rules, user, meeting_id)
    logger.info("Learned %s from an edit in meeting %s (%s other places fixed)", rules, meeting_id, propagation.replaced)
    return [{"wrong": wrong, "right": right} for wrong, right in rules], propagation


# --- new transcripts ---------------------------------------------------------


@dataclass
class Vocabulary:
    rules: list[Rule] = field(default_factory=list)
    # Keywords people added or taught.
    keywords: list[str] = field(default_factory=list)
    # Everyone at the company with a name, and the guests under Teammates.
    people: list[str] = field(default_factory=list)
    # Picked up from projects, Jira and meeting titles; listened for last.
    auto_keywords: list[str] = field(default_factory=list)


async def _load() -> Vocabulary:
    from app.database.db import async_session

    async with async_session() as db:
        rows = (await db.execute(
            select(TermCorrection.wrong, TermCorrection.right, TermCorrection.source)
            .where(TermCorrection.disabled_at.is_(None))
            .order_by(TermCorrection.times_confirmed.desc(), TermCorrection.updated_at.desc())
        )).all()
        # Someone has since joined with that name: it isn't a mishearing.
        protected = await protected_names(db)
        people = await team_names(db)
    vocabulary = Vocabulary(people=people)
    for wrong, right, source in rows:
        if wrong is None:
            (vocabulary.auto_keywords if source == "auto" else vocabulary.keywords).append(right)
        elif wrong.lower() not in protected:
            vocabulary.rules.append((wrong, right))
    # Longest first, so "Sky Tech Labs" wins over "Sky Tech".
    vocabulary.rules.sort(key=lambda rule: -len(rule[0]))
    return vocabulary


async def active_vocabulary() -> Vocabulary:
    """The vocabulary for a new transcript. Never fails a transcription: on
    any database trouble there is simply none."""
    try:
        return await asyncio.wait_for(_load(), LOAD_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("Vocabulary unavailable; transcribing without it", exc_info=True)
        return Vocabulary()


def keyterms(roster: list[str], vocabulary: Vocabulary, people: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Terms Prisma should listen for, most useful first, since only
    MAX_KEYTERMS fit: the people in this meeting, the configured roster,
    keywords, the right spelling of every correction, everyone else at the
    company, then keywords picked up automatically."""
    ordered = [
        *people, *roster, *vocabulary.keywords, *(right for _, right in vocabulary.rules),
        *vocabulary.people, *vocabulary.auto_keywords,
    ]
    seen: set[str] = set()
    terms: list[str] = []
    for term in ordered:
        term = " ".join((term or "").split())
        if term and "@" not in term and term.lower() not in seen:
            seen.add(term.lower())
            terms.append(term)
    return terms[:MAX_KEYTERMS]


def apply_to_turns(turns: list[dict], rules: list[Rule]) -> Counter:
    """Fix learned mishearings in provider turns, in place."""
    applied: Counter = Counter()
    for turn in turns:
        text, counts = apply_text(turn.get("text") or "", rules)
        if counts:
            if len(text.split()) != len((turn.get("text") or "").split()):
                turn.pop("words", None)  # word timings no longer line up
            turn["text"] = text
            applied += counts
    return applied


async def record_applied(applied: Counter) -> None:
    if not applied:
        return
    try:
        from app.database.db import async_session

        async with async_session() as db:
            for wrong, count in applied.items():
                await db.execute(
                    update(TermCorrection).where(func.lower(TermCorrection.wrong) == wrong.lower())
                    .values(times_applied=TermCorrection.times_applied + count)
                )
            await db.commit()
    except Exception:
        logger.warning("Could not record learned-vocabulary use", exc_info=True)


# --- past meetings -----------------------------------------------------------


async def fix_past_meetings(
    rules: list[Rule], user_id: uuid.UUID | None, meeting_ids: list[uuid.UUID] | None = None
) -> int:
    """Apply rules someone just added to every existing meeting that still
    has the wrong term (or only to `meeting_ids`; `user_id` None when Charcha
    applies a suggestion itself). Runs in the background; returns meetings
    fixed."""
    from sqlalchemy import or_

    from app.database.db import async_session
    from app.services import meeting_pipeline
    from app.services.meeting_index_service import rebuild_meeting_index

    fixed: list[uuid.UUID] = []
    async with async_session() as db:
        user = await db.get(User, user_id) if user_id is not None else None
        if (user_id is not None and user is None) or not rules:
            return 0
        candidates = (await db.execute(
            select(Meeting.id).where(
                Meeting.deleted_at.is_(None),
                # Known meetings are checked in full; otherwise only ones
                # whose text still has a wrong term.
                Meeting.id.in_(meeting_ids) if meeting_ids is not None else or_(*(
                    column.ilike(f"%{wrong}%")
                    for wrong, _ in rules
                    for column in (Meeting.transcript, Meeting.summary, Meeting.title)
                )),
            )
        )).scalars().all()
        for meeting_id in candidates:
            meeting = await db.get(Meeting, meeting_id)
            result = await propagate(db, meeting, rules, user)
            if result.replaced:
                await rebuild_meeting_index(db, meeting_id)
                fixed.append(meeting_id)
            await db.commit()
    for meeting_id in fixed:
        try:
            await meeting_pipeline.reindex_after_edit(meeting_id)
        except Exception:
            logger.exception("Re-indexing meeting %s after a vocabulary fix failed", meeting_id)
    logger.info("Vocabulary %s fixed %d past meetings", rules, len(fixed))
    return len(fixed)


def schedule_followups(background_tasks, meeting_id: uuid.UUID, propagation: Propagation) -> None:
    """After the request commits: re-index a corrected transcript and push
    corrected Jira-linked tasks."""
    from app.services import jira_service, meeting_pipeline

    if propagation.transcript_changed:
        background_tasks.add_task(meeting_pipeline.reindex_after_edit, meeting_id)
    for task_id in propagation.jira_task_ids:
        background_tasks.add_task(jira_service.push_changes, task_id, {"description", "owner"})


# --- people --------------------------------------------------------------------


def _person_name(value: str | None) -> str:
    """A display name worth listening for: not empty, not an email."""
    value = " ".join((value or "").split())
    return "" if not value or "@" in value else value


def _unique(names) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        name = _person_name(name)
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


async def team_names(db: AsyncSession) -> list[str]:
    """Everyone active at the company with a name, then the guests listed
    under Vocabulary → Teammates."""
    accounts = (await db.execute(
        select(User.name).where(User.name.is_not(None), User.status == "active").order_by(func.lower(User.name))
    )).scalars().all()
    guests = (await db.execute(select(KnownPerson.name).order_by(func.lower(KnownPerson.name)))).scalars().all()
    return _unique([*accounts, *guests])


async def meeting_people(db: AsyncSession, meeting_id: uuid.UUID) -> list[str]:
    """The names of a meeting's attendees — invitees, and whoever Meet saw
    speaking — preferring a colleague's account name."""
    rows = (await db.execute(
        select(MeetingAttendee.display_name, User.name)
        .outerjoin(User, User.id == MeetingAttendee.user_id)
        .where(MeetingAttendee.meeting_id == meeting_id)
    )).all()
    return _unique(account_name or display_name for display_name, account_name in rows)


def people_from_attendees(raw: list | None) -> list[str]:
    """Names from an attendee list as clients send it: bare strings (a name
    or an email) or {name, email} objects."""
    names = []
    for item in raw or []:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            names.append(item.get("name") or "")
    return _unique(names)


# --- notes -------------------------------------------------------------------

MAX_HINT_NAMES = 40
MAX_HINT_TERMS = 60


def prompt_hint(people: list[str], vocabulary: Vocabulary, roster: list[str] = ()) -> str:
    """What the notes model is told about spelling: the people in this
    meeting, everyone else, the company's terms, and known mishearings —
    so a summary says "Archit" even where the transcript says "Arshit"."""
    people = _unique(people)[:MAX_HINT_NAMES]
    taken = {name.lower() for name in people}
    company = [name for name in _unique([*roster, *vocabulary.people]) if name.lower() not in taken][:MAX_HINT_NAMES]
    taken |= {name.lower() for name in company}
    terms = [
        term for term in _unique([*vocabulary.keywords, *(right for _, right in vocabulary.rules), *vocabulary.auto_keywords])
        if term.lower() not in taken
    ][:MAX_HINT_TERMS]
    rules = vocabulary.rules[:MAX_HINT_TERMS]
    if not (people or company or terms or rules):
        return ""
    lines = ["Spelling of names and terms (use exactly these spellings):"]
    if people:
        lines.append("- People in this meeting: " + ", ".join(people))
    if company:
        lines.append("- Other people at the company and regular guests: " + ", ".join(company))
    if terms:
        lines.append("- Company terms, products and projects: " + ", ".join(terms))
    if rules:
        lines.append(
            "- Known mishearings (the transcript may still contain the first spelling): "
            + "; ".join(f'"{wrong}" means "{right}"' for wrong, right in rules)
        )
    lines.append(
        "Where the transcript has a word that sounds like one of these names or terms, write the listed spelling "
        "in the title, summary, overview, tasks, owners, decisions, risks and follow-up draft. "
        "Evidence excerpts still quote the transcript exactly as it is written."
    )
    return "\n".join(lines)


def clean_extraction(extraction: dict, rules: list[Rule]) -> dict:
    """The notes with every correction applied — the model is asked to use
    the right spellings, and this makes sure of it. Evidence excerpts are
    corrected too, matching a transcript that already was."""
    if not rules:
        return extraction
    cleaned, _ = apply_deep(extraction, rules)
    return cleaned


@dataclass
class NotesVocabulary:
    hint: str
    rules: list[Rule]
    propagation: Propagation


async def prepare_for_notes(db: AsyncSession, meeting: Meeting) -> NotesVocabulary:
    """Before (re)writing a meeting's notes: apply every current correction
    to its transcript and items — so notes regenerated after someone taught
    Charcha a name use it — and build the spelling hint for the model."""
    from app.config import settings

    vocabulary = await active_vocabulary()
    propagation = await propagate(db, meeting, vocabulary.rules, None) if vocabulary.rules else Propagation()
    people = await meeting_people(db, meeting.id)
    return NotesVocabulary(prompt_hint(people, vocabulary, settings.team_roster_list), vocabulary.rules, propagation)


# --- suggestions: learning without anyone editing ----------------------------

MAX_SUGGESTIONS_PER_MEETING = 8
# How close in time (ms) a caption must be to back up a transcript word.
CAPTION_WINDOW_MS = 4000
# Capitalised mid-sentence for reasons other than being someone's name.
_COMMON_CAPITALISED = {
    "okay", "ok", "yes", "yeah", "hello", "hi", "hey", "thanks", "thank", "sorry", "please", "sir", "madam",
    "maam", "ma'am", "ji", "bhai", "god", "google", "meet", "zoom", "teams", "slack", "whatsapp", "gmail",
    "excel", "sheets", "docs", "drive", "jira", "english", "hindi", "india", "indian", "charcha",
}
_SOUND_CODES = {
    **dict.fromkeys("bfpv", "1"), **dict.fromkeys("cgjkqsxz", "2"), **dict.fromkeys("dt", "3"),
    "l": "4", **dict.fromkeys("mn", "5"), "r": "6",
}
_POSSESSIVE = re.compile(r"['’]s$")


def sound_key(word: str) -> str:
    """A Soundex-like key where a leading vowel is any vowel and C/K/S sound
    alike, so "Archit", "Arshit" and "Orchid" share one."""
    letters = re.sub(r"[^a-z]", "", word.lower())
    if not letters:
        return ""
    head = "V" if letters[0] in "aeiouy" else _SOUND_CODES.get(letters[0], letters[0])
    codes: list[str] = []
    previous = _SOUND_CODES.get(letters[0], "")
    for char in letters[1:]:
        code = _SOUND_CODES.get(char, "")
        if code and code != previous:
            codes.append(code)
        if char not in "hw":
            previous = code
    return head + "".join(codes)


def _sounds_like(candidate: str, target: str, captioned: bool) -> float:
    """How strongly `candidate` looks like a mishearing of `target` (0: not)."""
    similarity = _similarity(candidate, target)
    if similarity >= 0.8 and min(len(candidate), len(target)) >= 5:
        return similarity
    if similarity >= 0.5 and sound_key(candidate) == sound_key(target):
        return similarity
    if captioned and similarity >= 0.4:
        return similarity
    return 0.0


@dataclass
class Suggestion:
    wrong: str
    right: str
    occurrences: int
    captions: bool


def _caption_says(captions: list[dict], start_ms: int | None, end_ms: int | None, word: str) -> bool:
    if start_ms is None or not captions:
        return False
    end_ms = end_ms if end_ms is not None else start_ms
    pattern = _pattern(word)
    for caption in captions:
        c_start = float(caption.get("start") or 0) * 1000
        c_end = float(caption.get("end") or 0) * 1000 or c_start
        if c_start - CAPTION_WINDOW_MS <= end_ms and c_end + CAPTION_WINDOW_MS >= start_ms and pattern.search(caption.get("text") or ""):
            return True
    return False


def find_suggestions(
    lines: list[tuple[str, int | None, int | None]],
    names: list[str],
    protected: set[str] | frozenset[str] = frozenset(),
    known_terms: set[str] | frozenset[str] = frozenset(),
    captions: list[dict] | None = None,
) -> list[Suggestion]:
    """Words in a transcript that are probably a misheard name of someone in
    the meeting. `lines` are (text, start_ms, end_ms); `names` the people in
    the meeting; `protected` lower-cased names of real people (never
    "misheard"); `known_terms` lower-cased words already in the vocabulary.

    A candidate is a capitalised word mid-sentence (a proper noun to the
    transcriber) that never appears in lower case in the meeting, isn't
    anyone's name or a known term, and sounds like exactly one name word —
    or is close to one where Meet's captions, at the same moment, have the
    real name."""
    targets: dict[str, str] = {}
    for name in names:
        for word in _person_name(name).split():
            word = _strip(word)
            if len(word) >= 3 and _WORDLIKE.match(word):
                targets.setdefault(word.lower(), word[:1].upper() + word[1:])

    lowercase_seen: set[str] = set()
    occurrences: dict[str, list[tuple[str, int | None, int | None]]] = {}
    for text, start_ms, end_ms in lines:
        words, starts = _tokens(text)
        for index, word in enumerate(words):
            word = _POSSESSIVE.sub("", word)
            if not word:
                continue
            if not word[:1].isupper():
                lowercase_seen.add(word.lower())
                continue
            key = word.lower()
            if (
                index in starts
                or len(word) < 3
                or not _WORDLIKE.match(word)
                or (word.isupper() and len(word) <= 4)
                or key in protected
                or key in targets
                or key in known_terms
                or key in _NOT_A_MISHEARING
                or key in _COMMON_CAPITALISED
            ):
                continue
            occurrences.setdefault(key, []).append((word, start_ms, end_ms))

    found: list[Suggestion] = []
    for key, seen in occurrences.items():
        if key in lowercase_seen or not targets:
            continue
        spelling = Counter(word for word, _, _ in seen).most_common(1)[0][0]
        scored: list[tuple[float, str, bool]] = []
        for target in targets.values():
            captioned = any(_caption_says(captions or [], start, end, target) for _, start, end in seen)
            score = _sounds_like(spelling, target, captioned)
            if score:
                scored.append((score, target, captioned))
        if not scored:
            continue
        scored.sort(reverse=True)
        # Sounds like two people equally: don't guess between them.
        if len(scored) > 1 and scored[0][1] != scored[1][1] and scored[0][0] - scored[1][0] < 0.1:
            continue
        score, target, captioned = scored[0]
        found.append(Suggestion(spelling, target, len(seen), captioned))
    found.sort(key=lambda item: (-item.captions, -item.occurrences, item.wrong))
    return found[:MAX_SUGGESTIONS_PER_MEETING]


def _transcript_lines(meeting: Meeting, segments: list) -> list[tuple[str, int | None, int | None]]:
    if segments:
        return [(segment.text or "", segment.start_ms, segment.end_ms) for segment in segments]
    lines = []
    for line in (meeting.transcript or "").splitlines():
        # "Speaker: text" — the label is a name, not something said.
        lines.append((line.split(":", 1)[1] if ":" in line[:60] else line, None, None))
    return lines


async def _meeting_captions(db: AsyncSession, meeting_id: uuid.UUID) -> list[dict]:
    """Meet's captions for a notetaker meeting (stored with its recording)."""
    import json

    from app.routes.recordings import _session_dir

    recording_ids = (await db.execute(
        select(RecordingSession.id).where(RecordingSession.meeting_id == meeting_id).order_by(RecordingSession.started_at.desc())
    )).scalars().all()
    for recording_id in recording_ids:
        path = _session_dir(recording_id) / "captions.json"
        if path.exists():
            try:
                captions = json.loads(path.read_text(encoding="utf-8"))
                return captions if isinstance(captions, list) else []
            except (OSError, ValueError):
                return []
    return []


def auto_apply_threshold(captions: bool) -> int | None:
    """Meetings a suggestion must be heard in before Charcha applies it."""
    from app.config import settings

    needed = settings.vocabulary_auto_apply_meetings
    if needed <= 0:
        return None
    return max(2, needed - 1) if captions else needed


async def suggest_for_meeting(db: AsyncSession, meeting_id: uuid.UUID) -> list[Rule]:
    """Record suggestions from one meeting; returns the ones now heard often
    enough to apply (already saved as corrections, not yet applied)."""
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None or meeting.deleted_at is not None:
        return []
    segments = await transcript_service.load_segments(db, meeting_id)
    captions = await _meeting_captions(db, meeting_id)
    caption_speakers = [caption.get("speaker") or "" for caption in captions]
    names = _unique([*await meeting_people(db, meeting_id), *caption_speakers])
    if not names:
        return []
    protected = await protected_names(db, meeting_id) | _name_keys(caption_speakers)
    known_terms: set[str] = set()
    for wrong, right in (await db.execute(select(TermCorrection.wrong, TermCorrection.right))).all():
        known_terms.add(right.lower())
        if wrong:
            known_terms.add(wrong.lower())
    found = find_suggestions(_transcript_lines(meeting, segments), names, protected, known_terms, captions)

    now = datetime.datetime.now(datetime.UTC)
    promoted: list[Rule] = []
    for item in found:
        row = (await db.execute(
            select(TermSuggestion).where(
                func.lower(TermSuggestion.wrong) == item.wrong.lower(), func.lower(TermSuggestion.right) == item.right.lower()
            )
        )).scalar_one_or_none()
        if row is None:
            row = TermSuggestion(wrong=item.wrong, right=item.right, occurrences=0, meeting_ids=[])
            db.add(row)
        elif row.status != "pending":
            continue  # decided already: dismissed stays dismissed
        if str(meeting_id) not in row.meeting_ids:
            row.meeting_ids = [*row.meeting_ids, str(meeting_id)]
            row.occurrences = (row.occurrences or 0) + item.occurrences
        if item.captions:
            row.reason = "captions"
        row.last_meeting_id = meeting_id
        needed = auto_apply_threshold(row.reason == "captions")
        if needed is not None and len(row.meeting_ids) >= needed:
            taken = (await db.execute(
                select(TermCorrection.id).where(func.lower(TermCorrection.wrong) == item.wrong.lower())
            )).first()
            row.status = "auto"
            row.decided_at = now
            if taken is None:
                db.add(TermCorrection(
                    wrong=row.wrong, right=row.right, source="suggested", source_meeting_id=meeting_id,
                    note=f"Applied after being heard in {len(row.meeting_ids)} meetings",
                ))
                promoted.append((row.wrong, row.right))
    await db.flush()
    if found:
        logger.info("Vocabulary suggestions from meeting %s: %s", meeting_id, [(s.wrong, s.right) for s in found])
    return promoted


async def learn_from_meeting(meeting_id: uuid.UUID) -> None:
    """After a meeting's notes are ready: suggest corrections from it, apply
    the ones heard in enough meetings, and refresh the automatic keywords.
    Never fails the caller."""
    from app.database.db import async_session

    try:
        async with async_session() as db:
            promoted = await suggest_for_meeting(db, meeting_id)
            rows = []
            if promoted:
                rows = (await db.execute(
                    select(TermSuggestion.meeting_ids).where(
                        TermSuggestion.status == "auto",
                        func.lower(TermSuggestion.wrong).in_([wrong.lower() for wrong, _ in promoted]),
                    )
                )).scalars().all()
            await db.commit()
        if promoted:
            meeting_ids = list({uuid.UUID(value) for ids in rows for value in ids})
            await fix_past_meetings(promoted, None, meeting_ids)
    except Exception:
        logger.exception("Learning vocabulary from meeting %s failed", meeting_id)
    try:
        await refresh_auto_keywords()
    except Exception:
        logger.exception("Refreshing automatic vocabulary keywords failed")


async def accept_suggestion(db: AsyncSession, suggestion: TermSuggestion, user: User) -> TermCorrection:
    now = datetime.datetime.now(datetime.UTC)
    entry = (await db.execute(
        select(TermCorrection).where(func.lower(TermCorrection.wrong) == suggestion.wrong.lower())
    )).scalar_one_or_none()
    if entry is None:
        entry = TermCorrection(
            wrong=suggestion.wrong, right=suggestion.right, source="suggested", created_by=user.id,
            source_meeting_id=suggestion.last_meeting_id, note=f"Suggested by Charcha, confirmed by {user.name or user.email}",
        )
        db.add(entry)
    elif entry.source != "manual":
        entry.right = suggestion.right
    entry.disabled_at = None
    suggestion.status = "accepted"
    suggestion.decided_by = user.id
    suggestion.decided_at = now
    # One right spelling per misheard word: other guesses for it are moot.
    await db.execute(
        update(TermSuggestion)
        .where(
            func.lower(TermSuggestion.wrong) == suggestion.wrong.lower(),
            TermSuggestion.id != suggestion.id,
            TermSuggestion.status == "pending",
        )
        .values(status="dismissed", decided_by=user.id, decided_at=now)
    )
    await db.flush()
    return entry


# --- keywords picked up automatically -----------------------------------------

AUTO_REFRESH_SECONDS = 3600
MAX_AUTO_KEYWORDS = 30
MAX_TITLE_KEYWORDS = 15
_auto_refreshed_at: float = 0.0
# Words in meeting titles that say what kind of meeting it is, not who or what about.
_TITLE_STOPWORDS = {
    "meeting", "meetings", "sync", "syncup", "weekly", "daily", "monthly", "quarterly", "annual", "standup",
    "stand", "review", "reviews", "call", "calls", "catch", "catchup", "discussion", "demo", "planning", "plan",
    "update", "updates", "team", "kickoff", "kick", "intro", "introduction", "interview", "onboarding", "session",
    "check", "checkin", "connect", "project", "product", "sprint", "retro", "retrospective", "notes", "agenda",
    "the", "and", "for", "with", "new", "one", "all", "hands", "follow", "followup", "sales", "marketing",
    "design", "engineering", "tech", "finance", "ops", "operations", "strategy", "roadmap", "brainstorm",
    "workshop", "training", "internal", "external", "client", "customer", "test", "testing", "untitled",
    "google", "meet", "manually", "added", "tasks", "task", "discuss", "about", "regarding", "status", "weekly",
    "morning", "evening", "lunch", "quick", "chat", "touch", "base", "board", "leadership", "office", "hours",
    *_NOT_A_MISHEARING,
}


def title_keywords(titles: list[str]) -> list[str]:
    """Capitalised words that recur across meeting titles — client, product
    and series names ("Acme weekly", "Acme pricing")."""
    seen_in: Counter = Counter()
    spelling: dict[str, str] = {}
    lowercase: set[str] = set()
    for title in titles:
        words = {_strip(word) for word in (title or "").replace("/", " ").replace("|", " ").split()}
        for word in words:
            if not word or not _WORDLIKE.match(word) or len(word) < 3 or any(char.isdigit() for char in word):
                continue
            key = word.lower()
            if not word[:1].isupper():
                lowercase.add(key)
                continue
            if key in _TITLE_STOPWORDS:
                continue
            seen_in[key] += 1
            spelling.setdefault(key, word)
    keywords = [spelling[key] for key, count in seen_in.most_common() if count >= 2 and key not in lowercase]
    return keywords[:MAX_TITLE_KEYWORDS]


async def _derived_keywords(db: AsyncSession) -> dict[str, str]:
    """{term: where it came from}: Charcha projects, Jira projects, and words
    recurring in the last 90 days' meeting titles."""
    from app.services import jira_service

    derived: dict[str, str] = {}
    for name in (await db.execute(select(Project.name).where(Project.deleted_at.is_(None)))).scalars().all():
        name = " ".join((name or "").split())
        if name and len(name) <= 40 and len(name.split()) <= 3:
            derived.setdefault(name, "Project")
    connection = await jira_service.get_connection(db)
    if connection is not None:
        try:
            for project in await asyncio.wait_for(jira_service.list_projects(db, connection), 15):
                name = " ".join((project.get("name") or "").split())
                if name and len(name) <= 40 and len(name.split()) <= 3:
                    derived.setdefault(name, "Jira project")
        except Exception:
            logger.info("Jira projects unavailable for vocabulary keywords", exc_info=True)
    since = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=90)
    titles = (await db.execute(
        select(Meeting.title).where(Meeting.deleted_at.is_(None), Meeting.confidential.is_(False), Meeting.date >= since).order_by(Meeting.date.desc()).limit(500)
    )).scalars().all()
    for word in title_keywords(list(titles)):
        derived.setdefault(word, "Meeting titles")
    return derived


async def refresh_auto_keywords(force: bool = False) -> None:
    """Keep the automatic keywords in step with projects, Jira and meeting
    titles: add new ones, drop ones no longer derived. One switched off by
    someone stays (switched off) so it doesn't come back on."""
    import time

    from app.database.db import async_session

    global _auto_refreshed_at
    if not force and time.monotonic() - _auto_refreshed_at < AUTO_REFRESH_SECONDS:
        return
    _auto_refreshed_at = time.monotonic()
    async with async_session() as db:
        derived = await _derived_keywords(db)
        people = {name.lower() for name in await team_names(db)} | await protected_names(db)
        entries = (await db.execute(select(TermCorrection))).scalars().all()
        taken = {entry.right.lower() for entry in entries if entry.source != "auto"} | {
            entry.wrong.lower() for entry in entries if entry.wrong
        }
        auto = {entry.right.lower(): entry for entry in entries if entry.source == "auto" and entry.wrong is None}
        wanted = {
            term.lower(): (term, note) for term, note in derived.items()
            if term.lower() not in taken and term.lower() not in people
        }
        wanted = dict(list(wanted.items())[:MAX_AUTO_KEYWORDS])
        for key, entry in auto.items():
            if key not in wanted and entry.disabled_at is None:
                await db.delete(entry)
        for key, (term, note) in wanted.items():
            if key in auto:
                auto[key].note = note
            else:
                db.add(TermCorrection(right=term, source="auto", note=note))
        await db.commit()
