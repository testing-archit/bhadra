import datetime
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.db import get_db
from app.database.models import PasswordResetToken, User
from app.dependencies import create_access_token, get_current_user, is_admin
from app.rate_limit import limiter
from app.services import attendee_service, email_service
from app.services.password_service import hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _signup_allowed(email: str) -> bool:
    domains = settings.allowed_signup_domain_list
    return not domains or email.rsplit("@", 1)[-1].lower() in domains


class GoogleLoginRequest(BaseModel):
    google_access_token: str


class LoginResponse(BaseModel):
    token: str
    email: str
    name: str | None


@router.post("/google", response_model=LoginResponse)
@limiter.limit("10/minute")
async def login_with_google(
    request: Request,
    body: GoogleLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {body.google_access_token}"},
        )

    if not r.is_success:
        raise HTTPException(status_code=401, detail="Invalid Google access token")

    info = r.json()
    email = (info.get("email") or "").strip().lower()
    google_sub = info.get("sub")
    name = info.get("name")
    if not email or not google_sub:
        raise HTTPException(status_code=401, detail="Google didn't share an email address for this account")

    result = await db.execute(select(User).where(User.google_sub == google_sub))
    user = result.scalar_one_or_none()

    if user is None:
        # Linking by email is only safe when Google has verified that the
        # account owns the address; otherwise anyone could claim it.
        if info.get("email_verified") is not True and str(info.get("email_verified")).lower() != "true":
            raise HTTPException(status_code=403, detail="Verify this email address with Google first, then sign in again")
        result = await db.execute(select(User).where(func.lower(User.email) == email))
        user = result.scalar_one_or_none()
        if user is None and not _signup_allowed(email):
            raise HTTPException(status_code=403, detail="Sign-up is limited to your company's email addresses. Ask an admin to invite you.")
        if user is not None:
            user.google_sub = google_sub
            await db.commit()
            await db.refresh(user)
        else:
            user = User(email=email, name=name, google_sub=google_sub)
            db.add(user)
            await db.flush()
            await attendee_service.link_new_account(db, user)
            await email_service.enqueue(db, "welcome", user.id, dedupe_key=f"welcome:{user.id}")
            await db.commit()
            await db.refresh(user)

    if user.status != "active":
        raise HTTPException(status_code=403, detail="This account is suspended")

    token = create_access_token(user.id, user.email)
    return LoginResponse(token=token, email=user.email, name=user.name)


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email address")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(v) > 128:
            raise ValueError("Password is too long")
        return v


class PasswordLoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        return v.strip().lower()


@router.post("/register", response_model=LoginResponse)
@limiter.limit("5/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    if not _signup_allowed(body.email):
        raise HTTPException(status_code=403, detail="Sign-up is limited to your company's email addresses. Ask an admin to invite you.")
    result = await db.execute(select(User).where(func.lower(User.email) == body.email))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user = User(email=body.email, name=body.name, password_hash=hash_password(body.password))
    db.add(user)
    await db.flush()
    await attendee_service.link_new_account(db, user)
    await email_service.enqueue(db, "welcome", user.id, dedupe_key=f"welcome:{user.id}")
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id, user.email)
    return LoginResponse(token=token, email=user.email, name=user.name)


@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/minute")
async def login_with_password(
    request: Request,
    body: PasswordLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    result = await db.execute(select(User).where(func.lower(User.email) == body.email))
    user = result.scalar_one_or_none()

    if user is None or user.password_hash is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="This account is suspended")

    token = create_access_token(user.id, user.email)
    return LoginResponse(token=token, email=user.email, name=user.name)


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(user: User = Depends(get_current_user)) -> LoginResponse:
    """Re-mints a fresh 30-day token for an already-valid session, so an
    active user is never silently logged out mid-month. Requires the
    current token to still be valid — an expired token can't refresh
    itself, it has to go through /google again."""
    token = create_access_token(user.id, user.email)
    return LoginResponse(token=token, email=user.email, name=user.name)


