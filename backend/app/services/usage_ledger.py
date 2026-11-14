"""Every paid AI call, priced at the moment it happens.

Each Gemini generation and Deepgram transcription records one
`AiUsageEvent`: tokens (or audio seconds), the USD cost from the price table
below, the live USD→INR rate fetched at that moment, the INR cost, and who /
which meeting / which feature it was for. The admin panel reads these rows
directly, so a past month's spend never changes when today's exchange rate
or prices do.

Calls happen in worker threads (the SDKs are synchronous), so recording is
handed to the app's event loop and never slows or breaks the AI call itself.
"""

import asyncio
import contextvars
import datetime
import json
import logging
import uuid
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)

# USD per 1M tokens (input, cached input, output), Standard paid tier, text
# prompts <= 200k tokens — per model, matched by the longest prefix. From
# Google's published price list (PRICES_SOURCE). Override any of these with
# AI_PRICING_JSON, e.g. {"gemini-3.8-flash": {"input": 0.75, "cached": 0.075, "output": 3.75}}.
PRICES_SOURCE = "ai.google.dev/gemini-api/docs/pricing, checked 2026-10-07"
_FLASH_2026 = {"input": 0.75, "cached": 0.075, "output": 3.75}
_FLASH_2027 = {"input": 1.50, "cached": 0.15, "output": 7.50}
DEFAULT_TOKEN_PRICES: dict[str, dict[str, float]] = {
    # Introductory prices through 2026-12-31; see PRICE_CHANGES.
    "gemini-3.8-flash": _FLASH_2026,
    "gemini-3.7-flash": _FLASH_2026,
    "gemini-3.6-flash": _FLASH_2026,
    "gemini-3.5-flash-lite": {"input": 0.30, "cached": 0.03, "output": 2.50},
    "gemini-3.5-flash": {"input": 1.50, "cached": 0.15, "output": 9.00},
    "gemini-3.1-flash-lite": {"input": 0.25, "cached": 0.025, "output": 1.50},
    "gemini-3.1-pro": {"input": 2.00, "cached": 0.20, "output": 12.00},
    "gemini-2.5-flash-lite": {"input": 0.10, "cached": 0.01, "output": 0.40},
    "gemini-2.5-flash": {"input": 0.30, "cached": 0.03, "output": 2.50},
    "gemini-2.5-pro": {"input": 1.25, "cached": 0.125, "output": 10.00},
    # Anything unlisted is priced like the current default Flash model.
    "gemini": _FLASH_2026,
}
# Published future price changes: from that date (UTC) the entry replaces the
# default above. Google announced the 3.6–3.8 Flash prices double in 2027.
PRICE_CHANGES: dict[str, list[tuple[datetime.date, dict[str, float]]]] = {
    key: [(datetime.date(2027, 1, 1), _FLASH_2027)]
    for key in ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini")
}


def default_token_prices(on: datetime.date | None = None) -> dict[str, dict[str, float]]:
    """The published price table in force on `on` (default: today, UTC)."""
    on = on or datetime.datetime.now(datetime.UTC).date()
    table = dict(DEFAULT_TOKEN_PRICES)
    for key, changes in PRICE_CHANGES.items():
        for since, prices in sorted(changes, key=lambda change: change[0]):
            if on >= since:
                table[key] = prices
    return table


# USD per audio minute: Nova-3 multilingual, pre-recorded, pay as you go, as
# requested by transcriber.py. Diarization is included for pre-recorded audio
# (the US$0.002 add-on is streaming only) — deepgram.com/pricing, checked
# 2026-10-09. Override with AI_PRICING_JSON, e.g. {"deepgram": 0.0043} on Growth.
DEFAULT_AUDIO_PRICES: dict[str, float] = {"deepgram": 0.0052}


@dataclass
class Attribution:
    user_id: uuid.UUID | None = None
    meeting_id: uuid.UUID | None = None
    # Events of this request recorded before its meeting existed (a bot
    # ingest transcribes and extracts notes first, then creates the meeting);
    # they are linked to it once attribute(meeting_id=...) is called.
    unassigned: list | None = None


# Set per request (see dependencies.get_current_user) and copied into the
# worker threads asyncio.to_thread runs AI calls in.
current = contextvars.ContextVar("ai_usage_attribution", default=Attribution())
_loop: asyncio.AbstractEventLoop | None = None
# The event loop keeps only weak references to tasks; a write still pending
# could otherwise be garbage-collected before it records anything.
_pending: set[asyncio.Task] = set()


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def attribute(*, user_id: uuid.UUID | None = None, meeting_id: uuid.UUID | None = None) -> None:
    """Who the next AI calls in this request are for. Fields left None keep
    what was already set."""
    previous = current.get()
    unassigned = previous.unassigned if previous.unassigned is not None else []
    if meeting_id is not None and previous.meeting_id is None and unassigned:
        _link_to_meeting(list(unassigned), meeting_id)
        unassigned = []
    current.set(
        Attribution(
            user_id=user_id or previous.user_id,
            meeting_id=meeting_id or previous.meeting_id,
            unassigned=unassigned,
        )
    )


