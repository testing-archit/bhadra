"""Seed synthetic demo data: Hinglish meetings with tasks, decisions and risks.

Everything here is invented for demos. Meetings are owned by the first email
and shared (granted attendee rows) with every email given, so all of them
see the same workspace. Accounts must already exist (sign up first).

    python scripts/seed_demo.py owner@example.com teammate@example.com
    python scripts/seed_demo.py --reset owner@example.com ...   # replace
    python scripts/seed_demo.py --reset --existing   # rebuild for whoever has it

Re-running without --reset does nothing if the demo is already there.
"""
import asyncio
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, func, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.db import async_session  # noqa: E402
from app.services.demo_seed import MEETINGS, SEED_PREFIX, _decision, seed_workspace  # noqa: E402
from app.database.models import (  # noqa: E402
    Decision,
    Meeting,
    MeetingAttendee,
    MeetingTask,
    Project,
    Risk,
    User,
)


async def main(emails: list[str], reset: bool) -> None:
    async with async_session() as db:
        users = []
        for email in emails:
            user = await db.scalar(select(User).where(func.lower(User.email) == email.lower()))
            if user is None:
                sys.exit(f"No account for {email}. Sign up first, then re-run.")
            users.append(user)
        owner, mate = users[0], users[1] if len(users) > 1 else users[0]

        # Only this owner's demo: guests of the no-sign-up demo have their own copies.
        existing = (await db.scalars(select(Meeting).where(Meeting.client_meeting_id.like(f"{SEED_PREFIX}%"),
                                                           Meeting.user_id == owner.id))).all()
        if existing and not reset:
            # Top up: add demo decisions missing from the seeded meetings,
            # leaving everything people have changed untouched.
            added = 0
            for meeting in existing:
                spec = MEETINGS[int(meeting.client_meeting_id.removeprefix(SEED_PREFIX))]
                have = set((await db.scalars(select(Decision.decision).where(Decision.meeting_id == meeting.id))).all())
                project_id = await db.scalar(select(Project.id).where(Project.name == spec["project"]))
                speakers = {line.split(":", 1)[0].split(" (")[0] for line in spec["transcript"].splitlines()}
                for entry in spec["decisions"]:
                    if entry[0] not in have:
                        db.add(_decision(meeting.id, project_id, entry, speakers))
                        added += 1
            await db.commit()
            print(f"Demo data already present ({len(existing)} meetings); added {added} missing decisions.")
            skip = {int(m.client_meeting_id.removeprefix(SEED_PREFIX)) for m in existing}
            if len(skip) >= len(MEETINGS):
                print("Every demo meeting is present. Use --reset to rebuild it all.")
                return
        else:
            skip = set()
        if existing and reset:
            await db.execute(delete(Meeting).where(Meeting.client_meeting_id.like(f"{SEED_PREFIX}%"),
                                                   Meeting.user_id == owner.id))
            await db.flush()

        counts = await seed_workspace(db, owner, mate if mate.id != owner.id else None, skip)
        await db.commit()
        print("Seeded demo data:", ", ".join(f"{v} {k}" for k, v in counts.items()))


async def existing_accounts() -> list[str]:
    """Owner first, then the teammates, of the demo meetings already seeded:
    lets the server rebuild its demo without anyone typing emails."""
    async with async_session() as db:
        meeting = await db.scalar(select(Meeting).where(Meeting.client_meeting_id.like(f"{SEED_PREFIX}%"),
                                                        ~Meeting.user_id.in_(select(User.id).where(User.email.like("%@demo.wilco.invalid"))))
                                  .order_by(Meeting.created_at).limit(1))
        if meeting is None:
            return []
        owner = await db.get(User, meeting.user_id)
        mates = (await db.scalars(select(User.email).join(MeetingAttendee, MeetingAttendee.user_id == User.id)
                                  .where(MeetingAttendee.meeting_id == meeting.id, User.id != owner.id))).all()
        return [owner.email, *mates[:1]]


async def run(args: list[str], reset: bool, existing: bool) -> None:
    if existing and not args:
        args = await existing_accounts()
        print("Rebuilding the demo for", len(args), "existing account(s)")
    if not args:
        sys.exit(__doc__)
    await main(args, reset)


if __name__ == "__main__":
    asyncio.run(run([a for a in sys.argv[1:] if not a.startswith("--")], "--reset" in sys.argv, "--existing" in sys.argv))