class MeResponse(BaseModel):
    id: str
    email: str
    name: str | None
    department: str | None
    is_admin: bool
    role: str
    status: str
    team_id: str | None
    team_name: str | None
    job_title: str | None
    auth_method: str
    # Whether a Wilco password is set (Google accounts may have none).
    has_password: bool = False
    created_at: str


class UpdateDepartmentRequest(BaseModel):
    department: str


class GoogleSheetsSettings(BaseModel):
    spreadsheet_id: str | None = None
    tasks_tab: str = "Tasks"
    notes_tab: str = "Meeting Notes"

    @field_validator("spreadsheet_id")
    @classmethod
    def normalize_spreadsheet_id(cls, value: str | None) -> str | None:
        if not value or not value.strip():
            return None
        value = value.strip()
        match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", value)
        value = match.group(1) if match else value
        if len(value) > 200 or not re.fullmatch(r"[a-zA-Z0-9_-]+", value):
            raise ValueError("Invalid Google spreadsheet ID")
        return value

    @field_validator("tasks_tab", "notes_tab")
    @classmethod
    def validate_tab_name(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 100:
            raise ValueError("Sheet tab names must contain between 1 and 100 characters")
        return value


@router.post("/connector-token")
@limiter.limit("10/hour")
async def connector_token(request: Request, user: User = Depends(get_current_user)) -> dict:
    """A 90-day token for connecting Claude (or another MCP client) to this
    person's Wilco. It only works on the MCP endpoint, never the regular
    API, and a password change revokes it."""
    from app import mcp_server

    token, expires = mcp_server.create_connector_token(user)
    return {"token": token, "url": mcp_server.connector_url(), "expires_at": expires.isoformat()}


@router.get("/me", response_model=MeResponse)
async def get_me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> MeResponse:
    from app.database.models import Team
    team = await db.get(Team, user.team_id) if user.team_id else None
    return MeResponse(
        id=str(user.id), email=user.email, name=user.name, department=user.department, is_admin=is_admin(user),
        role="super_admin" if user.email.strip().lower() in settings.admin_email_list else user.role,
        status=user.status, team_id=str(user.team_id) if user.team_id else None,
        team_name=team.name if team else None, job_title=user.job_title,
        auth_method="Google" if user.google_sub else "Password", has_password=user.password_hash is not None, created_at=user.created_at.isoformat(),
    )


@router.patch("/me", response_model=MeResponse)
async def update_me(
    body: UpdateDepartmentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    user.department = body.department.strip()
    await db.commit()
    from app.database.models import Team
    team = await db.get(Team, user.team_id) if user.team_id else None
    return MeResponse(
        id=str(user.id), email=user.email, name=user.name, department=user.department, is_admin=is_admin(user),
        role="super_admin" if user.email.strip().lower() in settings.admin_email_list else user.role,
        status=user.status, team_id=str(user.team_id) if user.team_id else None,
        team_name=team.name if team else None, job_title=user.job_title,
        auth_method="Google" if user.google_sub else "Password", has_password=user.password_hash is not None, created_at=user.created_at.isoformat(),
    )


@router.get("/directory")
async def list_directory(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Every active Wilco account, for the attendee pickers.

    Not admin-only on purpose: to say who was in a meeting you have to be able
    to see the list of colleagues. It exposes name, email and department —
    the same things an org chart would — and nothing about their meetings.
    """
    result = await db.execute(
        select(User).where(User.status == "active").order_by(User.name, User.email)
    )
    return [
        {
            "id": str(item.id),
            "name": item.name or item.email.split("@")[0],
            "email": item.email,
            "department": item.department,
            "job_title": item.job_title,
        }
        for item in result.scalars().all()
    ]


@router.get("/integrations/google-sheets", response_model=GoogleSheetsSettings)
async def get_google_sheets_settings(user: User = Depends(get_current_user)) -> GoogleSheetsSettings:
    return GoogleSheetsSettings(
        spreadsheet_id=user.google_sheets_spreadsheet_id,
        tasks_tab=user.google_sheets_tasks_tab,
        notes_tab=user.google_sheets_notes_tab,
    )


@router.put("/integrations/google-sheets", response_model=GoogleSheetsSettings)
async def update_google_sheets_settings(
    body: GoogleSheetsSettings,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GoogleSheetsSettings:
    user.google_sheets_spreadsheet_id = body.spreadsheet_id
    user.google_sheets_tasks_tab = body.tasks_tab
    user.google_sheets_notes_tab = body.notes_tab
    await db.commit()
    return body


# --- passwords -----------------------------------------------------------------------


def _valid_password(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    if len(v) > 128:
        raise ValueError("Password is too long")
    return v


class ForgotPasswordRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def normalize(cls, v: str) -> str:
        return v.strip().lower()


class ResetPasswordRequest(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def check(cls, v: str) -> str:
        return _valid_password(v)


class ChangePasswordRequest(BaseModel):
    current_password: str | None = None
    new_password: str

    @field_validator("new_password")
    @classmethod
    def check(cls, v: str) -> str:
        return _valid_password(v)


FORGOT_COOLDOWN = datetime.timedelta(minutes=2)


@router.post("/password/forgot")
@limiter.limit("5/minute")
async def forgot_password(request: Request, body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Always the same answer, whether or not the address has an account, so
    this can't be used to find out who uses Wilco."""
    user = (await db.execute(select(User).where(func.lower(User.email) == body.email))).scalar_one_or_none()
    if user is not None and user.status == "active":
        recent = await db.scalar(
            select(func.count()).select_from(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.purpose == "reset",
                PasswordResetToken.created_at >= datetime.datetime.now(datetime.UTC) - FORGOT_COOLDOWN,
            )
        )
        if not recent:
            if user.password_hash is None and user.google_sub:
                # Google-only accounts get a link to *set* a password: the
                # same proof (access to the inbox) as a reset.
                token = await email_service.issue_password_link(db, user, "reset")
                await email_service.enqueue(db, "password_reset_google", user.id, {"token": token}, dedupe_key=f"password_reset_google:{token[:16]}")
            else:
                token = await email_service.issue_password_link(db, user, "reset")
                await email_service.enqueue(db, "password_reset", user.id, {"token": token}, dedupe_key=f"password_reset:{token[:16]}")
            await db.commit()
    return {"ok": True, "message": "If that address has a Wilco account, a reset link is on its way."}


@router.post("/password/reset", response_model=LoginResponse)
@limiter.limit("10/minute")
async def reset_password(request: Request, body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    user = await email_service.redeem_password_link(db, body.token)
    if user is None:
        raise HTTPException(status_code=400, detail="This link has expired or was already used. Ask for a new one.")
    await _set_password(db, user, body.password, how="reset")
    # A fresh session: its iat isn't before the cut-off (both whole seconds).
    return LoginResponse(token=create_access_token(user.id, user.email), email=user.email, name=user.name)


@router.post("/password/change", response_model=LoginResponse)
@limiter.limit("5/minute")
async def change_password(
    request: Request, body: ChangePasswordRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> LoginResponse:
    """Set or change your password from Settings. Changing needs the current
    one; a Google-only account can add one without it."""
    if user.password_hash is not None and not verify_password(body.current_password or "", user.password_hash):
        raise HTTPException(status_code=400, detail="Your current password isn't right")
    await _set_password(db, user, body.new_password, how="settings")
    return LoginResponse(token=create_access_token(user.id, user.email), email=user.email, name=user.name)


async def _set_password(db: AsyncSession, user: User, password: str, *, how: str) -> None:
    now = datetime.datetime.now(datetime.UTC)
    user.password_hash = hash_password(password)
    # Every session issued before now stops working.
    user.sessions_valid_after = now
    await email_service.enqueue(
        db, "password_changed", user.id, {"how": how, "at": now.isoformat()}, dedupe_key=f"password_changed:{user.id}:{now.isoformat()}"
    )
    await db.commit()
