import asyncio
import time
from datetime import datetime, timezone

import httpx

from app.config import settings

FALLBACK_USD_TO_INR = 94.0
# Free, keyless sources, tried in order. All publish daily reference rates,
# which is all AI-cost reporting needs.
FREE_SOURCES = [
    (
        "open.er-api.com",
        "https://open.er-api.com/v6/latest/USD",
        lambda body: body["rates"]["INR"],
        lambda body: body.get("time_last_update_unix"),
    ),
    (
        "Frankfurter (ECB)",
        "https://api.frankfurter.dev/v1/latest?base=USD&symbols=INR",
        lambda body: body["rates"]["INR"],
        lambda body: _date_stamp(body.get("date")),
    ),
    (
        "fawazahmed0 currency-api",
        "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json",
        lambda body: body["usd"]["inr"],
        lambda body: _date_stamp(body.get("date")),
    ),
]
# A failed lookup is not retried for this long, so an outage can't turn every
# AI call into a slow network round-trip.
FAILURE_BACKOFF_SECONDS = 15 * 60

_cached_rate: dict | None = None
_cache_deadline = 0.0
_lock = asyncio.Lock()


def _date_stamp(value: str | None) -> int | None:
    if not value:
        return None
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


async def usd_to_inr() -> dict:
    """The current USD→INR quote, reused for `fx_cache_seconds`.

    Every AI call is priced with this, and stores the rate and its source, so
    spend reflects the rate at the moment it happened. The free daily sources
    are tried in order, then the last good quote, then a fixed fallback — and
    a failure backs off instead of retrying on every call.
    """
    global _cached_rate, _cache_deadline
    now = time.monotonic()
    if _cached_rate is not None and now < _cache_deadline:
        return {**_cached_rate, "cached": True}

    async with _lock:
        now = time.monotonic()
        if _cached_rate is not None and now < _cache_deadline:
            return {**_cached_rate, "cached": True}

        for name, url, read_rate, read_time in FREE_SOURCES:
            try:
                # Providers move their APIs behind redirects (frankfurter.app
                # did); follow them rather than silently losing a source.
                async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    body = response.json()
                rate = float(read_rate(body))
                if rate <= 0:
                    continue
                stamp = read_time(body)
                _cached_rate = {
                    "usd_to_inr": rate,
                    "source": name,
                    "quoted_at": datetime.fromtimestamp(int(stamp), tz=timezone.utc).isoformat() if stamp else datetime.now(timezone.utc).isoformat(),
                    "live": False,
                }
                _cache_deadline = now + settings.fx_cache_seconds
                return {**_cached_rate, "cached": False}
            except (httpx.HTTPError, KeyError, TypeError, ValueError):
                continue

        if _cached_rate is not None and _cached_rate.get("source") != "Configured fallback":
            _cached_rate = {**_cached_rate, "live": False}
            _cache_deadline = now + FAILURE_BACKOFF_SECONDS
            return {**_cached_rate, "cached": True}

        _cached_rate = {
            "usd_to_inr": FALLBACK_USD_TO_INR,
            "source": "Configured fallback",
            "quoted_at": None,
            "live": False,
        }
        _cache_deadline = now + FAILURE_BACKOFF_SECONDS
        return {**_cached_rate, "cached": False}
