"""qdrant_service in VECTOR_STORE=pinecone mode routes every operation to
pinecone_store, with ids that line up with migrated Qdrant points."""

from unittest.mock import patch

import pytest

from app.config import settings
from app.services import pinecone_store, qdrant_service


@pytest.fixture
def pinecone_mode(monkeypatch):
    monkeypatch.setattr(settings, "vector_store", "pinecone")
    with patch.object(qdrant_service, "embed_passages", side_effect=lambda texts: [[0.1] * 1024 for _ in texts]), \
         patch.object(qdrant_service, "embed_query", return_value=[0.2] * 1024), \
         patch.object(qdrant_service, "get_client", side_effect=AssertionError("Qdrant used in pinecone mode")):
        yield


def test_upsert_uses_meeting_prefixed_qdrant_ids(pinecone_mode):
    with patch.object(pinecone_store, "upsert") as upsert:
        qdrant_service.upsert_meeting("m-1", "Weekly", "2026-10-07", "Summary", "", [], [{"task": "Ship it"}])
    namespace, vectors = upsert.call_args.args
    assert namespace == "company_memory"
    ids = [vid for vid, _, _ in vectors]
    assert ids == [f"m-1#{qdrant_service._point_id('m-1_summary')}", f"m-1#{qdrant_service._point_id('m-1_task_0')}"]
    assert vectors[0][2]["meeting_title"] == "Weekly" and vectors[0][2]["content_type"] == "summary"


def test_search_builds_pinecone_filter(pinecone_mode):
    with patch.object(pinecone_store, "query", return_value=[{"id": "x", "score": 0.9}]) as query:
        hits = qdrant_service.search("q", top_k=4, content_type="summary", meeting_ids=["a", "b"])
    assert hits == [{"id": "x", "score": 0.9}]
    namespace, _, top_k, flt = query.call_args.args
    assert (namespace, top_k) == ("company_memory", 4)
    assert flt == {"content_type": {"$eq": "summary"}, "meeting_id": {"$in": ["a", "b"]}}


def test_delete_rename_and_policies(pinecone_mode):
    with patch.object(pinecone_store, "delete_meeting") as delete, \
         patch.object(pinecone_store, "set_meeting_metadata") as rename, \
         patch.object(pinecone_store, "query", return_value=[]) as query:
        qdrant_service.delete_meeting("m-1")
        qdrant_service.update_meeting_title("m-1", "New title")
        qdrant_service.search_policies("leave policy", top_k=3)
    delete.assert_called_once_with("company_memory", "m-1")
    rename.assert_called_once_with("company_memory", "m-1", {"meeting_title": "New title"})
    assert query.call_args.args[0] == "company_policy" and query.call_args.args[2] == 3


def test_filter_for_drops_empty_conditions():
    assert pinecone_store.filter_for({"department": None, "content_type": ""}) is None
    assert pinecone_store.filter_for({}, []) == {"meeting_id": {"$in": []}}
