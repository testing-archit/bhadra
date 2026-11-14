"""AI cost ledger: every paid call priced at the moment it happens."""

import asyncio
import datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select

from app.database.db import async_session
from app.database.models import AiUsageEvent
from app.services import usage_ledger
from tests.conftest import auth_headers

RATE = {"usd_to_inr": 90.0, "source": "pytest-fx", "quoted_at": "2026-10-07T10:00:00+00:00", "live": True}


def test_token_cost_counts_cached_tokens_at_the_cached_price():
    # 1M input of which 400k cached, 100k output, at Google's 3.5 Flash prices.
    cost = usage_ledger.token_cost_usd("gemini-3.5-flash", 1_000_000, 400_000, 100_000)
    assert round(cost, 6) == round((600_000 * 1.50 + 400_000 * 0.15 + 100_000 * 9.00) / 1_000_000, 6)


def test_published_flash_prices_double_in_2027():
    before = usage_ledger.token_prices("gemini-3.8-flash", datetime.date(2026, 12, 31))[0]
    after = usage_ledger.token_prices("gemini-3.8-flash", datetime.date(2027, 1, 1))[0]
    assert before == {"input": 0.75, "cached": 0.075, "output": 3.75}
    assert after == {"input": 1.50, "cached": 0.15, "output": 7.50}
    # Flash-Lite has no announced change.
    assert usage_ledger.token_prices("gemini-3.5-flash-lite", datetime.date(2027, 6, 1))[0]["input"] == 0.30


def test_prices_match_the_longest_model_prefix_and_can_be_overridden():
    assert usage_ledger.token_prices("gemini-2.5-flash-lite-001")[1] == "gemini-2.5-flash-lite"
    assert usage_ledger.token_prices("some-future-model")[1] == "gemini"
    with patch.object(usage_ledger.settings, "ai_pricing_json", '{"gemini-3.5-flash": {"input": 1, "cached": 0.5, "output": 2}, "gnani": 0.02}'):
        assert usage_ledger.token_cost_usd("gemini-3.5-flash", 1_000_000, 0, 1_000_000) == 3.0
        assert usage_ledger.audio_price_per_minute("gnani") == 0.02


async def test_calls_are_recorded_with_the_rate_at_that_moment(member_user):
    with patch("app.services.exchange_rate_service.usd_to_inr", new=AsyncMock(return_value=RATE)):
        usage_ledger.attribute(user_id=member_user.id)
        usage_ledger.record_tokens("pytest_feature", "gemini-3.5-flash", {"input_tokens": 1000, "output_tokens": 500, "cache_tokens_read": 0})
        usage_ledger.record_audio("pytest_feature", "gnani", "prisma-v3.0", 120)
        for _ in range(50):
            await asyncio.sleep(0.05)
            async with async_session() as db:
                rows = (await db.execute(select(AiUsageEvent).where(AiUsageEvent.feature == "pytest_feature"))).scalars().all()
            if len(rows) == 2:
                break
    try:
        assert len(rows) == 2
        tokens = next(r for r in rows if r.provider == "gemini")
        audio = next(r for r in rows if r.provider == "gnani")
        assert tokens.user_id == member_user.id and tokens.usd_to_inr == 90.0 and tokens.rate_source == "pytest-fx"
        assert abs(tokens.inr_cost - tokens.usd_cost * 90) < 1e-9
        assert audio.usd_cost == 0
    finally:
        async with async_session() as db:
            await db.execute(delete(AiUsageEvent).where(AiUsageEvent.feature == "pytest_feature"))
            await db.commit()


async def test_admin_cost_report(client, admin_user, member_user):
    async with async_session() as db:
        db.add(AiUsageEvent(
            occurred_at=datetime.datetime.now(datetime.UTC), provider="gemini", feature="pytest_report", model="gemini-3.5-flash",
            input_tokens=10, output_tokens=5, usd_cost=0.5, usd_to_inr=90, inr_cost=45, rate_source="pytest", user_id=member_user.id,
        ))
        await db.commit()
    try:
        with patch("app.services.exchange_rate_service.usd_to_inr", new=AsyncMock(return_value=RATE)):
            report = (await client.get("/api/admin/ai-costs?days=7", headers=auth_headers(admin_user))).json()
            assert (await client.get("/api/admin/ai-costs", headers=auth_headers(member_user))).status_code == 403
        feature = next(row for row in report["by_feature"] if row["key"] == "pytest_report")
        assert feature["inr"] == 45 and feature["usd"] == 0.5
        assert any(row["key"] == str(member_user.id) for row in report["by_user"])
        assert report["prices"]["model_in_use"]
    finally:
        async with async_session() as db:
            await db.execute(delete(AiUsageEvent).where(AiUsageEvent.feature == "pytest_report"))
            await db.commit()


async def test_calls_made_before_the_meeting_existed_are_linked_to_it(member_user, make_meeting):
    # A bot ingest transcribes and writes notes, then creates the meeting.
    meeting = await make_meeting(member_user, "Ledger link", None)
    with patch("app.services.exchange_rate_service.usd_to_inr", new=AsyncMock(return_value=RATE)):
        usage_ledger.current.set(usage_ledger.Attribution())
        usage_ledger.attribute(user_id=member_user.id)
        usage_ledger.record_audio("pytest_link", "gnani", "prisma-v3.0", 60)
        await asyncio.sleep(0.3)  # written before the meeting exists
        usage_ledger.record_tokens("pytest_link", "gemini-3.5-flash", {"input_tokens": 10, "output_tokens": 5})
        usage_ledger.attribute(meeting_id=meeting.id)
        for _ in range(50):
            await asyncio.sleep(0.05)
            async with async_session() as db:
                rows = (await db.execute(select(AiUsageEvent).where(AiUsageEvent.feature == "pytest_link"))).scalars().all()
            if len(rows) == 2 and all(r.meeting_id == meeting.id for r in rows):
                break
    try:
        assert len(rows) == 2 and all(r.meeting_id == meeting.id for r in rows)
    finally:
        async with async_session() as db:
            await db.execute(delete(AiUsageEvent).where(AiUsageEvent.feature == "pytest_link"))
            await db.commit()
