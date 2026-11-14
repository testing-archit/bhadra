"""Give colleagues the meetings they were invited to before they had an
account. New accounts get this at sign-up (`attendee_service.link_new_account`);
this applies it to accounts that already exist, then links tasks whose stated
owner now resolves to an account.

Idempotent.

    python scripts/link_invited_accounts.py [--dry-run]
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.database.db import async_session
from app.database.models import User
from app.services import attendee_service


async def main(dry_run: bool) -> None:
    async with async_session() as db:
        users = (await db.execute(select(User).where(User.status == "active"))).scalars().all()
        for user in users:
            meetings = await attendee_service.link_new_account(db, user)
            if meetings:
                print(f"{user.email}: now on {len(meetings)} meeting(s) {sorted(map(str, meetings))}")
        linked = await attendee_service.relink_task_owners(db)
        print(f"{linked} task(s) linked to their owner's account")
        if dry_run:
            await db.rollback()
        else:
            await db.commit()


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))
