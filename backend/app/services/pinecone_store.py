"""Pinecone serverless index as the vector store (VECTOR_STORE=pinecone).

qdrant_service keeps the public API and dispatches here, so callers don't
change. One index (PINECONE_INDEX, 1024-d cosine, same scores as Qdrant's
cosine — calibrated thresholds still hold); each Qdrant collection is a
namespace of the same name.

Vector ids are "<meeting_id>#<uuid5>" for meeting chunks — the uuid5 is the
Qdrant point id, so vectors copied by scripts/migrate_qdrant_to_pinecone.py
and later re-indexes overwrite each other instead of duplicating — and the
plain uuid5 for policy chunks.

Plain REST over httpx; the data-plane shapes below were exercised against a
live index with API version 2025-04 (2026-07 reworked index creation).
"""

import time

import httpx

from app.config import settings

API_VERSION = "2025-04"
CONTROL_URL = "https://api.pinecone.io"
# Requests are capped at 2 MB; a 1024-float vector is ~20 KB of JSON plus up
# to 1.5 KB of chunk text.
UPSERT_BATCH = 50

_host: str | None = None


def _headers() -> dict:
    return {"Api-Key": settings.pinecone_api_key, "X-Pinecone-Api-Version": API_VERSION}


def _check(response: httpx.Response, what: str) -> dict:
    if not response.is_success:
        raise RuntimeError(f"Pinecone {what} error {response.status_code}: {response.text[:200]}")
    return response.json() if response.content else {}


def host() -> str:
    """The index's data-plane URL, creating the index the first time."""
    global _host
    if _host:
        return _host
    name = settings.pinecone_index
    with httpx.Client(timeout=30.0, headers=_headers()) as client:
        response = client.get(f"{CONTROL_URL}/indexes/{name}")
        if response.status_code == 404:
            _check(
                client.post(
                    f"{CONTROL_URL}/indexes",
                    json={
                        "name": name,
                        "dimension": 1024,
                        "metric": "cosine",
                        # The only region on Pinecone's free plan.
                        "spec": {"serverless": {"cloud": "aws", "region": "us-east-1"}},
                        "deletion_protection": "enabled",
                    },
                ),
                "create index",
            )
            for _ in range(30):
                time.sleep(2)
                response = client.get(f"{CONTROL_URL}/indexes/{name}")
                if response.is_success and response.json().get("status", {}).get("ready"):
                    break
        info = _check(response, "describe index")
    _host = f"https://{info['host']}"
    return _host


def _post(path: str, body: dict, what: str) -> dict:
    with httpx.Client(timeout=30.0, headers=_headers()) as client:
        return _check(client.post(f"{host()}{path}", json=body), what)


def _clean(metadata: dict) -> dict:
    # Pinecone rejects null metadata values.
    return {k: v for k, v in (metadata or {}).items() if v is not None}


def upsert(namespace: str, vectors: list[tuple[str, list[float], dict]]) -> None:
    for start in range(0, len(vectors), UPSERT_BATCH):
        batch = vectors[start : start + UPSERT_BATCH]
        _post(
            "/vectors/upsert",
            {
                "namespace": namespace,
                "vectors": [{"id": vid, "values": values, "metadata": _clean(meta)} for vid, values, meta in batch],
            },
            "upsert",
        )


def query(namespace: str, vector: list[float], top_k: int, flt: dict | None = None) -> list[dict]:
    body = {"namespace": namespace, "vector": vector, "topK": top_k, "includeMetadata": True}
    if flt:
        body["filter"] = flt
    matches = _post("/query", body, "query").get("matches", [])
    return [{"id": m["id"], "score": m["score"], **(m.get("metadata") or {})} for m in matches]


def delete_meeting(namespace: str, meeting_id: str) -> None:
    _post("/vectors/delete", {"namespace": namespace, "filter": {"meeting_id": {"$eq": meeting_id}}}, "delete")


def _ids_with_prefix(namespace: str, prefix: str) -> list[str]:
    ids: list[str] = []
    token = None
    with httpx.Client(timeout=30.0, headers=_headers()) as client:
        while True:
            params = {"namespace": namespace, "prefix": prefix}
            if token:
                params["paginationToken"] = token
            page = _check(client.get(f"{host()}/vectors/list", params=params), "list")
            ids += [v["id"] for v in page.get("vectors", [])]
            token = (page.get("pagination") or {}).get("next")
            if not token:
                return ids


def set_meeting_metadata(namespace: str, meeting_id: str, metadata: dict) -> None:
    for vid in _ids_with_prefix(namespace, f"{meeting_id}#"):
        _post("/vectors/update", {"namespace": namespace, "id": vid, "setMetadata": _clean(metadata)}, "update")


def stats() -> dict:
    return _post("/describe_index_stats", {}, "stats")


def filter_for(conditions: dict[str, str], meeting_ids: list[str] | None = None) -> dict | None:
    flt: dict = {k: {"$eq": v} for k, v in conditions.items() if v}
    if meeting_ids is not None:
        flt["meeting_id"] = {"$in": meeting_ids}
    return flt or None