def _link_to_meeting(events: list[dict], meeting_id: uuid.UUID) -> None:
    written = []
    for event in events:
        event["meeting_id"] = meeting_id  # picked up by a write still pending
        if event.get("id") is not None:
            written.append(event["id"])
    if written:
        _spawn(_set_meeting(written, meeting_id))


async def _set_meeting(ids: list, meeting_id: uuid.UUID) -> None:
    from sqlalchemy import update

    from app.database.db import async_session
    from app.database.models import AiUsageEvent

    try:
        async with async_session() as db:
            await db.execute(update(AiUsageEvent).where(AiUsageEvent.id.in_(ids)).values(meeting_id=meeting_id))
            await db.commit()
    except Exception:
        logger.exception("Could not link AI usage to meeting %s", meeting_id)


def _overrides() -> dict:
    if not settings.ai_pricing_json:
        return {}
    try:
        return json.loads(settings.ai_pricing_json)
    except ValueError:
        logger.warning("AI_PRICING_JSON is not valid JSON; using default prices")
        return {}


def token_prices(model: str, on: datetime.date | None = None) -> tuple[dict[str, float], str]:
    """(prices, which entry matched) for a model, on a date (default today)."""
    table = {**default_token_prices(on), **{k: v for k, v in _overrides().items() if isinstance(v, dict)}}
    for key in sorted(table, key=len, reverse=True):
        if model.startswith(key):
            return table[key], key
    return table["gemini"], "gemini"


def audio_price_per_minute(provider: str) -> float:
    override = _overrides().get(provider)
    return float(override) if isinstance(override, (int, float)) else DEFAULT_AUDIO_PRICES.get(provider, 0.0)


def token_cost_usd(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    prices, _ = token_prices(model)
    billable_input = max(0, input_tokens - cached_tokens)
    return (
        billable_input * prices["input"] + cached_tokens * prices.get("cached", prices["input"]) + output_tokens * prices["output"]
    ) / 1_000_000


def record_tokens(feature: str, model: str, usage: dict) -> None:
    """Called right after a Gemini generation, from any thread."""
    _schedule(
        dict(
            provider="gemini",
            feature=feature,
            model=model,
            input_tokens=int(usage.get("input_tokens") or 0),
            cached_tokens=int(usage.get("cache_tokens_read") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            audio_seconds=0.0,
            usd_cost=token_cost_usd(
                model,
                int(usage.get("input_tokens") or 0),
                int(usage.get("cache_tokens_read") or 0),
                int(usage.get("output_tokens") or 0),
            ),
        )
    )


def record_audio(feature: str, provider: str, model: str, seconds: float) -> None:
    """Called right after a transcription."""
    _schedule(
        dict(
            provider=provider,
            feature=feature,
            model=model,
            input_tokens=0,
            cached_tokens=0,
            output_tokens=0,
            audio_seconds=float(seconds or 0),
            usd_cost=(float(seconds or 0) / 60) * audio_price_per_minute(provider),
        )
    )


def _schedule(event: dict) -> None:
    attribution = current.get()
    event.update(user_id=attribution.user_id, meeting_id=attribution.meeting_id, occurred_at=datetime.datetime.now(datetime.UTC))
    if attribution.meeting_id is None and attribution.unassigned is not None:
        attribution.unassigned.append(event)
    _spawn(_write(event))


def _spawn(coroutine) -> None:
    loop = _loop
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    try:
        if running is not None:
            task = running.create_task(coroutine)
            _pending.add(task)
            task.add_done_callback(_pending.discard)
        elif loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(coroutine, loop)
        else:  # No loop (scripts, some tests): nothing to record into.
            coroutine.close()
    except Exception:
        coroutine.close()
        logger.exception("Could not schedule an AI usage record")


async def _write(event: dict) -> None:
    from sqlalchemy import update

    from app.database.db import async_session
    from app.database.models import AiUsageEvent
    from app.services import exchange_rate_service

    try:
        rate = await exchange_rate_service.usd_to_inr()
        async with async_session() as db:
            row = AiUsageEvent(
                **{key: value for key, value in event.items() if key != "id"},
                usd_to_inr=rate["usd_to_inr"],
                inr_cost=event["usd_cost"] * rate["usd_to_inr"],
                rate_source=rate.get("source"),
                rate_quoted_at=_parse_time(rate.get("quoted_at")),
            )
            db.add(row)
            await db.commit()
            event["id"] = row.id
            if event["meeting_id"] != row.meeting_id:
                # The meeting was created while this row was being written.
                await db.execute(update(AiUsageEvent).where(AiUsageEvent.id == row.id).values(meeting_id=event["meeting_id"]))
                await db.commit()
    except Exception:
        logger.exception("Could not record AI usage")


def _parse_time(value) -> datetime.datetime | None:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
