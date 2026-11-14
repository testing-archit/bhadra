import uuid

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.config import settings
from app.services import pinecone_store
from app.services.embedding_service import EMBEDDING_DIM, embed_passages, embed_query

COMPANY_MEMORY_COLLECTION = "company_memory"
POLICY_COLLECTION = "company_policy"
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200
UPSERT_BATCH_SIZE = 90

# Deterministic point IDs: Qdrant only accepts unsigned ints or UUIDs, unlike
# Pinecone's free-form string ids. uuid5 over a fixed namespace + our own
# composite key (e.g. "{meeting_id}_decision_0") gives the same idempotent
# re-upsert-by-id behaviour the old Pinecone code relied on.
_ID_NAMESPACE = uuid.UUID("6f7d6e0a-6d1a-4b8e-9f0a-3d6c9d9a6b3e")


def _point_id(ref: str) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, ref))


_client: QdrantClient | None = None


def _off() -> bool:
    """VECTOR_STORE=none: no vector database on this server. Indexing is a
    no-op and searches raise, so callers use their fallbacks (memory answers
    from recent meetings, the policy assistant from keyword matching)."""
    return settings.vector_store == "none"


class VectorSearchOff(RuntimeError):
    pass


def _on_pinecone() -> bool:
    """VECTOR_STORE=pinecone: the same collections live as namespaces of a
    Pinecone index (see pinecone_store). The public API below is unchanged."""
    return settings.vector_store == "pinecone"


def pinecone_id(point_id: str, payload: dict) -> str:
    meeting_id = payload.get("meeting_id")
    return f"{meeting_id}#{point_id}" if meeting_id else str(point_id)


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    return _client


def ensure_collections() -> None:
    if _off():
        return
    if _on_pinecone():
        return
    client = get_client()
    for name in (COMPANY_MEMORY_COLLECTION, POLICY_COLLECTION):
        if not client.collection_exists(name):
            client.create_collection(
                collection_name=name,
                vectors_config=qm.VectorParams(size=EMBEDDING_DIM, distance=qm.Distance.COSINE),
            )


def _chunk_text(text: str) -> list[str]:
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start = end - CHUNK_OVERLAP
    return chunks


def _upsert_points(collection: str, points: list[qm.PointStruct]) -> None:
    if _off():
        return
    if not points:
        return
    if _on_pinecone():
        pinecone_store.upsert(
            collection, [(pinecone_id(str(p.id), p.payload or {}), p.vector, p.payload or {}) for p in points]
        )
        return
    client = get_client()
    ensure_collections()
    for i in range(0, len(points), UPSERT_BATCH_SIZE):
        client.upsert(collection_name=collection, points=points[i : i + UPSERT_BATCH_SIZE])


def upsert_meeting(
    meeting_id: str,
    meeting_title: str,
    meeting_date: str,
    summary: str,
    transcript: str,
    decisions: list[dict],
    tasks: list[dict],
    department: str | None = None,
    risks: list[dict] | None = None,
) -> None:
    if _off():
        return
    dept = department or "unassigned"
    records: list[tuple[str, str, dict]] = []  # (ref_id, chunk_text, extra_payload)

    if summary:
        records.append((f"{meeting_id}_summary", summary, {"content_type": "summary"}))

    for i, decision in enumerate(decisions):
        text = f"Decision: {decision.get('decision', '')}\nReason: {decision.get('reason', '')}"
        alternatives = decision.get("alternatives") or []
        if alternatives:
            text += f"\nRejected alternatives: {', '.join(alternatives)}"
        records.append(
            (f"{meeting_id}_decision_{i}", text, {"content_type": "decision", "project": decision.get("project") or ""})
        )

    for i, task in enumerate(tasks):
        text = f"Task: {task.get('task', '')}"
        if task.get("assignedTo"):
            text += f" (assigned to {task['assignedTo']})"
        if task.get("dueDate"):
            text += f" due {task['dueDate']}"
        if task.get("priority"):
            text += f" [{task['priority']} priority]"
        records.append(
            (f"{meeting_id}_task_{i}", text, {"content_type": "task", "project": task.get("project") or ""})
        )

    for i, risk in enumerate(risks or []):
        text = f"Risk: {risk.get('risk', '')}"
        if risk.get("severity"):
            text += f" [{risk['severity']} severity]"
        records.append(
            (f"{meeting_id}_risk_{i}", text, {"content_type": "risk", "project": risk.get("project") or ""})
        )

    for i, chunk in enumerate(_chunk_text(transcript)):
        records.append((f"{meeting_id}_transcript_{i}", chunk, {"content_type": "transcript"}))

    if not records:
        return

    vectors = embed_passages([text for _, text, _ in records])
    points = [
        qm.PointStruct(
            id=_point_id(ref_id),
            vector=vector,
            payload={
                "chunk_text": text,
                "meeting_id": meeting_id,
                "meeting_title": meeting_title,
                "meeting_date": meeting_date,
                "department": dept,
                **extra,
            },
        )
        for (ref_id, text, extra), vector in zip(records, vectors)
    ]
    _upsert_points(COMPANY_MEMORY_COLLECTION, points)


def update_meeting_title(meeting_id: str, title: str) -> None:
    if _off():
        return
    if _on_pinecone():
        pinecone_store.set_meeting_metadata(COMPANY_MEMORY_COLLECTION, meeting_id, {"meeting_title": title})
        return
    ensure_collections()
    get_client().set_payload(
        collection_name=COMPANY_MEMORY_COLLECTION,
        payload={"meeting_title": title},
        points=qm.Filter(
            must=[qm.FieldCondition(key="meeting_id", match=qm.MatchValue(value=meeting_id))]
        ),
    )


