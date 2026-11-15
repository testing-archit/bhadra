"""Server-side action dispatch protects against stale/misclassifying clients."""
import re


def board_action(command: str) -> str | None:
    text = command.lower().strip().rstrip('.!?')
    text = re.sub(r'\bfig[\s-]+jam\b', 'figjam', text)
    while True:
        value = re.sub(r'^(?:please|can you|could you|would you|will you|kindly|just|go ahead and|i want you to|i need you to)\s+', '', text)
        if value == text: break
        text = value
    if not re.search(r'\b(?:figjam|figma|white\s?boards?|jam\s*boards?|boards?)\b', text):
        return None
    if re.match(r'(?:open|launch|start|create|make)\b', text):
        bare = re.fullmatch(
            r'(?:open|launch|start|create|make)(?: up)?(?: and (?:present|share|show))? (?:me )?(?:a |the |our |my |new )?'
            r'(?:white\s?boards?|boards?|figjam|figma|jam\s*boards?)(?: board)?(?: (?:and )?(?:present|share|show)(?: it)?)?', text)
        return 'open_board' if bare else 'edit_board'
    if re.match(r'(?:draw|sketch|add|move|rename|connect|remove|delete|undo)\b', text):
        return 'edit_board'
    return None
