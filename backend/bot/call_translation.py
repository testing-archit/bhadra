"""Per-call translation subscriptions. Shared chat, bounded to three languages.

Each language advances only after its summary reaches chat. Translation never
plays speech, avoiding overlap with the discussion and the command microphone.
"""
import re
import time

LANGUAGES = {"english": "en-IN", "hinglish": "hi-en", "hindi": "hi-IN", "tamil": "ta-IN", "telugu": "te-IN", "kannada": "kn-IN", "malayalam": "ml-IN", "marathi": "mr-IN", "bengali": "bn-IN", "gujarati": "gu-IN", "punjabi": "pa-IN"}
STOP = {"stop translation", "stop translating", "stop translations", "turn off translation"}


def requested_language(command):
    match = re.fullmatch(r"(?:please )?(?:translate(?: (?:this|the call))?(?: (?:to|into|in))?|translation in|(?:live |running )?(?:captions|summary) in) (" + "|".join(LANGUAGES) + r")[.!?]*", command.strip(), re.I)
    return match.group(1).lower() if match else None


class RunningTranslations:
    INTERVAL = 30

    def __init__(self):
        self.languages = {}
        self.last_poll = 0.0
        self.revision = 0

    def command(self, text, captions):
        value = text.strip().lower().rstrip('.!?')
        if value in STOP:
            self.languages.clear()
            self.revision += 1
            return "Stopped the running translations in shared chat."
        language = requested_language(text)
        if not language:
            return None
        if language not in self.languages and len(self.languages) >= 3:
            return "I can translate into three languages at once. Say ‘stop translations’ to choose again."
        cursor = max((float(row.get('end', 0)) for row in captions), default=0) - 30
        self.languages.setdefault(language, max(0, cursor))
        self.revision += 1
        self.last_poll = time.monotonic() - self.INTERVAL
        return f"I'll post a running {language.title()} summary in shared meeting chat, about every 30 seconds when there's new speech. Everyone can read it. Say ‘stop translations’ to stop."

    async def flush(self, captions, elapsed, translate, send, paused):
        if paused() or not self.languages or time.monotonic() - self.last_poll < self.INTERVAL:
            return
        self.last_poll = time.monotonic()
        revision = self.revision
        for language, cursor in list(self.languages.items()):
            delta = [row for row in captions if float(row.get('end', 0)) > cursor and float(row.get('end', 0)) <= elapsed - 8][-60:]
            if not delta:
                continue
            result = await translate(LANGUAGES[language], delta)
            if revision != self.revision or paused():
                return
            if result and await send(f"[{language.title()} · running summary] {result}"):
                if revision == self.revision:
                    self.languages[language] = max(float(row['end']) for row in delta)
