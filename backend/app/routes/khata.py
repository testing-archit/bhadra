"""Voice khata: a shop's udhaar ledger kept by speaking.

Gnani Prisma hears the shopkeeper in any Indian language, Wilco's language
layer turns the note into entries, and reminders are written in the
customer's language and can be read aloud by Gnani Timbre."""
import asyncio
import base64
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.database.models import KhataEntry, User
from app.dependencies import get_current_user
from app.rate_limit import limiter
from app.services import khata_service, transcriber, tts_service, usage_ledger

router = APIRouter(prefix="/api/khata", tags=["khata"])
MAX_AUDIO_BYTES = 8 * 1024 * 1024


def _entry(row: KhataEntry) -> dict:
    return {"id": str(row.id), "customer": row.customer, "kind": row.kind, "amount": row.amount,
            "note": row.note, "said": row.said, "created_at": row.created_at.isoformat() if row.created_at else None}


async def _ledger(db: AsyncSession, user: User) -> dict:
    rows = (await db.scalars(select(KhataEntry).where(KhataEntry.user_id == user.id)
                             .order_by(KhataEntry.created_at.desc()).limit(500))).all()
    balances: dict[str, dict] = {}
    totals = defaultdict(float)
    for row in reversed(rows):  # oldest first, so the newest spelling wins
        item = balances.setdefault(row.customer_key, {"customer": row.customer, "balance": 0.0, "last_at": None})
        item["customer"] = row.customer
        item["balance"] += row.amount if row.kind == "credit" else -row.amount
        item["last_at"] = row.created_at.isoformat() if row.created_at else None
        totals[row.kind] += row.amount
    customers = sorted(balances.values(), key=lambda item: -item["balance"])
    return {
        "entries": [_entry(row) for row in rows[:100]],
        "customers": customers,
        "outstanding": round(sum(max(item["balance"], 0) for item in customers), 2),
        "given": round(totals["credit"], 2),
        "received": round(totals["payment"], 2),
    }


async def _record(db: AsyncSession, user: User, said: str) -> list[KhataEntry]:
    usage_ledger.attribute(user_id=user.id)
    try:
        parsed = await asyncio.to_thread(khata_service.parse, said)
    except Exception as error:
        raise HTTPException(status_code=502, detail="Couldn't understand that right now. Try again.") from error
    if not parsed:
        raise HTTPException(status_code=422, detail="I didn't hear a name and an amount. Try “Gupta ji ne 500 ka udhaar liya”.")
    rows = [KhataEntry(user_id=user.id, customer=item.customer.strip(), customer_key=khata_service.customer_key(item.customer),
                       kind=item.kind, amount=round(item.amount, 2), note=item.note.strip() or None, said=said.strip()[:2000])
            for item in parsed]
    db.add_all(rows)
    await db.commit()
    return rows


@router.get("")
async def ledger(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return await _ledger(db, user)


class KhataText(BaseModel):
    text: str = Field(min_length=3, max_length=2000)


@router.post("/text")
@limiter.limit("30/minute")
async def add_by_text(request: Request, body: KhataText, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)) -> dict:
    rows = await _record(db, user, body.text)
    return {"added": [_entry(row) for row in rows], **(await _ledger(db, user))}


@router.post("/voice")
@limiter.limit("30/minute")
async def add_by_voice(request: Request, audio: UploadFile = File(...), user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)) -> dict:
    """Speak a line in any Indian language; Gnani Prisma transcribes it."""
    data = await audio.read()
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=422, detail="Record a short note, up to about a minute.")
    usage_ledger.attribute(user_id=user.id)
    try:
        heard = await transcriber.transcribe_audio_detailed(data, audio.content_type or "audio/webm", "auto",
                                                             timeout_seconds=20, interactive=True)
    except transcriber.TranscriptionNotConfigured as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Couldn't hear that clearly. Try again.") from error
    said = " ".join(turn["text"] for turn in heard.get("turns") or []).strip()
    if not said:
        raise HTTPException(status_code=422, detail="I didn't catch any speech. Try again closer to the phone.")
    rows = await _record(db, user, said)
    return {"heard": said, "language": heard.get("language"), "added": [_entry(row) for row in rows], **(await _ledger(db, user))}


@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    await db.execute(delete(KhataEntry).where(KhataEntry.id == entry_id, KhataEntry.user_id == user.id))
    await db.commit()
    return await _ledger(db, user)


class ReminderRequest(BaseModel):
    customer: str = Field(min_length=1, max_length=120)
    language: str = Field(default="hi-en", max_length=8)
    shop: str = Field(default="", max_length=120)
    speak: bool = False


@router.post("/reminder")
@limiter.limit("20/minute")
async def reminder(request: Request, body: ReminderRequest, user: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)) -> dict:
    """A polite WhatsApp reminder for a customer's balance, in their language;
    optionally read aloud by Gnani Timbre (to send as a voice note)."""
    if body.language not in khata_service.LANGUAGES:
        raise HTTPException(status_code=422, detail="Pick one of the listed languages.")
    key = khata_service.customer_key(body.customer)
    rows = (await db.scalars(select(KhataEntry).where(KhataEntry.user_id == user.id, KhataEntry.customer_key == key))).all()
    balance = sum(row.amount if row.kind == "credit" else -row.amount for row in rows)
    if balance <= 0:
        raise HTTPException(status_code=409, detail="Nothing is pending for this customer.")
    usage_ledger.attribute(user_id=user.id)
    shop = body.shop.strip() or f"{(user.name or 'our').split(' ')[0]}'s shop"
    try:
        text = await asyncio.to_thread(khata_service.reminder, rows[-1].customer, balance, shop, body.language)
    except Exception as error:
        raise HTTPException(status_code=502, detail="Couldn't write the reminder right now.") from error
    audio = None
    if body.speak:
        try:
            audio = base64.b64encode(await tts_service.synthesize(text, body.language)).decode()
        except Exception:
            audio = None
    return {"customer": rows[-1].customer, "balance": round(balance, 2), "text": text, "audio": audio}
