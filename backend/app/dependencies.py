import uuid

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.db import get_db
from app.database.models import Meeting, MeetingAttendee, User
from app.services import usage_ledger

JWT_ALGORITHM = "HS256"


def create_access_token(user_id: uuid.UUID, email: str) -> str:
    import datetime

    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": str(user_id),
        "email": email,
        # Compared with users.sessions_valid_after: a password reset signs
        # out every session issued before it.
        "iat": int(now.timestamp()),
        "exp": now + datetime.timedelta(days=30),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


async def get_current_user(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.removeprefix("Bearer ")
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[JWT_ALGORITHM], options={"require": ["sub", "exp"]}
        )
        # Other tokens share this secret (email unsubscribe links, calendar
        # OAuth state) and carry a `purpose`; only session tokens sign in.
        if "purpose" in payload:
            raise jwt.InvalidTokenError("not a session token")
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="This account is suspended")
    if user.sessions_valid_after is not None and payload.get("iat", 0) < int(user.sessions_valid_after.timestamp()):
        raise HTTPException(status_code=401, detail="Your password was changed. Sign in again.")
    # AI calls made while serving this request are billed to this person.
    usage_ledger.attribute(user_id=user.id)
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def is_admin(user: User) -> bool:
    return user.email.strip().lower() in settings.admin_email_list or user.role in {"admin", "super_admin"}


def department_scope(user: User) -> str | None:
    """None means unrestricted (sees every department). Otherwise, the single
    department a non-admin user is scoped to.

    Retained only for the department *labelling* of newly created projects.
    It is no longer a visibility rule — see `meeting_visibility_clause`.
    """
    return None if is_admin(user) else user.department


def meeting_visibility_clause(user: User) -> ColumnElement[bool] | None:
    """The WHERE clause restricting `Meeting` rows to the ones `user` may read
    in their own workspace: meetings they recorded (`Meeting.user_id`) or are
    listed on with *granted* access — calendar invitees, people who asked for
    the notetaker, and anyone the organizer later shared it with.

    Admins get the same clause. They can open any meeting (see
    `user_can_read_meeting`) and browse them all from the Admin panel, but
    their own Home, Meetings, Tasks and memory chat show only the meetings
    they were part of — otherwise an admin's workspace is every meeting in
    the company, which is useless to work from.

    Never returns None any more; the Optional return type is kept for callers
    written against the old "None means unrestricted" contract.
    """
    return or_(
        Meeting.user_id == user.id,
        Meeting.id.in_(
            select(MeetingAttendee.meeting_id).where(
                MeetingAttendee.user_id == user.id, MeetingAttendee.access == "granted"
            )
        ),
    )


def visible_meeting_ids(user: User):
    """Subquery of the meeting ids `user` may read. Unlike
    `meeting_visibility_clause` this is always a real subquery, for the
    callers that need to filter a table that is not joined to `meetings`."""
    query = select(Meeting.id).where(Meeting.deleted_at.is_(None))
    clause = meeting_visibility_clause(user)
    if clause is not None:
        query = query.where(clause)
    return query


async def user_can_read_meeting(
    db: AsyncSession, user: User, meeting_id: uuid.UUID | None
) -> bool:
    """Whether `user` may open the meeting: they recorded it, have granted
    access to it, or are a Wilco admin. Says nothing about
    whether the meeting is deleted — callers filter on `deleted_at` themselves,
    because the recycle bin legitimately reads deleted meetings."""
    if meeting_id is None:
        return False
    # Admins can open any single meeting — that is how the Admin panel's
    # "All meetings" list works — without it filling their own lists. Not a
    # confidential one: only the people in it can open that.
    if is_admin(user):
        confidential = await db.scalar(select(Meeting.confidential).where(Meeting.id == meeting_id))
        if not confidential:
            return True
    clause = meeting_visibility_clause(user)
    result = await db.execute(
        select(Meeting.id).where(Meeting.id == meeting_id, clause).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def user_can_manage_meeting_access(db: AsyncSession, user: User, meeting: Meeting) -> bool:
    """Who decides who else may read a meeting: the person whose notetaker
    recorded it, the calendar organizer (when they have an account), and
    Wilco admins — except on a confidential meeting, which only its
    recorder and organizer manage (an admin could otherwise share it with
    themselves)."""
    if meeting.user_id == user.id or meeting.organizer_user_id == user.id:
        return True
    return is_admin(user) and not meeting.confidential


# No-sign-up demo accounts (POST /api/auth/demo). The .invalid domain can
# never receive mail; these accounts get a private seeded workspace and
# can't reach anything outside it (notetaker, calendars, voice cloning).
DEMO_EMAIL_DOMAIN = "demo.wilco.invalid"


def is_demo(user: User) -> bool:
    return (user.email or "").lower().endswith("@" + DEMO_EMAIL_DOMAIN)


async def require_full_account(user: User = Depends(get_current_user)) -> User:
    if is_demo(user):
        raise HTTPException(status_code=403, detail="That isn't available in the demo. Create a free account to use it.")
    return user
