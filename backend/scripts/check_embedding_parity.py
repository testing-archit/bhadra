"""Check that Pinecone Inference's multilingual-e5-large gives the same vectors
as the local fastembed model, so Qdrant's existing points stay searchable
after production switches to Pinecone (no re-index).

    PINECONE_API_KEY=... python scripts/check_embedding_parity.py

Prints the cosine similarity between local and Pinecone vectors for each
sample, with Pinecone given the bare text and the already-prefixed text. The
variant near 1.000 tells you how Pinecone handles E5's "passage: "/"query: "
prefixes — set embedding_service.PINECONE_ADDS_PREFIX to match. Anything
below ~0.99 for both means the models differ and Qdrant must be re-indexed
(scripts/reindex_meetings.py) after switching.
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import settings  # noqa: E402
from app.services import embedding_service as es  # noqa: E402

SAMPLES = [
    ("passage", "Archit tum SIP AUM wala calculation check kar lena by Friday"),
    ("passage", "We decided to use PostgreSQL because SQL is better for reporting."),
    ("query", "why did we choose PostgreSQL?"),
    ("query", "Friday tak kaunsa task pending hai"),
]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def main() -> int:
    if not settings.pinecone_api_key:
        print("Set PINECONE_API_KEY first.")
        return 2
    model = es._get_model()
    worst = {True: 1.0, False: 1.0}
    for input_type, text in SAMPLES:
        prefix = es._PASSAGE_PREFIX if input_type == "passage" else es._QUERY_PREFIX
        local = next(iter(model.embed([prefix + text]))).tolist()
        for adds_prefix in (True, False):
            es.PINECONE_ADDS_PREFIX = adds_prefix
            remote = es._pinecone_embed([text], input_type, prefix)[0]
            score = cosine(local, remote)
            worst[adds_prefix] = min(worst[adds_prefix], score)
            label = "bare text    " if adds_prefix else "prefixed text"
            print(f"{input_type:8} {label} cos={score:.4f}  {text[:50]}")
    print(f"\nworst, Pinecone adds prefix (bare text sent): {worst[True]:.4f}")
    print(f"worst, we add prefix (prefixed text sent):     {worst[False]:.4f}")
    best = max(worst, key=worst.get)
    if worst[best] < 0.99:
        print("Neither matches: re-index Qdrant after switching.")
        return 1
    print(f"Use PINECONE_ADDS_PREFIX = {best}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
