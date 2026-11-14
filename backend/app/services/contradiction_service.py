import logging

from pydantic import BaseModel

from app.services import qdrant_service
from app.services.gemini_service import generate_structured

SIMILARITY_THRESHOLD = 0.4
logger = logging.getLogger(__name__)


class ContradictionResult(BaseModel):
    conflicts: bool
    note: str = ""


CONTRADICTION_SYSTEM_PROMPT = """Check whether a new company decision conflicts with or supersedes a past decision. A conflict reverses, contradicts, or materially changes a decision on the same topic; related or more detailed decisions are not automatically conflicts. If there is a conflict, write one sentence naming the past meeting and date."""


def check_for_contradiction(decision_text: str, department: str | None, meeting_ids: list[str] | None = None) -> dict:
    """`meeting_ids` limits the past decisions compared against: the note
    names the past meeting and quotes its decision to everyone in the new
    one, so it must only draw on meetings they may hear about."""
    if meeting_ids is not None and not meeting_ids:
        return {"note": None, "usage": None}
    try:
        hits = qdrant_service.search(
            decision_text, top_k=3, department=department, content_type="decision", meeting_ids=meeting_ids
        )
    except Exception:
        logger.exception("Skipping contradiction lookup because Qdrant is unavailable")
        return {"note": None, "usage": None}
    if not hits or hits[0]["score"] < SIMILARITY_THRESHOLD:
        return {"note": None, "usage": None}

    past = hits[0]
    parsed, usage = generate_structured(
        CONTRADICTION_SYSTEM_PROMPT,
        f"New decision: {decision_text}\n\nPast decision from meeting {past.get('meeting_title')} on {past.get('meeting_date')}: {past.get('chunk_text')}",
        ContradictionResult,
        max_output_tokens=1000,
        feature="decision_conflicts",
    )
    return {"note": (parsed.note or None) if parsed.conflicts else None, "usage": usage}
