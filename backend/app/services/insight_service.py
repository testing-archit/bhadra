"""Grounded AI notes: validating evidence, storing extracted items, and
regenerating insights without overwriting what people already reviewed.

Evidence validation is mechanical and deliberately strict: a cited segment
must exist, and the quoted excerpt must actually appear in it (or in an
immediate neighbour, since models are sometimes off by one line). Passing
that check proves the quote is real, not that it supports the claim — which
is why every item still carries a review state in the UI.
"""

import asyncio
import datetime
import logging
import re
import uuid

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Decision,
    InsightRun,
    Meeting,
    MeetingAttendee,
    MeetingInsight,
    MeetingTask,
    Project,
    Risk,
    TaskComment,
    Trace,
    TranscriptSegment,
    User,
    meeting_projects,
)
from app.services import ai_extractor, privacy_service, processing_service, transcript_service, vocabulary_service
from app.services.latin_names import DEVANAGARI, latin_name

logger = logging.getLogger(__name__)
MAX_REFS_PER_ITEM = 3
MAX_EXCERPT_CHARS = 300


# --- evidence ----------------------------------------------------------------


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (text or "").lower())).strip()


def _ref(segment: TranscriptSegment, excerpt: str, verified: bool) -> dict:
    return {
        "segment_id": str(segment.id),
        "seq": segment.seq,
        "start_ms": segment.start_ms,
        "end_ms": segment.end_ms,
        "speaker": transcript_service.display_label(segment),
        "excerpt": (excerpt if verified else segment.text)[:MAX_EXCERPT_CHARS],
        "verified": verified,
    }


def validate_evidence(refs: list[dict], by_seq: dict[int, TranscriptSegment]) -> tuple[list[dict], list[str], int]:
    """(validated refs, review flags, rejected count) for one item."""
    validated: list[dict] = []
    rejected = 0
    seen: set[int] = set()
    for raw in (refs or [])[:MAX_REFS_PER_ITEM]:
        try:
            seq = int(raw.get("segment"))
        except (TypeError, ValueError):
            rejected += 1
            continue
        segment = by_seq.get(seq)
        if segment is None:
            rejected += 1
            continue
        excerpt = (raw.get("excerpt") or "").strip()
        needle = _norm(excerpt)
        match = None
        if needle:
            for candidate_seq in (seq, seq - 1, seq + 1):
                candidate = by_seq.get(candidate_seq)
                if candidate is not None and needle in _norm(candidate.text):
                    match = candidate
                    break
        if match is not None and match.seq not in seen:
            seen.add(match.seq)
            validated.append(_ref(match, excerpt, True))
        elif match is None and seq not in seen:
            seen.add(seq)
            validated.append(_ref(segment, excerpt, False))
    flags: list[str] = []
    if not validated:
        flags.append("evidence_missing")
    elif not any(ref["verified"] for ref in validated):
        flags.append("evidence_unverified")
    return validated, flags, rejected


def _best_segment(excerpt: str, segments: list[TranscriptSegment]) -> tuple[TranscriptSegment | None, bool]:
    needle = _norm(excerpt)
    if not needle:
        return None, False
    for segment in segments:
        if needle in _norm(segment.text):
            return segment, True
    words = set(needle.split())
    best, best_score = None, 0.0
    for segment in segments:
        overlap = len(words & set(_norm(segment.text).split())) / max(1, len(words))
        if overlap > best_score:
            best, best_score = segment, overlap
    return (best, False) if best_score >= 0.6 else (None, False)


async def reanchor_evidence(db: AsyncSession, meeting_id: uuid.UUID, segments: list[TranscriptSegment]) -> None:
    """After segments are rebuilt (a re-transcription), point each item's
    evidence at the new segment holding the same quote. Quotes that no longer
    match exactly are kept but marked unverified for review."""
    for model in (MeetingTask, Decision, Risk):
        items = (await db.execute(select(model).where(model.meeting_id == meeting_id))).scalars().all()
        for item in items:
            if not item.evidence:
                continue
            refs = []
            for ref in item.evidence:
                segment, exact = _best_segment(ref.get("excerpt") or "", segments)
                if segment is not None:
                    refs.append(_ref(segment, ref.get("excerpt") or "", exact and ref.get("verified", False)))
            flags = [f for f in (item.ai_flags or []) if f not in {"evidence_missing", "evidence_unverified"}]
            if not refs:
                flags.append("evidence_missing")
            elif not any(r["verified"] for r in refs):
                flags.append("evidence_unverified")
            item.evidence = refs
            item.ai_flags = flags
    await db.flush()


