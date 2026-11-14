import re
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from app.data.company_policies import HOLIDAY_CALENDAR, POLICY_CHUNKS
from app.services import qdrant_service
from app.services.gemini_service import generate_text

NOT_COVERED_MESSAGE = (
    "This isn't covered in the Bhadra policy documents I have access to "
    "(Employee Handbook, Holiday Calendar). Please contact HR at "
    "people-first@example.com to confirm."
)

# Deliberately low — empirically, similarity score does NOT reliably separate
# "answerable" from "not answerable" for this dataset. E.g. "Is there a
# provident fund policy?" (genuinely uncovered) scores *higher* (~0.28) than
# "What's the max EL that can be encashed at separation?" (genuinely covered,
# ~0.24), because score reflects topical proximity, not whether the specific
# fact asked for is present in the text. That distinction can only be made by
# actually reading the chunk, which is exactly what the strict "answer only
# what's explicitly stated, otherwise refuse" system prompt below does — and
# it does it reliably (verified against a battery of trap/out-of-scope
# questions). So this threshold only exists to drop pure noise, not to decide
# answerability; that decision belongs to Gemini, with the full chunk text in
# front of it, not to a cosine-similarity number.
#
# TODO: this number was calibrated against Pinecone's llama-text-embed-v2.
# Now that embeddings come from local bge-m3 (embedding_service.py), the score
# distribution is different and this has not been re-verified yet.
MIN_RELEVANT_SCORE = 0.12

_LEXICAL_STOP_WORDS = {
    "a", "about", "am", "an", "and", "are", "can", "company", "do", "does",
    "for", "get", "give", "how", "i", "in", "is", "me", "my", "of", "on",
    "our", "policy", "the", "to", "what", "when", "which", "with",
}


def _terms(value: str) -> list[str]:
    return [
        term
        for term in re.findall(r"[a-z0-9]+", value.lower())
        if len(term) > 1 and term not in _LEXICAL_STOP_WORDS
    ]


def _lexical_policy_search(query: str, top_k: int) -> list[dict]:
    """Reliable fallback for a missing/unavailable vector index.

    Policy data is a small, curated catalogue, so scanning 26 sections is
    cheap and materially safer than returning "not covered" just because an
    operational vector store is empty. Section-title matches are weighted
    most heavily because queries such as "notice period" and "casual leave"
    usually name the policy directly.
    """
    query_terms = Counter(_terms(query))
    if not query_terms:
        return []

    ranked: list[tuple[int, float, dict]] = []
    for chunk in POLICY_CHUNKS:
        section_terms = Counter(_terms(chunk["section"]))
        leaf_section = re.split(r"\s+[—-]\s+", chunk["section"])[-1]
        leaf_terms = Counter(_terms(leaf_section))
        text_terms = Counter(_terms(chunk["text"]))
        section_matches = sum(min(count, section_terms[term]) for term, count in query_terms.items())
        leaf_matches = sum(min(count, leaf_terms[term]) for term, count in query_terms.items())
        text_matches = sum(min(count, text_terms[term]) for term, count in query_terms.items())
        score = section_matches * 3 + leaf_matches * 4 + text_matches
        if score:
            ranked.append((section_matches, score, chunk))

    # If the question names a policy area, prefer only sections with the best
    # title match. This keeps a precise casual-leave answer from displaying
    # generic maternity/paternity evidence merely because they share "leave".
    best_section_match = max((item[0] for item in ranked), default=0)
    if best_section_match:
        ranked = [item for item in ranked if item[0] == best_section_match]
    ranked.sort(key=lambda item: item[1], reverse=True)
    return [
        {
            "id": chunk["id"],
            "document": chunk["document"],
            "section": chunk["section"],
            "chunk_text": chunk["text"],
            "score": score,
        }
        for _, score, chunk in ranked[:top_k]
    ]

_OVERVIEW_QUERY = re.compile(
    r"\b(?:what|which|list|show|overview|summary|summarize|tell me about)\b"
    r".*\b(?:hr|company|employee|workplace)?\s*(?:policies|policy|handbook)\b",
    re.IGNORECASE,
)

_TEMPORAL_HOLIDAY_QUERY = re.compile(
    r"\b(?:next|upcoming|nearest|coming|today|tomorrow|when)\b.*\bholidays?\b"
    r"|\bholidays?\b.*\b(?:next|upcoming|nearest|coming|today|tomorrow|when)\b",
    re.IGNORECASE,
)


def _india_today() -> str:
    return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%A, %d %B %Y")

