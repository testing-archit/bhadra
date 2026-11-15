"""Validate Mermaid diagram source before it is stored, rendered or presented.

Mermaid is rendered with securityLevel 'strict' everywhere, which already
disables click handlers and HTML labels. This is the server-side gate: it keeps
the source to known diagram types, strips code fences a model may add, and
refuses directives that can change rendering settings or embed links/scripts.
"""
import re

MAX_CHARS = 4000
MAX_LINES = 150

DIAGRAM_TYPES = (
    "flowchart", "graph", "sequenceDiagram", "erDiagram", "classDiagram",
    "stateDiagram-v2", "stateDiagram", "journey", "gantt", "mindmap", "timeline",
)

_FORBIDDEN = [
    (re.compile(r"%%\s*\{"), "Diagram settings directives aren't allowed"),
    (re.compile(r"^\s*(?:click|callback|href)\b", re.I | re.M), "Diagram links and click actions aren't allowed"),
    (re.compile(r"javascript\s*:|data\s*:\s*text/html|<\s*/?\s*(?:script|iframe|object|embed|style|img|a)\b", re.I), "Diagram text can't contain HTML or scripts"),
]


def clean(source: str) -> str:
    """Return normalized Mermaid source, or raise ValueError with a user-facing reason."""
    text = (source or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    fenced = re.fullmatch(r"```(?:mermaid)?\s*\n(.*?)\n?```", text, re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    if not text:
        raise ValueError("The diagram is empty")
    if len(text) > MAX_CHARS or text.count("\n") + 1 > MAX_LINES:
        raise ValueError("The diagram is too large; split it into smaller diagrams")
    for pattern, reason in _FORBIDDEN:
        if pattern.search(text):
            raise ValueError(reason)
    header = next((line.strip() for line in text.split("\n")
                   if line.strip() and not line.strip().startswith("%%")), "")
    if not any(header == kind or header.startswith(kind + " ") or header.startswith(kind + "\t")
               for kind in DIAGRAM_TYPES):
        raise ValueError("Start the diagram with a supported type, such as flowchart LR or sequenceDiagram")
    return text
