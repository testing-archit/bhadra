from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from google import genai
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
    config = client.models.generate_content.call_args.kwargs['config']
    assert config.thinking_config.thinking_budget is None
    assert config.thinking_config.thinking_level == 'LOW'


def test_strict_board_schema_reaches_api_as_json_schema_and_validates_reply():
    """Exercise the actual SDK serializer that rejected live board commands."""
    import json
    from app.services.board_commands import BoardCommandPlan

    requests = []
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        config = body['generationConfig']
        assert 'responseSchema' not in config
        assert config['thinkingConfig'] == {'thinkingLevel':'MINIMAL'}
        assert 'temperature' not in config
        assert config['responseJsonSchema']['$defs']['BoardOperation']['additionalProperties'] is False
        # A provider response must still pass our strict local schema.
        reply = {'message': 'Added', 'operations': [{'op': 'create_node', 'title': 'Release check', 'unexpected': True}]}
        return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': json.dumps(reply)}]}}]})

    client = genai.Client(api_key='test-key', http_options={'client_args': {'transport': httpx.MockTransport(respond)}})
    with patch.object(gemini_service, '_client', return_value=client), \
            patch.object(gemini_service.usage_ledger, 'record_tokens') as billed, \
            pytest.raises(ValidationError):
        gemini_service.generate_structured('system', 'synthetic board command', BoardCommandPlan, attempts=1,
                                          model='gemini-3.5-flash-lite', thinking_budget=0)
    assert len(requests) == 1
    billed.assert_called_once()


def test_legacy_models_keep_numeric_thinking_budgets():
    assert gemini_service._thinking_config('gemini-2.5-flash-lite', 0).thinking_budget == 0
    assert gemini_service._thinking_config('gemini-3.5-flash-lite', None) is None
    assert gemini_service._thinking_config('gemini-3.8-flash', 256).thinking_level == 'LOW'
