"""Gnani Evon v3.3, the Indic LLM, through any OpenAI-compatible server.

Evon is open-weights with no hosted Gnani API, so it runs wherever the team
hosts it (EVON_URL). Callers fall back to Gemini when it isn't configured
or doesn't answer in time. Self-hosted, so the cost ledger isn't charged."""
import httpx

from app.config import settings


def configured() -> bool:
    return bool(settings.evon_url)


async def chat(system: str, user: str, *, max_tokens: int = 220, temperature: float = 0.4, timeout: float = 8.0) -> str:
    headers = {"Authorization": f"Bearer {settings.evon_api_key}"} if settings.evon_api_key else {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=3.0)) as client:
        response = await client.post(
            settings.evon_url.rstrip("/") + "/v1/chat/completions",
            headers=headers,
            json={"model": settings.evon_model, "max_tokens": max_tokens, "temperature": temperature,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        )
    response.raise_for_status()
    text = (response.json()["choices"][0]["message"].get("content") or "").strip()
    if not text:
        raise RuntimeError("Evon returned an empty reply")
    return text
