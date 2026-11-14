"""Email preferences and one-click unsubscribe."""

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.database.models import User
from app.dependencies import get_current_user, is_admin
from app.rate_limit import limiter
from app.services import email_service
from app.services.email_templates import app_url

router = APIRouter(prefix="/api/email", tags=["email"])


def _payload(user: User) -> dict:
    prefs = email_service.prefs_for(user)
    kinds = email_service.kind_prefs_for(user)
    return {
        "enabled": email_service.configured(),
        "address": user.email,
        "categories": [
            {
                "key": key, "label": label, "description": description, "can_disable": switchable, "enabled": prefs[key],
                "emails": [
                    {"key": kind, "label": kind_label, "description": kind_description, "enabled": kinds[kind]}
                    for kind, (kind_label, kind_description) in email_service.KIND_INFO.items()
                    if email_service.KINDS[kind][0] == key
                ],
            }
            for key, (label, description, switchable) in email_service.CATEGORIES.items()
            if key != "admin" or is_admin(user)
        ],
        "schedule": email_service.schedule_for(user),
        "send_hours": list(email_service.SEND_HOURS),
    }


class ScheduleUpdate(BaseModel):
    reminder_days: list[int] | None = None
    digest_day: int | None = Field(default=None, ge=0, le=6)
    hour: int | None = None


class PrefsUpdate(BaseModel):
    categories: dict[str, bool] = {}
    kinds: dict[str, bool] = {}
    schedule: ScheduleUpdate | None = None


@router.get("/preferences")
async def get_preferences(user: User = Depends(get_current_user)) -> dict:
    return _payload(user)


@router.put("/preferences")
async def update_preferences(body: PrefsUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    stored = dict(user.email_prefs or {})
    for key, value in body.categories.items():
        if key in email_service.CATEGORIES and email_service.CATEGORIES[key][2]:
            stored[key] = bool(value)
    kinds = dict(stored.get("kinds") or {})
    for kind, value in body.kinds.items():
        if kind in email_service.KIND_INFO and email_service.CATEGORIES[email_service.KINDS[kind][0]][2]:
            kinds[kind] = bool(value)
    stored["kinds"] = kinds
    if body.schedule is not None:
        schedule = email_service.schedule_for(user)
        if body.schedule.reminder_days is not None:
            if any(d < 0 or d > 6 for d in body.schedule.reminder_days):
                raise HTTPException(status_code=422, detail="Days must be 0 (Monday) to 6 (Sunday)")
            schedule["reminder_days"] = sorted(set(body.schedule.reminder_days))
        if body.schedule.digest_day is not None:
            schedule["digest_day"] = body.schedule.digest_day
        if body.schedule.hour is not None:
            if body.schedule.hour not in email_service.SEND_HOURS:
                raise HTTPException(status_code=422, detail="Pick a time between 06:00 and 11:00")
            schedule["hour"] = body.schedule.hour
        stored["schedule"] = schedule
    user.email_prefs = stored
    await db.commit()
    return _payload(user)


async def _unsubscribe(db: AsyncSession, token: str) -> tuple[User, str]:
    try:
        user_id, category = email_service.read_unsubscribe_token(token)
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(status_code=400, detail="This unsubscribe link isn't valid")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if email_service.CATEGORIES[category][2]:
        user.email_prefs = {**(user.email_prefs or {}), category: False}
        await db.commit()
    return user, category


@router.get("/unsubscribe", include_in_schema=False)
async def unsubscribe_link(token: str) -> RedirectResponse:
    """A plain GET never changes anything — mail scanners open links. It
    sends people to a page with a confirm button."""
    return RedirectResponse(app_url(f"/unsubscribe?token={token}"), status_code=303)


@router.post("/unsubscribe")
@limiter.limit("30/minute")
async def unsubscribe(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """RFC 8058 one-click (the mail client POSTs to the List-Unsubscribe URL,
    token in the query string) and the confirm button on /unsubscribe (token
    in a JSON body)."""
    value = request.query_params.get("token")
    if not value and request.headers.get("content-type", "").startswith("application/json"):
        value = (await request.json()).get("token")
    if not value:
        raise HTTPException(status_code=400, detail="Missing token")
    user, category = await _unsubscribe(db, value)
    return {"ok": True, "category": category, "label": email_service.CATEGORIES[category][0], "email": user.email}