def delete_meeting(meeting_id: str) -> None:
    """Remove every vector chunk derived from a meeting."""
    if _off():
        return
    if _on_pinecone():
        pinecone_store.delete_meeting(COMPANY_MEMORY_COLLECTION, meeting_id)
        return
    ensure_collections()
    get_client().delete(
        collection_name=COMPANY_MEMORY_COLLECTION,
        points_selector=qm.Filter(
            must=[qm.FieldCondition(key="meeting_id", match=qm.MatchValue(value=meeting_id))]
        ),
        wait=True,
    )


def replace_meeting(
    meeting_id: str,
    meeting_title: str,
    meeting_date: str,
    summary: str,
    transcript: str,
    decisions: list[dict],
    tasks: list[dict],
    department: str | None = None,
    risks: list[dict] | None = None,
) -> None:
    """Rebuild a meeting index after an extracted fact is edited/deleted."""
    if _off():
        return
    delete_meeting(meeting_id)
    upsert_meeting(
        meeting_id,
        meeting_title,
        meeting_date,
        summary,
        transcript,
        decisions,
        tasks,
        department,
        risks,
    )


def _build_filter(conditions: dict[str, str], meeting_ids: list[str] | None = None) -> qm.Filter | None:
    must = [qm.FieldCondition(key=k, match=qm.MatchValue(value=v)) for k, v in conditions.items() if v]
    if meeting_ids is not None:
        must.append(qm.FieldCondition(key="meeting_id", match=qm.MatchAny(any=meeting_ids)))
    return qm.Filter(must=must) if must else None


def search(
    query_text: str,
    top_k: int = 5,
    department: str | None = None,
    content_type: str | None = None,
    meeting_ids: list[str] | None = None,
) -> list[dict]:
    """`meeting_ids`, when given, restricts hits to that exact set of meeting
    ids (attendee-scoped chat). `None` means unrestricted by meeting id —
    distinct from an empty list, which callers should treat as "search
    nothing" and short-circuit before ever calling this."""
    if _off():
        raise VectorSearchOff("Vector search is off on this server")
    if _on_pinecone():
        return pinecone_store.query(
            COMPANY_MEMORY_COLLECTION,
            embed_query(query_text),
            top_k,
            pinecone_store.filter_for({"department": department, "content_type": content_type}, meeting_ids),
        )
    ensure_collections()
    query_vector = embed_query(query_text)
    query_filter = _build_filter({"department": department, "content_type": content_type}, meeting_ids)

    hits = get_client().query_points(
        collection_name=COMPANY_MEMORY_COLLECTION,
        query=query_vector,
        query_filter=query_filter,
        limit=top_k,
    ).points

    return [{"id": str(hit.id), "score": hit.score, **(hit.payload or {})} for hit in hits]


def upsert_policy_chunks(chunks: list[dict]) -> None:
    """chunks: [{id, document, section, text}]. Re-running ingestion after an
    edit just overwrites the same deterministic ids in place."""
    if _off():
        return
    if not chunks:
        return
    vectors = embed_passages([c["text"] for c in chunks])
    points = [
        qm.PointStruct(
            id=_point_id(c["id"]),
            vector=vector,
            payload={"chunk_text": c["text"], "document": c["document"], "section": c["section"]},
        )
        for c, vector in zip(chunks, vectors)
    ]
    _upsert_points(POLICY_COLLECTION, points)


def search_policies(query_text: str, top_k: int = 6) -> list[dict]:
    if _off():
        raise VectorSearchOff("Vector search is off on this server")
    if _on_pinecone():
        return pinecone_store.query(POLICY_COLLECTION, embed_query(query_text), top_k)
    ensure_collections()
    query_vector = embed_query(query_text)
    hits = get_client().query_points(
        collection_name=POLICY_COLLECTION,
        query=query_vector,
        limit=top_k,
    ).points
    return [{"id": str(hit.id), "score": hit.score, **(hit.payload or {})} for hit in hits]


# Same calibration reference as contradiction_service: unrelated summaries
# scored ~0.10-0.25 in practice, so anything below this is noise, not a
# genuine topical match — better to show nothing than a false "related" link.
RELATED_SCORE_THRESHOLD = 0.35


def find_related_meetings(
    query_text: str,
    exclude_meeting_id: str,
    department: str | None = None,
    top_k: int = 3,
) -> list[dict]:
    """Surfaces other meetings that discussed similar topics, for the
    "related past discussions" panel on a meeting's detail page. Searches
    summary chunks only (one per meeting) so results dedupe naturally rather
    than one meeting crowding the list with several transcript chunks."""
    if _off():
        return []
    if not query_text:
        return []
    hits = search(query_text, top_k=top_k + 3, department=department, content_type="summary")
    related = []
    for hit in hits:
        if hit.get("meeting_id") == exclude_meeting_id:
            continue
        if (hit.get("score") or 0) < RELATED_SCORE_THRESHOLD:
            continue
        related.append(
            {
                "meeting_id": hit.get("meeting_id"),
                "meeting_title": hit.get("meeting_title"),
                "meeting_date": hit.get("meeting_date"),
                "score": hit.get("score"),
            }
        )
        if len(related) >= top_k:
            break
    return related
