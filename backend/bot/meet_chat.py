"""Google Meet's in-call chat: open the panel and post a message.

Meet's markup changes often, so every lookup tries a few labels and every
failure is logged and swallowed: a chat that can't be reached must never
cost the recording.
"""
import logging
import re
from collections import Counter

from playwright.async_api import Page

log = logging.getLogger("meet_chat")

CHAT_BUTTON = (
    'button[aria-label*="Chat with everyone" i], '
    'button[aria-label*="Show everyone" i][aria-label*="chat" i], '
    'button[aria-label="Chat" i], button[aria-label*="chat" i]'
)
CHAT_INPUT = (
    'textarea[aria-label*="Send a message" i], '
    'textarea[placeholder*="Send a message" i], '
    '[contenteditable="true"][aria-label*="message" i]'
)
SEND_BUTTON = 'button[aria-label*="Send a message" i], button[aria-label="Send" i]'


async def open_panel(page: Page) -> bool:
    """Opens the chat panel if it isn't already; True when the input is there."""
    if await page.locator(CHAT_INPUT).count():
        return True
    button = page.locator(CHAT_BUTTON).first
    try:
        if await button.count():
            await button.click(timeout=3000)
        else:
            # Meet's own shortcut for the chat panel.
            await page.keyboard.press("Control+Alt+KeyC")
        await page.locator(CHAT_INPUT).first.wait_for(state="visible", timeout=5000)
        return True
    except Exception as error:
        log.warning("Could not open the Meet chat: %s", error)
        return False


async def send(page: Page, text: str) -> bool:
    """Posts `text` to everyone in the call. False if chat was unreachable
    (disabled by the host, markup changed); never raises."""
    try:
        if not await open_panel(page):
            return False
        box = page.locator(CHAT_INPUT).first
        await box.click(timeout=3000)
        # Meet sends on Enter, so a multi-line message goes line by line
        # joined with Shift+Enter.
        lines = text.split("\n")
        for index, line in enumerate(lines):
            await box.type(line, delay=4)
            if index < len(lines) - 1:
                await page.keyboard.press("Shift+Enter")
        send_button = page.locator(SEND_BUTTON).first
        if await send_button.count() and await send_button.is_enabled():
            await send_button.click(timeout=3000)
        else:
            await page.keyboard.press("Enter")
        return True
    except Exception as error:
        log.warning("Could not post to the Meet chat: %s", error)
        return False


def join_notice(display_name: str, requested_by: str | None, app_url: str | None, leave_phrase: str) -> str:
    """What the notetaker says when it joins: who it is, who invited it,
    that it records, and how to make it leave."""
    invited = f", invited by {requested_by}" if requested_by else ""
    lines = [
        f"Hi, I'm {display_name}{invited}. I'm recording this call so Charcha can write up the notes, tasks and decisions.",
        f'To stop me, say "{leave_phrase}" or remove me from the call.',
        'Ask me about this call here: start your message with "Charcha", e.g. "Charcha recap" or "Charcha, what did we decide?"',
        'Add a task the same way: "Charcha, add task: Vedant to send the invoice by Friday".',
    ]
    if app_url:
        lines.append(f"Notes appear at {app_url}/meetings after the call.")
    return "\n".join(lines)


# Every line of text in the open chat panel. The panel is found from the
# message box upwards, so it survives Meet renaming its containers.
PANEL_LINES_JS = """
() => {
  const input = document.querySelector('textarea[aria-label*="Send a message" i], textarea[placeholder*="Send a message" i], [contenteditable="true"][aria-label*="message" i]');
  if (!input) return null;
  let panel = input;
  for (let i = 0; i < 12 && panel.parentElement; i++) {
    panel = panel.parentElement;
    if (panel.matches('[role="complementary"], aside, [aria-label*="message" i][role="region"]')) break;
  }
  return (panel.innerText || "").split("\\n").map((line) => line.trim()).filter(Boolean);
}
"""

_TASK_RE = re.compile(r"^(?:please\s+)?(?:add|create|note|make)\s+(?:a\s+|an\s+)?(?:task|action item|todo|to-do)\b[\s:,.-]*(.+)$", re.IGNORECASE)


def task_text(question: str) -> str | None:
    """The task in "add task: Vedant to send the invoice by Friday", or None
    when the message is a question rather than a task to add."""
    match = _TASK_RE.match(question.strip())
    return match.group(1).strip() if match and len(match.group(1).strip()) >= 2 else None


_QUESTION_RE = re.compile(r"^\s*@?charcha\b[\s,:;.!-]*(.+)$", re.IGNORECASE)


class ChatWatcher:
    """Finds new chat messages addressed to Charcha ("Charcha, ...").

    Lines already in the panel when watching starts are ignored, and so are
    the notetaker's own messages, so it never answers itself or old chat."""

    def __init__(self) -> None:
        self._seen: Counter[str] | None = None
        self._own: set[str] = set()

    def remember_sent(self, text: str) -> None:
        for line in text.split("\n"):
            if line.strip():
                self._own.add(line.strip())

    async def new_questions(self, page: Page) -> list[str]:
        try:
            lines = await page.evaluate(PANEL_LINES_JS)
        except Exception:
            return []
        if lines is None:
            await open_panel(page)
            return []
        counts = Counter(lines)
        if self._seen is None:
            self._seen = counts
            return []
        fresh = counts - self._seen
        self._seen = counts
        questions = []
        for line, times in fresh.items():
            if line in self._own:
                continue
            match = _QUESTION_RE.match(line)
            if match and len(match.group(1).strip()) >= 2:
                questions.extend([match.group(1).strip()] * times)
        return questions
