from unittest.mock import patch

from app.services import memory_retriever


def _usage() -> dict:
    return {"input_tokens": 1, "output_tokens": 1, "cache_tokens_read": 0, "cache_tokens_written": 0}


@patch("app.services.memory_retriever.generate_text")
@patch("app.services.memory_retriever.qdrant_service.search")
def test_short_follow_up_uses_recent_context_and_deduplicates_sources(mock_search, mock_generate):
    mock_search.return_value = [
        {"meeting_id": "one", "meeting_title": "Atlas review", "meeting_date": "2026-08-01", "content_type": "summary", "chunk_text": "Phased rollout."},
        {"meeting_id": "one", "meeting_title": "Atlas review", "meeting_date": "2026-08-01", "content_type": "decision", "chunk_text": "Risk was lower."},
    ]
    mock_generate.return_value = ("Risk was lower.", _usage())
    history = [
        {"role": "user", "content": "What did we decide about Project Atlas?"},
        {"role": "assistant", "content": "The team selected a phased rollout."},
    ]

    result = memory_retriever.answer_query("Why?", ["one"], history=history)

    retrieval_query = mock_search.call_args.args[0]
    assert "Project Atlas" in retrieval_query
    assert retrieval_query.endswith("Why?")
    assert len(result["sources"]) == 1
    assert "Conversation so far" in mock_generate.call_args.args[1]
    assert mock_generate.call_args.kwargs["thinking_budget"] == 256


@patch("app.services.memory_retriever.generate_text")
@patch("app.services.memory_retriever.qdrant_service.search")
def test_empty_meeting_ids_short_circuits_without_calling_qdrant(mock_search, mock_generate):
    mock_generate.return_value = ("I don't have any meetings to search.", _usage())

    result = memory_retriever.answer_query("Why?", [])

    mock_search.assert_not_called()
    assert result["sources"] == []