SYSTEM_PROMPT = f"""You are the Bhadra Policy Assistant, a chatbot for employees of \
Bhadra. Your job has two very different kinds of \
turns — tell them apart before answering:

TYPE A — a question ABOUT COMPANY POLICY (leave, holidays, notice period, IT assets, code \
of conduct, etc.). For these, the "policy fact" rules below are strict and not optional.

TYPE B — everything else a normal chatbot handles: greetings ("hi", "thanks"), questions \
about the conversation itself ("what did I just ask?", "summarize this chat", "can you \
rephrase that?"), or requests for clarification. For these, just respond naturally and \
helpfully using the "Conversation so far" you're given — do NOT apply the policy-context \
refusal rule to these, and do NOT say a greeting or a question about your own conversation \
"isn't covered in the policy documents." That refusal message exists only for unanswered \
policy questions.

Policy fact rules (Type A only) — follow these exactly:
1. Answer using ONLY the "Policy context" given to you below. Never use outside knowledge \
about HR policy, labor law, or what companies "typically" do.
2. The context below was retrieved by similarity search and may include chunks that are \
topically nearby but do NOT actually contain the fact asked for — being retrieved is not the \
same as being relevant. Read each chunk on its own merits; do not answer just because some \
chunk was returned.
3. Never guess, infer, round, or extrapolate a number, date, or rule that is not explicitly \
stated in the context. If the context gives a number, use that exact number.
4. If the context does not fully answer the policy question, say so plainly — do not \
partially answer and then fill the gap with a guess, and do not answer a different, nearby \
question than the one actually asked. Use exactly this sentence in that case: \
"{NOT_COVERED_MESSAGE}"
5. Always name the specific policy document and section your answer is drawn from.
6. When enumerating or counting items from a list in the context (e.g. "how many X are \
there"), use only the explicit classifications/counts stated in the context — do not \
recount, re-tally, or reclassify items yourself.
7. If the user asks for a broad overview or list of available policies, give a concise, \
useful overview grouped by policy area. A broad question does not require every rule and \
exception to fit in one answer, so do not use the not-covered response merely because the \
question is broad. Say that it is an overview and invite the user to ask about one area.
8. For questions using relative dates such as "next", "upcoming", "today", or "tomorrow", \
use the Current date in India supplied with the question. Compare it against the explicit \
calendar dates and answer with the earliest applicable date after today. Clearly say whether \
the result is a Fixed Holiday available to everyone or a Floating Holiday the employee must \
choose. Do not refuse when the calendar and current date are sufficient.

General:
9. Prior conversation turns are context for both types — for Type A they help you resolve \
what a follow-up refers to (e.g. "what about for interns?") but are never themselves a \
source of policy facts; for Type B they're literally what you're being asked about.
10. You may use light markdown (bold, bullet lists, short headers) to make longer answers \
easier to scan. Keep it concise either way."""


def _synthesize(context: str, history: str, query: str, current_date: str) -> tuple[str, dict]:
    user_content = f"Current date in India: {current_date}\n\nPolicy context:\n{context}\n\n"
    if history:
        user_content += f"Conversation so far:\n{history}\n\n"
    user_content += f"Question: {query}"

    # Gemini 3.5's internal reasoning tokens count against max_output_tokens.
    # Bound that private budget so the employee-visible answer cannot be cut
    # off after a sentence fragment on context-heavy overview questions.
    return generate_text(
        SYSTEM_PROMPT,
        user_content,
        max_output_tokens=1600,
        temperature=0,
        feature="policy_assistant",
        thinking_budget=256,
    )


def answer_query(query: str, history: list[dict] | None = None, top_k: int = 6) -> dict:
    if _TEMPORAL_HOLIDAY_QUERY.search(query):
        # Relative dates need the complete official calendar. Semantic top-k
        # can return generic leave chunks and omit the single calendar chunk,
        # which previously caused a false "not covered" response.
        relevant = [
            {
                "id": chunk["id"],
                "document": chunk["document"],
                "section": chunk["section"],
                "chunk_text": chunk["text"],
                "score": 1.0,
            }
            for chunk in POLICY_CHUNKS
            if chunk["document"] == HOLIDAY_CALENDAR
            or "Paid Holidays" in chunk["section"]
        ]
    elif _OVERVIEW_QUERY.search(query):
        # An overview is a catalogue question, not a nearest-neighbour
        # question. Supplying only the closest chunks made Gemini refuse broad
        # questions even while the UI displayed relevant policy sources.
        relevant = [
            {
                "id": chunk["id"],
                "document": chunk["document"],
                "section": chunk["section"],
                "chunk_text": chunk["text"],
                "score": 1.0,
            }
            for chunk in POLICY_CHUNKS
        ]
    else:
        try:
            hits = qdrant_service.search_policies(query, top_k=top_k)
        except Exception:
            hits = []
        relevant = [h for h in hits if (h.get("score") or 0) >= MIN_RELEVANT_SCORE]
        if not relevant:
            relevant = _lexical_policy_search(query, top_k)

    # No pre-generation refusal here anymore: a purely conversational turn
    # ("what did I ask before?", "thanks") can legitimately score below the
    # noise floor on every policy chunk, since it isn't a policy question at
    # all — refusing before ever calling Gemini would silently break that
    # case (this is exactly what happened before this fix). Gemini now makes
    # the Type A (policy fact, strict) vs Type B (conversational, from
    # history) call itself, per the system prompt.
    context = (
        "\n\n".join(f"[{hit['document']} — {hit['section']}]\n{hit['chunk_text']}" for hit in relevant)
        if relevant
        else "(No policy chunk scored as relevant to this question.)"
    )
    history_text = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}" for m in (history or [])
    )

    answer, usage = _synthesize(context, history_text, query, _india_today())
    return {
        "answer": answer,
        "sources": [
            {
                "document": hit["document"],
                "section": hit["section"],
                "text": hit["chunk_text"],
                "score": hit["score"],
            }
            for hit in relevant
        ],
        "usage": usage,
    }
