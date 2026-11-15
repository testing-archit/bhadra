from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ValidationError

from app.services import gemini_service


class _Notes(BaseModel):
    title: str


def _response(text: str, parsed=None) -> SimpleNamespace:
    usage = SimpleNamespace(prompt_token_count=100, candidates_token_count=50, thoughts_token_count=30, cached_content_token_count=0)
    return SimpleNamespace(text=text, parsed=parsed, usage_metadata=usage, candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")])


def _client(*responses) -> MagicMock:
    client = MagicMock()
    client.models.generate_content.side_effect = list(responses)
    return client


def test_thinking_tokens_count_as_output():
    assert gemini_service.usage_dict(_response("{}"))["output_tokens"] == 80


def test_cut_off_json_is_retried_once_and_both_calls_are_billed():
    client = _client(_response('{"title": "Test flight, evidence: [S40, S46'), _response('{"title": "TestFlight"}'))
    with patch.object(gemini_service, "_client", return_value=client), \
            patch.object(gemini_service.usage_ledger, "record_tokens") as billed:
        parsed, _ = gemini_service.generate_structured("system", "prompt", _Notes, feature="meeting_notes")
    assert parsed.title == "TestFlight"
    assert billed.call_count == 2


def test_gives_up_after_the_retry():
    broken = '{"title": "never closed'
    client = _client(_response(broken), _response(broken))
    with patch.object(gemini_service, "_client", return_value=client), \
            patch.object(gemini_service.usage_ledger, "record_tokens"), pytest.raises(ValidationError):
        gemini_service.generate_structured("system", "prompt", _Notes)
    assert client.models.generate_content.call_count == 2


def test_json_wrapped_in_prose_is_used_and_a_cut_off_retry_gets_more_room():
    # Production: the contradiction check got "Here is the JSON" and failed.
    client = _client(_response('{"title": "cut'), _response('Here is the JSON:\n```json\n{"title": "Budget"}\n```'))
    with patch.object(gemini_service, "_client", return_value=client), \
            patch.object(gemini_service.usage_ledger, "record_tokens"):
        parsed, _ = gemini_service.generate_structured("system", "prompt", _Notes, max_output_tokens=250)
    assert parsed.title == "Budget"
    budgets = [call.kwargs["config"].max_output_tokens for call in client.models.generate_content.call_args_list]
    assert budgets == [250, 500]


def test_interactive_generation_limits_retry_and_thinking():
    client=_client(_response('{"title":"Ready"}'))
    with patch.object(gemini_service,'_client',return_value=client) as factory, patch.object(gemini_service.usage_ledger,'record_tokens'):
        gemini_service.generate_structured('system','prompt',_Notes,timeout_seconds=15,attempts=1,thinking_budget=0)
    factory.assert_called_once_with(15)
    assert client.models.generate_content.call_args.kwargs['config'].thinking_config.thinking_budget==0
