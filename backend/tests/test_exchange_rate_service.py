import httpx
import pytest

from app.services import exchange_rate_service


class FakeResponse:
    def __init__(self, payload: dict | None = None, error: Exception | None = None):
        self.payload = payload or {}
        self.error = error

    def raise_for_status(self) -> None:
        if self.error:
            raise self.error

    def json(self) -> dict:
        return self.payload


class RoutingClient:
    """Answers each free source's URL with its own payload (or an error)."""

    def __init__(self, routes: dict[str, FakeResponse]):
        self.routes = routes
        self.requests: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url, *_args, **_kwargs) -> FakeResponse:
        self.requests.append(url)
        for needle, response in self.routes.items():
            if needle in url:
                return response
        return FakeResponse(error=httpx.ConnectError("down"))


@pytest.fixture(autouse=True)
def reset_exchange_rate_cache(monkeypatch):
    monkeypatch.setattr(exchange_rate_service, "_cached_rate", None)
    monkeypatch.setattr(exchange_rate_service, "_cache_deadline", 0.0)


def _install(monkeypatch, client):
    seen = {}

    def factory(**kwargs):
        seen.update(kwargs)
        return client

    monkeypatch.setattr(exchange_rate_service.httpx, "AsyncClient", factory)
    return seen


@pytest.mark.asyncio
async def test_first_free_source_is_used_and_reused(monkeypatch):
    client = RoutingClient({"er-api": FakeResponse({"rates": {"INR": 96.38}, "time_last_update_unix": 1791244951})})
    options = _install(monkeypatch, client)

    first = await exchange_rate_service.usd_to_inr()
    second = await exchange_rate_service.usd_to_inr()

    assert len(client.requests) == 1
    assert first["usd_to_inr"] == 96.38 and first["source"] == "open.er-api.com"
    assert first["quoted_at"].startswith("2026-")
    assert first["cached"] is False and second["cached"] is True
    # Providers move behind redirects; they must be followed.
    assert options["follow_redirects"] is True


@pytest.mark.asyncio
async def test_falls_through_to_the_next_free_sources(monkeypatch):
    client = RoutingClient({"frankfurter": FakeResponse({"date": "2026-10-06", "rates": {"INR": 96.42}})})
    _install(monkeypatch, client)
    quote = await exchange_rate_service.usd_to_inr()
    assert quote["usd_to_inr"] == 96.42 and quote["source"] == "Frankfurter (ECB)"
    assert quote["quoted_at"].startswith("2026-10-06")

    monkeypatch.setattr(exchange_rate_service, "_cached_rate", None)
    monkeypatch.setattr(exchange_rate_service, "_cache_deadline", 0.0)
    client = RoutingClient({"currency-api": FakeResponse({"date": "2026-10-06", "usd": {"inr": 96.418}})})
    _install(monkeypatch, client)
    quote = await exchange_rate_service.usd_to_inr()
    assert quote["usd_to_inr"] == 96.418 and quote["source"] == "fawazahmed0 currency-api"


@pytest.mark.asyncio
async def test_all_sources_down_uses_fallback_without_retrying(monkeypatch):
    client = RoutingClient({})
    _install(monkeypatch, client)

    first = await exchange_rate_service.usd_to_inr()
    second = await exchange_rate_service.usd_to_inr()

    assert len(client.requests) == len(exchange_rate_service.FREE_SOURCES)
    assert first["usd_to_inr"] == exchange_rate_service.FALLBACK_USD_TO_INR
    assert first["live"] is False and first["cached"] is False
    assert second["cached"] is True


def test_no_tatum_left():
    assert not hasattr(exchange_rate_service.settings, "tatum_api_key")
    assert all("tatum" not in url for _, url, *_ in exchange_rate_service.FREE_SOURCES)
