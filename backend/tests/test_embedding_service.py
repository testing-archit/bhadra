"""Pinecone Inference path of embedding_service, with the HTTP call faked."""

from unittest.mock import patch

import httpx
import pytest

from app.config import settings
from app.services import embedding_service as es


@pytest.fixture
def pinecone_calls(monkeypatch):
    monkeypatch.setattr(settings, "pinecone_api_key", "pc-test")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        calls.append((request.headers, body))
        data = [{"values": [float(len(i["text"]))] * es.EMBEDDING_DIM} for i in body["inputs"]]
        return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 1}})

    real_client = httpx.Client
    with patch.object(es.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
        yield calls


def test_passages_are_batched_and_typed(pinecone_calls):
    vectors = es.embed_passages([f"chunk {i}" for i in range(200)])
    assert len(vectors) == 200 and len(vectors[0]) == es.EMBEDDING_DIM
    assert [len(body["inputs"]) for _, body in pinecone_calls] == [96, 96, 8]
    headers, body = pinecone_calls[0]
    assert headers["Api-Key"] == "pc-test" and headers["X-Pinecone-Api-Version"] == es.PINECONE_API_VERSION
    assert body["model"] == "multilingual-e5-large"
    assert body["parameters"] == {"input_type": "passage", "truncate": "END"}


def test_query_prefix_follows_the_parity_setting(pinecone_calls, monkeypatch):
    monkeypatch.setattr(es, "PINECONE_ADDS_PREFIX", True)
    es.embed_query("why postgres")
    monkeypatch.setattr(es, "PINECONE_ADDS_PREFIX", False)
    es.embed_query("why postgres")
    sent = [body["inputs"][0]["text"] for _, body in pinecone_calls]
    assert sent == ["why postgres", "query: why postgres"]
    assert all(body["parameters"]["input_type"] == "query" for _, body in pinecone_calls)


def test_pinecone_errors_surface_and_never_load_the_local_model(monkeypatch):
    monkeypatch.setattr(settings, "pinecone_api_key", "pc-test")
    real_client = httpx.Client
    transport = httpx.MockTransport(lambda r: httpx.Response(401, json={"error": {"message": "Invalid API key."}}))
    with patch.object(es.httpx, "Client", lambda **kw: real_client(transport=transport, **kw)), \
         patch.object(es, "_get_model", side_effect=AssertionError("local model loaded")):
        with pytest.raises(RuntimeError, match="Pinecone embeddings error 401"):
            es.embed_query("x")
