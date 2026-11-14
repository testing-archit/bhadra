import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.database.models import Notification, User
from app.dependencies import get_current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _serialize(notification: Notification) -> dict:
    return {
        "id": str(notification.id),
        "type": notification.type,
        "message": notification.message,
        "link": notification.link,
        "read": notification.read_at is not None,
        "created_at": notification.created_at.isoformat(),
    }


@router.get("")
async def list_notifications(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    return [_serialize(n) for n in result.scalars().all()]


@router.get("/unread-count")
async def unread_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Notification.id).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    return {"count": len(result.all())}


@router.patch("/{notification_id}")
async def mark_read(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    notification = await db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notification.read_at is None:
        notification.read_at = datetime.datetime.now(datetime.UTC)
        await db.commit()
    return _serialize(notification)


@router.post("/read-all")
async def mark_all_read(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    now = datetime.datetime.now(datetime.UTC)
    for notification in result.scalars().all():
        notification.read_at = now
    await db.commit()
    return {"ok": True}