def _validated_list(items: list[dict], by_seq: dict) -> tuple[list[dict], int, int]:
    """Validates evidence for plain {text/title, evidence} objects (sections,
    template items) in place. Returns (items, checked, rejected)."""
    checked = rejected = 0
    out = []
    for item in items or []:
        refs, flags, dropped = validate_evidence(item.get("evidence") or [], by_seq)
        checked += len(item.get("evidence") or [])
        rejected += dropped
        out.append({**item, "evidence": refs, "flags": flags})
    return out, checked, rejected


# --- persistence -------------------------------------------------------------


async def resolve_project(
    db: AsyncSession, name: str | None, department: str | None, cache: dict[str, Project]
) -> Project | None:
    """Get-or-create a project by exact case-insensitive name. The per-call
    cache keeps one meeting's repeated mentions to a single round trip."""
    if not name or not name.strip():
        return None
    key = name.strip().lower()
    if key in cache:
        return cache[key]
    result = await db.execute(select(Project).where(func.lower(Project.name) == key))
    project = result.scalar_one_or_none()
    if project is not None and project.deleted_at is not None:
        return None
    if project is None:
        project = Project(name=name.strip(), department=department)
        db.add(project)
        await db.flush()
    cache[key] = project
    return project


async def resolve_owner_user_id(db: AsyncSession, meeting_id: uuid.UUID, owner: str | None) -> uuid.UUID | None:
    """The account a task's stated owner refers to: one of the meeting's
    internal attendees (full name, or a first name no other attendee has),
    else exactly one active account with that full name or email. Ambiguous
    or unknown names resolve to nobody — never keep a stale account."""
    key = (owner or "").strip().lower()
    if not key:
        return None
    found = (await _owner_resolver(db, meeting_id))(key)
    if found is not None:
        return found
    ids = (await db.execute(
        select(User.id).where(
            User.status == "active",
            or_(func.lower(func.trim(User.name)) == key, func.lower(User.email) == key),
        ).limit(2)
    )).scalars().all()
    return ids[0] if len(ids) == 1 else None


async def _owner_resolver(db: AsyncSession, meeting_id: uuid.UUID):
    """Map a stated owner name to a user id — only among this meeting's
    internal attendees, by full name or a first name no other attendee
    shares. A name shared by two attendees resolves to nobody."""
    rows = (
        await db.execute(
            select(MeetingAttendee.user_id, User.name, MeetingAttendee.display_name)
            .join(User, User.id == MeetingAttendee.user_id)
            .where(MeetingAttendee.meeting_id == meeting_id, MeetingAttendee.user_id.is_not(None))
        )
    ).all()
    full: dict[str, set] = {}
    first: dict[str, set] = {}
    for user_id, user_name, display_name in rows:
        for name in {user_name or "", display_name or ""}:
            name = name.strip().lower()
            if not name:
                continue
            full.setdefault(name, set()).add(user_id)
            first.setdefault(name.split()[0], set()).add(user_id)

    def resolve(owner: str | None) -> uuid.UUID | None:
        key = (owner or "").strip().lower()
        if not key:
            return None
        for table in (full, first if " " not in key else {}):
            ids = table.get(key)
            if ids and len(ids) == 1:
                return next(iter(ids))
        return None

    return resolve


def _parse_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


async def _latin_people(db: AsyncSession, meeting: Meeting, extraction: dict) -> None:
    """Task owners and stand-up people in Latin script, spelled like the
    teammate they name — the transcript may have them in Devanagari."""
    items = list(extraction.get("tasks") or []) + [
        item for block in extraction.get("template_sections") or [] for item in block.get("items") or []
    ]
    if not any(DEVANAGARI.search(item.get("assignedTo") or item.get("person") or "") for item in items):
        return
    people = await vocabulary_service.meeting_people(db, meeting.id)
    people += [name for name in (await db.execute(select(User.name).where(User.status == "active"))).scalars() if name]
    for item in items:
        for key in ("assignedTo", "person"):
            if item.get(key):
                item[key] = latin_name(item[key], people)


