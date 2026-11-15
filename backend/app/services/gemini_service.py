import logging

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.services import usage_ledger

logger = logging.getLogger(__name__)

# A structured answer that comes back cut off or malformed gets one more try:
# Gemini occasionally loops inside a JSON string until it runs out of output
# tokens, and the same prompt again almost always comes back clean.
STRUCTURED_ATTEMPTS = 2


def _client(timeout_seconds: float | None = None) -> genai.Client:
    # google-genai owns an underlying httpx client. Caching it globally caused
    # intermittent "client has been closed" failures after request/thread
    # teardown. A fresh lightweight SDK wrapper per generation keeps the
    # transport lifecycle local to the call and is safe across worker threads.
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    options = {"timeout": int(timeout_seconds * 1000), "retry_options": {"attempts": 1}} if timeout_seconds else None
    return genai.Client(api_key=settings.gemini_api_key, **({"http_options": options} if options else {}))


def usage_dict(response) -> dict:
    usage = response.usage_metadata
    return {
        "input_tokens": getattr(usage, "prompt_token_count", 0) or 0,
        # Thinking is billed as output and shares max_output_tokens with the answer.
        "output_tokens": (getattr(usage, "candidates_token_count", 0) or 0) + (getattr(usage, "thoughts_token_count", 0) or 0),
        "cache_tokens_read": getattr(usage, "cached_content_token_count", 0) or 0,
        "cache_tokens_written": 0,
    }


def generate_text(
    system_instruction: str,
    prompt: str,
    *,
    max_output_tokens: int = 1000,
    temperature: float = 0.1,
    thinking_budget: int | None = None,
    feature: str = "other",
    model: str | None = None,
    timeout_seconds: float | None = None,
) -> tuple[str, dict]:
    thinking_config = (
        types.ThinkingConfig(thinking_budget=thinking_budget)
        if thinking_budget is not None
        else None
    )
    client = _client(timeout_seconds) if timeout_seconds else _client()
    try:
        response = client.models.generate_content(
            model=model or settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
                thinking_config=thinking_config,
            ),
        )
    finally:
        client.close()
    usage = usage_dict(response)
    usage_ledger.record_tokens(feature, model or settings.gemini_model, usage)
    return response.text or "", usage


def _json_part(text: str) -> str:
    """The JSON object in a reply that wrapped it in prose or code fences
    ("Here is the JSON: {...}")."""
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else text


def generate_structured(
    system_instruction: str,
    prompt: str,
    schema: type[BaseModel],
    *,
    max_output_tokens: int = 2000,
    feature: str = "other",
    model: str | None = None,
    timeout_seconds: float | None = None,
    attempts: int = STRUCTURED_ATTEMPTS,
    thinking_budget: int | None = None,
) -> tuple[BaseModel, dict]:
    if attempts < 1:
        raise ValueError("At least one generation attempt is required")
    budget = max_output_tokens
    for attempt in range(1, attempts + 1):
        client = _client(timeout_seconds) if timeout_seconds else _client()
        try:
            response = client.models.generate_content(
                model=model or settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=schema,
                    max_output_tokens=budget,
                    temperature=0.1,
                    thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget) if thinking_budget is not None else None,
                ),
            )
        finally:
            client.close()
        usage = usage_dict(response)
        # Recorded before parsing: a response that fails validation was still paid for.
        usage_ledger.record_tokens(feature, model or settings.gemini_model, usage)
        try:
            parsed = response.parsed
            if not isinstance(parsed, schema):
                parsed = schema.model_validate_json(_json_part(response.text or "{}"))
            return parsed, usage
        except ValidationError:
            finish = getattr((response.candidates or [None])[0], "finish_reason", None)
            if attempt == attempts:
                raise
            # Thinking counts against the output budget, so a cut-off answer
            # is retried with room to finish rather than cut off again.
            if "MAX_TOKENS" in str(finish):
                budget *= 2
            logger.warning(
                "Gemini %s returned unusable JSON (finish %s, %s output tokens); retrying with %s",
                feature, finish, usage["output_tokens"], budget,
            )
    raise AssertionError("unreachable")
