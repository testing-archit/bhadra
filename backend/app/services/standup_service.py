"""Stand-up digest: a recurring stand-up read per person, not per meeting.

For the last few occurrences of a stand-up series that the reader can open,
each person's updates, blockers and plans come from the occurrence's
template_sections ("Updates" / "Blockers" / "Plans"). Who said an item is
the item's `person` (set by the extractor since prompt 2026-10-grounded-2),
else a leading "Name:" in its text, else "Not attributed".

Blockers raised in two or more occurrences are flagged as repeated. Matching
is deterministic word overlap, not an AI call: the same blocker is usually
re-worded each day ("waiting on Acme's SSO metadata" / "still blocked on SSO
metadata from Acme"), and a free, repeatable check is worth more here than a
paid one that can differ between page loads.
"""

import difflib
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Meeting, MeetingInsight, User
from app.dependencies import meeting_visibility_clause

OCCURRENCES = 5
SECTIONS = {
    "updates": re.compile(r"\b(update|progress|done)", re.I),
    "blockers": re.compile(r"\b(blocker|blocked|impediment)", re.I),
    "plans": re.compile(r"\b(plan|next|today)", re.I),
}
UNATTRIBUTED = "Not attributed"

_PREFIX = re.compile(r"^\s*([A-Z][\w.'’-]*(?:\s+[A-Z][\w.'’-]*){0,3})\s*[:—–]\s+(.+)$", re.DOTALL)
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "was", "are", "has", "have", "had", "not", "but", "still",
    "on", "of", "to", "in", "is", "it", "be", "by", "an", "at", "as", "or", "we", "our", "their", "they", "them",
    "waiting", "blocked", "blocker", "stuck", "until", "yet", "again", "now", "some", "any", "get", "got", "need",
    "needs", "needed", "will", "would", "can", "cannot", "can't", "because", "due",
}


def _section_key(heading: str) -> str | None:
    for key, pattern in SECTIONS.items():
        if pattern.search(heading or ""):
            return key
    return None


def split_person(item: dict) -> tuple[str, str]:
    """(person, text) for one template item."""
    text = (item.get("text") or "").strip()
    person = (item.get("person") or "").strip()
    match = _PREFIX.match(text)
    if match and (not person or match.group(1).lower() == person.lower()):
        person = person or match.group(1)
        text = match.group(2).strip()
    return person or UNATTRIBUTED, text


def _canonical_names(names: set[str]) -> dict[str, str]:
    """Map each spoken name to the person it belongs to: "Priya" joins
    "Priya Sharma" when exactly one full name starts with it."""
    full = [n for n in names if " " in n]
    mapping = {}
    for name in names:
        if name == UNATTRIBUTED or " " in name:
            mapping[name] = name
            continue
        matches = [f for f in full if f.split()[0].lower() == name.lower()]
        mapping[name] = matches[0] if len(matches) == 1 else name
    return mapping


def _words(text: str) -> set[str]:
    return {w.rstrip("s") for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOP}


def same_blocker(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    if wa and wb:
        overlap = len(wa & wb)
        if overlap / len(wa | wb) >= 0.5 or (overlap >= 2 and overlap / min(len(wa), len(wb)) >= 0.75):
            return True
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.75


async def digest(db: AsyncSession, user: User, meeting: Meeting) -> dict | None:
    """None when this meeting isn't part of a stand-up series."""
    if not meeting.series_key:
        return None
    occurrences = (
        await db.execute(
            select(Meeting)
            .where(
                Meeting.series_key == meeting.series_key,
                Meeting.deleted_at.is_(None),
                Meeting.date <= meeting.date,
                Meeting.template == "standup",
                meeting_visibility_clause(user),
            )
            .order_by(Meeting.date.desc())
            .limit(OCCURRENCES)
        )
    ).scalars().all()
    if meeting.template != "standup" and not occurrences:
        return None
    occurrences = list(reversed(occurrences))  # oldest first, like a timeline
    insights = {
        i.meeting_id: i
        for i in (
            await db.execute(select(MeetingInsight).where(MeetingInsight.meeting_id.in_([m.id for m in occurrences])))
        ).scalars().all()
    } if occurrences else {}

    raw: list[tuple[Meeting, str, str, str]] = []  # (meeting, section, person, text)
    for occurrence in occurrences:
        insight = insights.get(occurrence.id)
        for block in (insight.template_sections if insight else None) or []:
            key = _section_key(block.get("heading", ""))
            if key is None:
                continue
            for item in block.get("items") or []:
                person, text = split_person(item)
                if text:
                    raw.append((occurrence, key, person, text))
    names = _canonical_names({person for _, _, person, _ in raw})

    people: dict[str, dict] = {}
    for occurrence, key, person, text in raw:
        name = names[person]
        entry = people.setdefault(name, {"name": name, "occurrences": {}})
        slot = entry["occurrences"].setdefault(
            str(occurrence.id), {"meeting_id": str(occurrence.id), "date": occurrence.date.isoformat(), "updates": [], "blockers": [], "plans": []}
        )
        slot[key].append(text)

    # Repeated blockers: cluster each person's blockers across occurrences.
    repeated = []
    for name, entry in people.items():
        blockers = [
            (slot["meeting_id"], slot["date"], text)
            for slot in entry["occurrences"].values()
            for text in slot["blockers"]
        ]
        clusters: list[list[tuple[str, str, str]]] = []
        for blocker in blockers:
            home = next((c for c in clusters if any(same_blocker(blocker[2], other[2]) for other in c)), None)
            if home is None:
                clusters.append([blocker])
            else:
                home.append(blocker)
        for cluster in clusters:
            meetings = sorted({(date, mid) for mid, date, _ in cluster})
            if len(meetings) >= 2:
                repeated.append(
                    {
                        "person": name,
                        "text": max(cluster, key=lambda b: b[1])[2],  # latest wording
                        "times": len(meetings),
                        "first_date": meetings[0][0],
                        "last_date": meetings[-1][0],
                        "meeting_ids": [mid for _, mid in meetings],
                    }
                )
    repeated.sort(key=lambda r: (-r["times"], r["person"].lower()))

    ordered = sorted(people.values(), key=lambda p: (p["name"] == UNATTRIBUTED, p["name"].lower()))
    return {
        "spoken_text": spoken_text(meeting, insights.get(meeting.id)),
        "occurrences": [{"id": str(m.id), "title": m.title, "date": m.date.isoformat(), "current": m.id == meeting.id} for m in occurrences],
        "people": [
            {
                "name": p["name"],
                "occurrences": sorted(p["occurrences"].values(), key=lambda s: s["date"]),
                "blocker_count": sum(len(s["blockers"]) for s in p["occurrences"].values()),
            }
            for p in ordered
        ],
        "repeated_blockers": repeated,
    }


def spoken_text(meeting: Meeting, insight: MeetingInsight | None) -> str:
    """Read the selected occurrence, never stale plans from an older stand-up."""
    lines = [f"{meeting.title}, {meeting.date.strftime('%d %B %Y')}."]
    labels = {"updates": "Updates", "blockers": "Blockers", "plans": "Plans stated in this stand-up"}
    for block in (insight.template_sections if insight else None) or []:
        key = _section_key(block.get("heading", ""))
        if key is None:
            continue
        for item in block.get("items") or []:
            person, value = split_person(item)
            if value:
                lines.append(f"{labels[key]}. {person}: {value}.")
    if len(lines) == 1:
        lines.append(meeting.summary or "No updates, blockers or plans were captured for this stand-up.")
    return " ".join(lines)[:6000]
