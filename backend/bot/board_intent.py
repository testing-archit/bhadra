"""Narrow routing for explicit board requests; no model required for dispatch."""
import re


def normalize(question: str) -> str:
    plain = question.strip().lower().rstrip('.!?')
    while True:
        cleaned = re.sub(r'^(?:please|can you|could you|would you)\s+', '', plain)
        if cleaned == plain:
            return plain
        plain = cleaned


def board_intent(question: str, active: bool, is_task: bool = False) -> str | None:
    plain = normalize(question)
    if is_task:
        return None  # Preserve task capture even when its description mentions a board.
    named = bool(re.search(r'\b(?:white\s?board|board|figjam|figma)\b', plain))
    if plain in {'stop presenting', 'stop sharing', 'stop presenting the board', 'stop sharing the board'}:
        return 'stop'
    implicit_board = active and bool(re.fullmatch(r'(?:present|share|show)(?: (?:it|this|that|this one|the current one))?', plain))
    if re.match(r'(?:present|share|show)\b', plain) and (named or implicit_board):
        return 'present'
    if named and re.match(r'(?:make|create|start|open)\b', plain):
        return 'open_present' if re.search(r'\b(?:present|share)\b', plain) else 'open'
    if re.match(r'(?:add|create|put|move|connect|rename|change|update|remove|delete|undo|draw|banao|jodo)\b', plain) and (named or active):
        if named or not is_task:
            return 'edit'
    return None


def opening_only(question: str) -> bool:
    """Only a bare open/present request can skip drawing inference."""
    return bool(re.fullmatch(
        r'(?:open|start|create|make)(?: up)?(?: and (?:present|share|show))? (?:a |the |our |my |new )?'
        r'(?:white\s?board|board|figjam|figma)(?: board)?(?: (?:and )?(?:present|share|show)(?: it)?)?',
        normalize(question),
    ))


def requires_plan(question: str) -> bool:
    return bool(re.search(r'\b(?:and|then|also|,)\s+(?:(?:add|create|record|make)\s+(?:an?\s+|the\s+)?(?:task|action item|todo)|send|email|schedule|invite|assign|reassign)\b', question, re.I))
