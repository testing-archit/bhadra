"""Copy every vector from Qdrant into the Pinecone index, unchanged.

    PINECONE_API_KEY=... python scripts/migrate_qdrant_to_pinecone.py

Both stores hold multilingual-e5-large vectors (Pinecone Inference and the
local model produce identical ones — scripts/check_embedding_parity.py), so
nothing is re-embedded: each Qdrant point goes across with its vector and
payload, under the id pinecone_store expects. Idempotent — run it again
after switching VECTOR_STORE=pinecone to pick up anything indexed in between.
Qdrant itself is only read, so it stays as a rollback.

Then it checks the copy: per-namespace counts, and a sample of points each
queried back by its own vector must come first with score ~1.0.
"""

import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import settings  # noqa: E402
from app.services import pinecone_store, qdrant_service  # noqa: E402

COLLECTIONS = [qdrant_service.COMPANY_MEMORY_COLLECTION, qdrant_service.POLICY_COLLECTION]


def read_all(collection: str) -> list:
    client = qdrant_service.get_client()
    if not client.collection_exists(collection):
        return []
    points, offset = [], None
    while True:
        page, offset = client.scroll(
            collection_name=collection, limit=256, offset=offset, with_vectors=True, with_payload=True
        )
        points += page
        if offset is None:
            return points


def main() -> int:
    if not settings.pinecone_api_key:
        print("Set PINECONE_API_KEY first.")
        return 2
    print(f"Pinecone index: {settings.pinecone_index} at {pinecone_store.host()}")
    copied: dict[str, list] = {}
    for collection in COLLECTIONS:
        points = read_all(collection)
        vectors = [
            (qdrant_service.pinecone_id(str(p.id), p.payload or {}), p.vector, p.payload or {}) for p in points
        ]
        pinecone_store.upsert(collection, vectors)
        copied[collection] = vectors
        print(f"{collection}: copied {len(vectors)} vectors")

    # Serverless counts catch up within seconds to a minute.
    expected = {c: len(v) for c, v in copied.items() if v}
    for _ in range(18):
        namespaces = pinecone_store.stats().get("namespaces", {})
        counts = {c: namespaces.get(c, {}).get("vectorCount", 0) for c in expected}
        if all(counts[c] >= expected[c] for c in expected):
            break
        time.sleep(10)
    ok = True
    for collection, want in expected.items():
        have = counts[collection]
        print(f"{collection}: Pinecone has {have}, Qdrant had {want}")
        ok &= have >= want

    for collection, vectors in copied.items():
        for vid, values, _ in random.sample(vectors, min(5, len(vectors))):
            top = pinecone_store.query(collection, values, 1)
            hit = top[0] if top else {}
            good = hit.get("id") == vid or (hit.get("score", 0) > 0.999)
            print(f"  self-match {vid[:46]:46} -> {str(hit.get('id'))[:46]:46} {hit.get('score', 0):.4f} {'ok' if good else 'MISMATCH'}")
            ok &= good
    print("Migration verified." if ok else "Migration NOT verified — do not switch VECTOR_STORE yet.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
