"""Narrow routing for explicit board requests; no model required for dispatch."""
import re


def normalize(question: str) -> str:
    plain = question.strip().lower().rstrip('.!?')
    plain = re.sub(r'\bfig[\s-]+jam\b', 'figjam', plain)
    while True:
        cleaned = re.sub(r'^(?:please|can you|could you|would you|will you|kindly|just|go ahead and|i want you to|i need you to)\s+', '', plain)
        if cleaned == plain:
            return plain
        plain = cleaned


def board_intent(question: str, active: bool, is_task: bool = False) -> str | None:
    plain = normalize(question)
    if is_task:
        return None  # Preserve task capture even when its description mentions a board.
    named = bool(re.search(r'\b(?:white\s?boards?|boards?|figjam|figma|jam\s*boards?)\b', plain))
    # "Draw a signup flow" always means the board, even before one is open:
    # route it straight to one board edit instead of an extra planner call.
    if re.match(r'(?:draw|sketch|diagram)\b', plain) or re.match(
            r'(?:make|create|map(?: out)?)\s+(?:me\s+)?(?:a|an|the|our|my)\s+(?:[\w,-]+\s+){0,6}?'
            r'(?:flow\s?chart|flow|diagram|mind\s?map)\b', plain):
        named = True
    # Hinglish: "architecture diagram bana do", "login ka flow chart banao".
    if DIAGRAM.search(plain) and HINGLISH_MAKE.search(plain):
        return 'edit'
    if plain in {'stop presenting', 'stop sharing', 'stop presenting the board', 'stop sharing the board'}:
        return 'stop'
    implicit_board = active and bool(re.fullmatch(r'(?:present|share|show)(?: (?:it|this|that|this one|the current one))?', plain))
    if re.match(r'(?:present|share|show)\b', plain) and (named or implicit_board):
        return 'present'
    if named and re.match(r'(?:make|create|start|open|launch)\b', plain):
        return 'open_present' if re.search(r'\b(?:present|share)\b', plain) else 'open'
    if re.match(r'(?:add|create|put|move|connect|rename|change|update|remove|delete|undo|draw|sketch|diagram|map|banao|jodo)\b', plain) and (named or active):
        if named or not is_task:
            return 'edit'
    return None


DIAGRAM = re.compile(r'\b(?:diagrams?|flow\s?charts?|architecture|system design|sequence|er diagram|data model|state machine|mermaid)\b')
HINGLISH_MAKE = re.compile(r'\b(?:bana(?:o|do|de|dijiye|na)?|banao|dikhao|draw karo|kheench(?:o| do)?)\b')


def wants_diagram(question: str) -> bool:
    """Diagram requests use Wilco's own board (Mermaid), which needs no FigJam sign-in."""
    return bool(DIAGRAM.search(normalize(question)))


def opening_only(question: str) -> bool:
    """Only a bare open/present request can skip drawing inference."""
    return bool(re.fullmatch(
        r'(?:open|launch|start|create|make)(?: up)?(?: and (?:present|share|show))? (?:me )?(?:a |the |our |my |new )?'
        r'(?:white\s?boards?|boards?|figjam|figma|jam\s*boards?)(?: board)?(?: (?:and )?(?:present|share|show)(?: it)?)?',
        normalize(question),
    ))


def requires_plan(question: str) -> bool:
    return bool(re.search(r'\b(?:and|then|also|,)\s+(?:(?:add|create|record|make)\s+(?:an?\s+|the\s+)?(?:task|action item|todo)|send|email|schedule|invite|assign|reassign)\b', question, re.I))