async def persist_items(
    db: AsyncSession,
    meeting: Meeting,
    extraction: dict,
    segments: list[TranscriptSegment],
    department: str | None,
    *,
    skip_descriptions: set[str] | None = None,
) -> dict:
    """Store extracted tasks/decisions/risks with validated evidence. Returns
    the created rows plus evidence-check counts for the InsightRun."""
    await _latin_people(db, meeting, extraction)
    by_seq = {segment.seq: segment for segment in segments}
    skip = skip_descriptions or set()
    resolve_owner = await _owner_resolver(db, meeting.id)
    project_cache: dict[str, Project] = {}
    projects: dict[uuid.UUID, Project] = {}
    checked = rejected = 0
    tasks, decisions, risks = [], [], []

    async def project_for(item: dict) -> Project | None:
        project = await resolve_project(db, item.get("project"), department, project_cache)
        if project is not None:
            projects[project.id] = project
        return project

    def grounding(item: dict) -> tuple[list[dict] | None, list[str]]:
        nonlocal checked, rejected
        if not segments:
            return None, []
        refs, flags, dropped = validate_evidence(item.get("evidence") or [], by_seq)
        checked += len(item.get("evidence") or [])
        rejected += dropped
        return refs, flags

    for item in extraction.get("tasks") or []:
        if _norm(item.get("task", "")) in skip:
            continue
        project = await project_for(item)
        refs, flags = grounding(item)
        if item.get("dueDateAmbiguous"):
            flags.append("due_date_ambiguous")
        task = MeetingTask(
            meeting_id=meeting.id,
            project_id=project.id if project else None,
            owner=item.get("assignedTo") or None,
            owner_user_id=resolve_owner(item.get("assignedTo")),
            description=item["task"],
            deadline=item.get("dueDate") or None,
            due_date=_parse_date(item.get("resolvedDueDate")),
            priority=item.get("priority") or None,
            evidence=refs,
            ai_flags=flags or None,
            origin="ai",
        )
        db.add(task)
        tasks.append(task)

    for item in extraction.get("risks") or []:
        if _norm(item.get("risk", "")) in skip:
            continue
        project = await project_for(item)
        refs, flags = grounding(item)
        risk = Risk(
            meeting_id=meeting.id,
            project_id=project.id if project else None,
            description=item["risk"],
            severity=item.get("severity") or None,
            evidence=refs,
            ai_flags=flags or None,
            origin="ai",
        )
        db.add(risk)
        risks.append(risk)

    for item in extraction.get("decisions") or []:
        if _norm(item.get("decision", "")) in skip:
            continue
        project = await project_for(item)
        refs, flags = grounding(item)
        decision = Decision(
            meeting_id=meeting.id,
            project_id=project.id if project else None,
            decision=item["decision"],
            reason=item.get("reason"),
            alternatives=item.get("alternatives") or [],
            participants=item.get("participants") or [],
            evidence=refs,
            ai_flags=flags or None,
            origin="ai",
        )
        db.add(decision)
        decisions.append((decision, item))

    if projects:
        existing = set(
            (
                await db.execute(
                    select(meeting_projects.c.project_id).where(meeting_projects.c.meeting_id == meeting.id)
                )
            ).scalars().all()
        )
        new_links = [pid for pid in projects if pid not in existing]
        if new_links:
            await db.execute(
                meeting_projects.insert(),
                [{"meeting_id": meeting.id, "project_id": pid} for pid in new_links],
            )
    await db.flush()
    return {"tasks": tasks, "decisions": decisions, "risks": risks, "checked": checked, "rejected": rejected}


async def write_insight(
    db: AsyncSession, meeting: Meeting, extraction: dict, segments: list[TranscriptSegment]
) -> tuple[int, int]:
    await _latin_people(db, meeting, extraction)
    await privacy_service.apply_ai_flag(db, meeting, extraction)
    by_seq = {segment.seq: segment for segment in segments}
    sections, c1, r1 = _validated_list(extraction.get("sections") or [], by_seq)
    template_sections = []
    c2 = r2 = 0
    for block in extraction.get("template_sections") or []:
        items, checked, rejected = _validated_list(block.get("items") or [], by_seq)
        c2 += checked
        r2 += rejected
        if items:
            template_sections.append({"heading": block.get("heading", ""), "items": items})
    speaker_activity = extraction.get("speaker_activity") or []
    if segments:
        breakdown = transcript_service.talk_time(segments)
        speaker_activity = [
            {"speaker": row["speaker"], "words": row["words"], "seconds": row["seconds"], "share": row["share"]}
            for row in breakdown["speakers"]
        ]
    values = dict(
        key_topics=extraction.get("key_topics", []),
        open_questions=extraction.get("open_questions", []),
        highlights=extraction.get("highlights", []),
        next_steps=extraction.get("next_steps", []),
        speaker_activity=speaker_activity,
        overview=extraction.get("overview") or None,
        sections=sections if segments else None,
        template_sections=template_sections or None,
        follow_up_draft=extraction.get("follow_up_draft") or None,
    )
    insight = await db.get(MeetingInsight, meeting.id)
    if insight is None:
        db.add(MeetingInsight(meeting_id=meeting.id, **values))
    else:
        for key, value in values.items():
            setattr(insight, key, value)
    return c1 + c2, r1 + r2


