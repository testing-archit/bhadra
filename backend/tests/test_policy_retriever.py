from unittest.mock import patch

from app.data.company_policies import POLICY_CHUNKS
from app.services import policy_retriever


def _usage() -> dict:
    return {
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_tokens_read": 0,
        "cache_tokens_written": 0,
    }


@patch("app.services.policy_retriever.generate_text")
@patch("app.services.policy_retriever.qdrant_service.search_policies")
def test_policy_overview_uses_complete_catalogue(mock_search, mock_generate):
    mock_generate.return_value = ("Policy overview", _usage())

    result = policy_retriever.answer_query("What are the HR policies?")

    mock_search.assert_not_called()
    assert len(result["sources"]) == len(POLICY_CHUNKS)
    prompt = mock_generate.call_args.args[1]
    assert "Current date in India:" in prompt
    assert "Earned Leave" in prompt
    assert "Code of Conduct" in prompt
    assert mock_generate.call_args.kwargs["thinking_budget"] == 256
    assert mock_generate.call_args.kwargs["max_output_tokens"] == 1600


@patch("app.services.policy_retriever.generate_text")
@patch("app.services.policy_retriever.qdrant_service.search_policies")
def test_specific_policy_question_still_uses_semantic_search(mock_search, mock_generate):
    mock_search.return_value = [
        {
            "document": "Employee Handbook",
            "section": "Leave",
            "chunk_text": "Employees receive earned leave.",
            "score": 0.8,
        }
    ]
    mock_generate.return_value = ("Leave answer", _usage())

    result = policy_retriever.answer_query("How many earned leave days do I get?")

    mock_search.assert_called_once_with("How many earned leave days do I get?", top_k=6)
    assert len(result["sources"]) == 1


@patch("app.services.policy_retriever.generate_text")
@patch("app.services.policy_retriever.qdrant_service.search_policies", return_value=[])
def test_empty_vector_index_falls_back_to_curated_policy_catalogue(mock_search, mock_generate):
    mock_generate.return_value = ("The standard notice period is 30 days.", _usage())

    result = policy_retriever.answer_query("What is the resignation notice period?")

    assert result["sources"]
    assert result["sources"][0]["section"] == "Probation & Notice Period Policy — Notice Period"
    assert "30 days" in result["sources"][0]["text"]


@patch("app.services.policy_retriever.generate_text")
@patch("app.services.policy_retriever.qdrant_service.search_policies", side_effect=RuntimeError("offline"))
def test_unavailable_vector_store_falls_back_for_casual_leave(mock_search, mock_generate):
    mock_generate.return_value = ("Employees receive 6 days.", _usage())

    result = policy_retriever.answer_query("How many casual leave days do I get?")

    assert result["sources"]
    assert "Casual Leave" in result["sources"][0]["section"]
    assert "6 Casual Leave" in result["sources"][0]["text"]


@patch("app.services.policy_retriever._india_today", return_value="Wednesday, 12 August 2026")
@patch("app.services.policy_retriever.generate_text")
@patch("app.services.policy_retriever.qdrant_service.search_policies")
def test_next_holiday_uses_current_date_and_full_calendar(
    mock_search, mock_generate, mock_today
):
    mock_generate.return_value = ("The next holiday is Independence Day.", _usage())

    result = policy_retriever.answer_query("When is the next holiday?")

    mock_search.assert_not_called()
    assert len(result["sources"]) == 2
    prompt = mock_generate.call_args.args[1]
    assert "Current date in India: Wednesday, 12 August 2026" in prompt
    assert "Independence Day — Saturday, 15-Aug-2026" in prompt
    assert "Raksha Bandhan — Friday, 28-Aug-2026" in prompt
    mock_today.assert_called_once()
