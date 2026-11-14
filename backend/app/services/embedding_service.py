import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# multilingual-e5-large is 1024-dim and covers ~100 languages including Hindi,
# which matters here since transcripts are Hindi/English code-switched.
# (BAAI/bge-m3 would also fit and is arguably stronger, but fastembed's
# TextEmbedding API doesn't support its multi-vector dense+sparse+colbert
# output format at all — not usable via this library regardless of network
# conditions.)
#
# Two engines produce the *same* model's vectors, so Qdrant's existing points
# stay valid whichever one runs:
#  * Pinecone Inference (PINECONE_API_KEY set) — hosted, free up to 5M
#    tokens/month, far more than a few meetings a day need. This is what
#    production uses: the local model held ~2.5 GB of the 4 GB VM for good,
#    which pushed the notetaker's Chromium into swap and broke up recordings
#    (2026-10-07 post-mortem).
#  * fastembed (ONNX, local) — no key needed; for development and as the
#    old behaviour. Imported lazily so production never loads it.
EMBEDDING_DIM = 1024

# E5-family models are trained with literal "query: "/"passage: " prefixes
# distinguishing what's being embedded, and skipping this measurably hurts
# their retrieval quality. Non-E5 sentence-transformers models were not
# trained with this convention, so applying it to them would just add noise —
# only prefix when the configured model is actually E5.
_IS_E5_MODEL = "e5" in settings.embedding_model.lower()
_PASSAGE_PREFIX = "passage: " if _IS_E5_MODEL else ""
_QUERY_PREFIX = "query: " if _IS_E5_MODEL else ""

PINECONE_EMBED_URL = "https://api.pinecone.io/embed"
PINECONE_API_VERSION = "2026-07"
PINECONE_MODEL = "multilingual-e5-large"
# Pinecone's per-request input cap for this model.
PINECONE_BATCH = 96
# Pinecone applies the E5 prefix itself from input_type; sending ours too
# would embed "passage: passage: …". Verified against fastembed's vectors
# with scripts/check_embedding_parity.py before switching production over.
PINECONE_ADDS_PREFIX = True

_model = None


def _use_pinecone() -> bool:
    return bool(settings.pinecone_api_key)


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        _model = TextEmbedding(model_name=settings.embedding_model, cache_dir=settings.embedding_cache_dir)
    return _model


def _pinecone_embed(texts: list[str], input_type: str, prefix: str) -> list[list[float]]:
    if not PINECONE_ADDS_PREFIX:
        texts = [prefix + t for t in texts]
    vectors: list[list[float]] = []
    with httpx.Client(timeout=30.0) as client:
        for start in range(0, len(texts), PINECONE_BATCH):
            batch = texts[start : start + PINECONE_BATCH]
            response = client.post(
                PINECONE_EMBED_URL,
                headers={"Api-Key": settings.pinecone_api_key, "X-Pinecone-Api-Version": PINECONE_API_VERSION},
                json={
                    "model": PINECONE_MODEL,
                    "inputs": [{"text": t} for t in batch],
                    # The local model truncates at 512 tokens too.
                    "parameters": {"input_type": input_type, "truncate": "END"},
                },
            )
            if not response.is_success:
                raise RuntimeError(f"Pinecone embeddings error {response.status_code}: {response.text[:200]}")
            body = response.json()
            vectors.extend(item["values"] for item in body["data"])
            logger.debug("Pinecone embedded %d inputs, %s tokens", len(batch), body.get("usage", {}).get("total_tokens"))
    return vectors


def embed_passages(texts: list[str]) -> list[list[float]]:
    """For text being indexed/upserted (meeting chunks, policy chunks)."""
    if not texts:
        return []
    if _use_pinecone():
        return _pinecone_embed(texts, "passage", _PASSAGE_PREFIX)
    return [vec.tolist() for vec in _get_model().embed([_PASSAGE_PREFIX + t for t in texts])]


def embed_query(text: str) -> list[float]:
    """For a search query being matched against already-indexed passages."""
    if _use_pinecone():
        return _pinecone_embed([text], "query", _QUERY_PREFIX)[0]
    return [vec.tolist() for vec in _get_model().embed([_QUERY_PREFIX + text])][0]