def record_run(
    db: AsyncSession,
    meeting: Meeting,
    extraction: dict | None,
    *,
    status: str,
    template: str,
    user_id: uuid.UUID | None,
    error: BaseException | None = None,
    checked: int = 0,
    rejected: int = 0,
) -> None:
    extraction = extraction or {}
    db.add(
        InsightRun(
            meeting_id=meeting.id,
            transcript_revision=meeting.transcript_revision or 1,
            template=template,
            model=extraction.get("model") or "unknown",
            prompt_version=extraction.get("prompt_version") or ai_extractor.EXTRACTION_PROMPT_VERSION,
            status=status,
            error=str(error)[:500] if error else None,
            chunk_count=extraction.get("chunk_count") or 1,
            input_tokens=int(extraction.get("input_tokens", 0) or 0) + int(extraction.get("cache_tokens_read", 0) or 0),
            output_tokens=int(extraction.get("output_tokens", 0) or 0),
            evidence_checked=checked,
            evidence_rejected=rejected,
            triggered_by=user_id,
            finished_at=datetime.datetime.now(datetime.UTC),
        )
    )


# --- regeneration ------------------------------------------------------------


# A regeneration that finds nothing replaces nothing while the meeting still
# has at least this many AI items it would delete.
KEEP_NOTES_OVER_EMPTY_RESULT = 3


async def _replaceable_ids(db: AsyncSession, meeting_id: uuid.UUID) -> tuple[list, list, list, set[str]]:
    """AI items nobody has touched — and the normalized text of everything
    that must be preserved, so regeneration doesn't add a duplicate of it."""
    tasks = (await db.execute(select(MeetingTask).where(MeetingTask.meeting_id == meeting_id, MeetingTask.deleted_at.is_(None)))).scalars().all()
    decisions = (await db.execute(select(Decision).where(Decision.meeting_id == meeting_id, Decision.deleted_at.is_(None)))).scalars().all()
    risks = (await db.execute(select(Risk).where(Risk.meeting_id == meeting_id, Risk.deleted_at.is_(None)))).scalars().all()
    commented_ids: set = set()
    if tasks:
        commented_ids = set(
            (await db.execute(select(TaskComment.task_id).where(TaskComment.task_id.in_([t.id for t in tasks])))).scalars().all()
        )

    preserved: set[str] = set()
    task_ids, decision_ids, risk_ids = [], [], []
    for task in tasks:
        # A task already in Jira, or one a manager decided to send (or keep
        # from) its owner, carries a decision that a fresh copy would lose.
        decided = task.jira_issue_key or task.owner_shared_at or task.owner_kept_private_at
        if (
            task.origin == "ai" and task.verified_at is None and (task.status or "pending") == "pending"
            and task.id not in commented_ids and not decided
        ):
            task_ids.append(task.id)
        else:
            preserved.add(_norm(task.description))
    for decision in decisions:
        if decision.origin == "ai" and decision.verified_at is None:
            decision_ids.append(decision.id)
        else:
            preserved.add(_norm(decision.decision))
    for risk in risks:
        if risk.origin == "ai" and risk.verified_at is None:
            risk_ids.append(risk.id)
        else:
            preserved.add(_norm(risk.description))
    return task_ids, decision_ids, risk_ids, preserved


