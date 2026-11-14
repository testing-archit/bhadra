"""Put Hindi script left in saved notes into English: task due-date phrases
("आज शाम तक"), task owners and stand-up people ("सार्थक" → Sarthak), and the
same in calendar briefs. Before prompt 2026-10-grounded-3 the extractor copied
them from the transcript as spoken. Transcripts and evidence quotes are left
alone — they are verbatim speech.

Idempotent — English text is left alone.

    python scripts/english_task_deadlines.py [--dry-run]
"""

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.database.db import async_session
from app.database.models import CalendarEvent, MeetingInsight, MeetingTask, User
from app.services.due_phrase import english_due_phrase
from app.services.insight_service import resolve_owner_user_id
from app.services.latin_names import DEVANAGARI, latin_name

HINDI = "[ऀ-ॿ]"


def _brief_text(text: str, people: list[str]) -> str:
    # "Sarthak (सार्थक)" → "Sarthak"; "सार्थक (Sarthak)" → "Sarthak".
    text = re.sub(rf"\s*\([^)]*{HINDI}[^)]*\)", "", text)
    text = re.sub(rf"{HINDI}+\s*\(([^)]+)\)", r"\1", text)
    return re.sub(rf"{HINDI}+", lambda m: latin_name(m.group(0), people) or "", text)


async def main(dry_run: bool) -> None:
    async with async_session() as db:
        people = [n for n in (await db.execute(select(User.name).where(User.status == "active"))).scalars() if n]

        tasks = (await db.execute(
            select(MeetingTask).where(MeetingTask.deadline.op("~")(HINDI) | MeetingTask.owner.op("~")(HINDI))
        )).scalars().all()
        for task in tasks:
            deadline = english_due_phrase(task.deadline, task.due_date)
            owner = latin_name(task.owner, people)
            print(f"task {task.id}: {task.deadline!r} -> {deadline!r}, {task.owner!r} -> {owner!r}")
            task.deadline = deadline
            if owner != task.owner:
                task.owner = owner
                task.owner_user_id = task.owner_user_id or await resolve_owner_user_id(db, task.meeting_id, owner)

        insights = (await db.execute(
            select(MeetingInsight).where(MeetingInsight.template_sections.isnot(None))
        )).scalars().all()
        fixed_insights = 0
        for insight in insights:
            dirty = False
            for block in insight.template_sections or []:
                for item in block.get("items") or []:
                    if DEVANAGARI.search(item.get("person") or ""):
                        print(f"insight {insight.meeting_id}: person {item['person']!r} -> {latin_name(item['person'], people)!r}")
                        item["person"], dirty = latin_name(item["person"], people), True
            if dirty:
                flag_modified(insight, "template_sections")
                fixed_insights += 1

        events = (await db.execute(select(CalendarEvent).where(CalendarEvent.brief.isnot(None)))).scalars().all()
        fixed_briefs = 0
        for event in events:
            brief, dirty = event.brief or {}, False
            for item in brief.get("open_tasks") or []:
                for key, fix in (("deadline", english_due_phrase), ("owner", lambda v: latin_name(v, people))):
                    if item.get(key) and fix(item[key]) != item[key]:
                        item[key], dirty = fix(item[key]), True
            if DEVANAGARI.search(brief.get("text") or ""):
                brief["text"], dirty = _brief_text(brief["text"], people), True
            if dirty:
                flag_modified(event, "brief")
                fixed_briefs += 1

        print(f"{len(tasks)} tasks, {fixed_insights} meeting notes, {fixed_briefs} briefs")
        if dry_run:
            await db.rollback()
        else:
            await db.commit()


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))
