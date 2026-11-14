"""Environment-driven settings for the notetaker bot. Every value has a
working default except the secrets, which fail loudly when first used."""

import os
import socket
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def require(name: str) -> str:
    value = _env(name)
    if not value:
        raise SystemExit(f"Missing required environment variable {name} — see backend/bot/README.md")
    return value


BACKEND_URL = _env("BACKEND_URL", "http://localhost:8080").rstrip("/")

# The Google account people invite, Fireflies style.
NOTETAKER_EMAIL = _env("NOTETAKER_EMAIL", "notetaker@example.com").lower()
# Shown in Meet when the signed-in session has expired and the bot has to
# fall back to joining as a named guest. When signed in, Meet shows the Google
# account's own profile name instead — set that to the same thing.
BOT_DISPLAY_NAME = _env("BOT_DISPLAY_NAME", "Charcha Notetaker")
MEETING_LANGUAGE = _env("MEETING_LANGUAGE", "hinglish")

STATE_DIR = Path(_env("STATE_DIR", str(Path(__file__).parent / "data")))
# Playwright storage state (cookies) for the notetaker's Google login.
# Rewritten after every meeting so Google's rotating cookies stay current.
AUTH_STATE_PATH = Path(_env("AUTH_STATE_PATH", str(STATE_DIR / "auth.json")))

POLL_SECONDS = int(_env("POLL_SECONDS", "30"))
# "Send notetaker" requests are checked far more often than the calendar:
# someone is sitting in the call waiting for the bot to knock.
CAPTURE_POLL_SECONDS = int(_env("CAPTURE_POLL_SECONDS", "3"))
# Join this long before the scheduled start, the way Fireflies does.
JOIN_EARLY_SECONDS = int(_env("JOIN_EARLY_SECONDS", "60"))
MAX_CONCURRENT_MEETINGS = int(_env("MAX_CONCURRENT_MEETINGS", "2"))
# How this container is named in Admin → Notetaker. Defaults to the
# hostname, which Docker sets to the container id.
INSTANCE_NAME = _env("NOTETAKER_INSTANCE_NAME") or socket.gethostname()
# How long to sit in the lobby waiting for the host to admit the bot.
LOBBY_TIMEOUT_SECONDS = int(_env("LOBBY_TIMEOUT_SECONDS", "600"))
# Leave once the bot has been the only participant for this long...
# Short, because the meeting is over for everyone who matters once they've
# all left; a longer wait only records an empty room.
ALONE_TIMEOUT_SECONDS = int(_env("ALONE_TIMEOUT_SECONDS", "30"))
# ...except right after joining early, when nobody has arrived yet.
WAIT_FOR_OTHERS_SECONDS = int(_env("WAIT_FOR_OTHERS_SECONDS", "600"))
# Stay at most this long past the event's scheduled end, and never longer
# than the hard cap, whatever the DOM says.
OVERRUN_MINUTES = int(_env("OVERRUN_MINUTES", "60"))
MAX_MEETING_MINUTES = int(_env("MAX_MEETING_MINUTES", "240"))

# Teams only, off by default: show the Bhadra logo as the notetaker's camera,
# since an anonymous guest can't have a profile picture. Encoding it costs CPU,
# and CPU shortage is what damages recordings, so check audio before enabling.
TEAMS_LOGO_CAMERA = _env("TEAMS_LOGO_CAMERA").lower() in {"1", "true", "yes"}
TEAMS_LOGO_IMAGE = Path(_env("TEAMS_LOGO_IMAGE", str(Path(__file__).parent / "assets" / "logo_card.png")))

# Google Meet only: post a short notice in the call's chat on joining (who
# invited the notetaker, that it records, how to make it leave), like any
# well-behaved notetaker. Off with ANNOUNCE_IN_CHAT=0.
ANNOUNCE_IN_CHAT = _env("ANNOUNCE_IN_CHAT", "1").lower() not in {"0", "false", "no"}
# Answer chat messages that start with "Charcha" from the call so far
# (needs ANNOUNCE_IN_CHAT: the panel is opened by the notice).
ANSWER_IN_CHAT = _env("ANSWER_IN_CHAT", "1").lower() not in {"0", "false", "no"}

EXIT_PHRASES = [
    p.strip().lower()
    for p in _env("EXIT_PHRASES", "notetaker please leave,note taker please leave,charcha please leave").split(",")
    if p.strip()
]

SESSIONS_DIR = STATE_DIR / "sessions"
PENDING_DIR = STATE_DIR / "pending_uploads"
SCHEDULER_STATE_PATH = STATE_DIR / "scheduler_state.json"