async def regenerate(
    db: AsyncSession,
    meeting: Meeting,
    *,
    template: str | None,
    user: User | None,
    adopt_title: bool = False,
) -> dict:
    """Regenerate a meeting's notes from its current transcript revision.

    Untouched AI suggestions are replaced. Anything a person approved,
    edited, moved off "pending", commented on, or created by hand is kept as
    is, and a human-verified summary is never overwritten.
    """
    template = ai_extractor.template_or_default(template or meeting.template)
    segments = await transcript_service.ensure_segments(db, meeting)
    if not segments and not meeting.transcript:
        raise ValueError("This meeting has no transcript to analyze")
    # Every correction the team has taught Charcha goes into the transcript
    # first, and the model is told how names and terms are spelled — so
    # notes never bring back a mishearing someone already fixed.
    notes_vocabulary = await vocabulary_service.prepare_for_notes(db, meeting)
    await db.commit()

    await processing_service.set_stage(meeting.id, "extraction", "running")
    try:
        extraction = await asyncio.to_thread(
            ai_extractor.extract_from_transcript,
            meeting.transcript or "",
            meeting.title,
            meeting.date.date(),
            segments=segments,
            template=template,
            vocabulary_hint=notes_vocabulary.hint,
        )
        extraction = vocabulary_service.clean_extraction(extraction, notes_vocabulary.rules)
    except Exception as error:
        await processing_service.set_stage(meeting.id, "extraction", "failed", error=error)
        record_run(db, meeting, None, status="failed", template=template, user_id=user.id if user else None, error=error)
        await db.commit()
        raise

    await db.refresh(meeting)
    if meeting.deleted_at is not None:
        # Tombstone: the meeting was deleted while the model was working.
        await processing_service.set_stage(meeting.id, "extraction", "skipped", error="Meeting was deleted")
        return {"status": "skipped"}

    task_ids, decision_ids, risk_ids, preserved = await _replaceable_ids(db, meeting.id)
    found = sum(len(extraction.get(key) or []) for key in ("tasks", "decisions", "risks", "template_sections"))
    if found == 0 and len(task_ids) + len(decision_ids) + len(risk_ids) >= KEEP_NOTES_OVER_EMPTY_RESULT:
        # A degenerate model reply (production, 2026-10-10: 407 tokens, no
        # items) must not erase good notes: keep them and say so.
        error = ValueError("The new notes came back empty, so the existing notes were kept. Try again.")
        await processing_service.set_stage(meeting.id, "extraction", "failed", error=error)
        record_run(db, meeting, extraction, status="failed", template=template, user_id=user.id if user else None, error=error)
        await db.commit()
        raise error
    if task_ids:
        await db.execute(delete(MeetingTask).where(MeetingTask.id.in_(task_ids)))
    if decision_ids:
        await db.execute(delete(Decision).where(Decision.id.in_(decision_ids)))
    if risk_ids:
        await db.execute(delete(Risk).where(Risk.id.in_(risk_ids)))

    created = await persist_items(db, meeting, extraction, segments, meeting.department, skip_descriptions=preserved)
    checked, rejected = await write_insight(db, meeting, extraction, segments)
    checked += created["checked"]
    rejected += created["rejected"]
    if not meeting.summary_verified_at and (extraction.get("summary") or "").strip():
        meeting.summary = extraction["summary"].strip()
    if adopt_title and (extraction.get("title") or "").strip():
        meeting.title = extraction["title"].strip()[:160]
    meeting.template = template
    meeting.insights_revision = meeting.transcript_revision
    record_run(db, meeting, extraction, status="succeeded", template=template, user_id=user.id if user else None, checked=checked, rejected=rejected)
    db.add(
        Trace(
            user_id=user.id if user else meeting.user_id,
            meeting_id=meeting.id,
            meeting_title=meeting.title,
            duration_minutes=meeting.duration_minutes,
            transcription_requests=0,
            ai_input_tokens=int(extraction.get("input_tokens", 0)) + int(extraction.get("cache_tokens_read", 0)),
            ai_output_tokens=int(extraction.get("output_tokens", 0)),
            ai_cache_hits=int(extraction.get("cache_tokens_read", 0)),
            tasks_found=len(created["tasks"]),
            decisions_found=len(created["decisions"]),
            status="success",
        )
    )
    await db.commit()
    await processing_service.set_stage(
        meeting.id,
        "extraction",
        "succeeded",
        detail={"template": template, "transcript_revision": meeting.transcript_revision, "evidence_checked": checked, "evidence_rejected": rejected},
    )
    if notes_vocabulary.propagation.jira_task_ids:
        from app.services import jira_service

        for task_id in notes_vocabulary.propagation.jira_task_ids:
            await jira_service.push_changes(task_id, {"description", "owner"})
    return {
        "status": "succeeded",
        "template": template,
        "tasks_added": len(created["tasks"]),
        "decisions_added": len(created["decisions"]),
        "risks_added": len(created["risks"]),
        "preserved_items": len(preserved),
        "evidence_checked": checked,
        "evidence_rejected": rejected,
    }
