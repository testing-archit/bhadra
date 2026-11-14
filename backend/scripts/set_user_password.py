import argparse
import asyncio
import getpass
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.db import async_session  # noqa: E402
from app.database.models import User  # noqa: E402
from app.services.password_service import hash_password  # noqa: E402


async def set_user_password(email: str, password: str, name: str | None) -> str:
    normalized_email = email.strip().lower()
    async with async_session() as db:
        result = await db.execute(select(User).where(User.email == normalized_email))
        user = result.scalar_one_or_none()
        action = "updated"
        if user is None:
            user = User(email=normalized_email, name=name)
            db.add(user)
            action = "created"
        elif name and not user.name:
            user.name = name

        user.password_hash = hash_password(password)
        await db.commit()
        return action


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a user or reset an existing user's password.")
    parser.add_argument("email")
    parser.add_argument("--name")
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")
    if not 8 <= len(password) <= 128:
        raise SystemExit("Password must contain between 8 and 128 characters.")

    action = asyncio.run(set_user_password(args.email, password, args.name))
    print(f"User {args.email.strip().lower()} {action}.")


if __name__ == "__main__":
    main()
