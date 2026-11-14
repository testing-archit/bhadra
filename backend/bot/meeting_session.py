"""One notetaker visit to one meeting: join, record, leave, hand off.
MeetingSession is Google Meet; TeamsSession swaps in Microsoft Teams' screens
(teams_dom.py). Recording, staying and handing off are the same for both.

Run by the scheduler as its own process per meeting (so a Chromium crash
takes down one meeting, not the bot), or by hand for a meeting that is not on
the notetaker's calendar:

    python meeting_session.py --url https://meet.google.com/abc-defg-hij

Audio: each session gets a private PulseAudio null sink; Chromium is pointed
at it via PULSE_SINK and ffmpeg records the sink's monitor. Captions: the
call's own live captions are scraped for speaker *names* — the backend lines them up
with Prisma's timestamped transcription (app/services/speaker_mapping.py).
"""

import argparse
import asyncio
import base64
import difflib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from playwright.async_api import BrowserContext, Page, async_playwright

import config
import meet_chat
import teams_dom
import uploader

log = logging.getLogger("session")

JOIN_BUTTON_TEXTS = ["Join now", "Ask to join", "Join meeting", "Join call", "Switch here"]
LEAVE_BUTTON = 'button[aria-label*="Leave call"], button[aria-label*="Leave meeting"]'
# Lower-cased page text meaning the bot is no longer in the call.
ENDED_PHRASES = [
    "you left the meeting",
    "you've left the call",
    "you’ve left the call",
    "you've been removed from the meeting",
    "you’ve been removed from the meeting",
    "the call has ended",
    "meeting has ended",
    "return to home screen",
]
# Lower-cased page text of Meet's waiting room. It already shows the call
# controls — Leave button included — so the Leave button alone doesn't mean
# the bot is in. Mistaking it for admission once cost a meeting all its
# speaker names: captions were tried (and given up on) before they existed.
WAITING_ROOM_PHRASES = [
    "please wait until a meeting host brings you into the call",
    "waiting for the host to let you in",
]
# Lower-cased page text meaning the bot will never be let in.
REJECTED_PHRASES = [
    "you can't join this video call",
    "you can’t join this video call",
    "someone in the call denied your request",
    "no one responded to your request",
    "you have been removed from the meeting",
    "this meeting has ended",
    "check your meeting code",
]

CAPTION_WATCHER_JS = """
() => {
  // Meet's caption DOM: a region per call, one block per speaker turn, each
  // block holding a name badge and the growing text. The badge class names
  // are obfuscated and do change — when they stop matching, captions simply
  // come back without names and the backend keeps "Speaker N" labels.
  const BADGE = ".NWpY1d, .xoMHSc";
  const ids = new WeakMap();
  let nextId = 1;
  const dirty = new Map();

  const inCaptions = (el) => {
    const region = el.closest('[role="region"]');
    return !!region && /caption/i.test(region.getAttribute("aria-label") || "");
  };

  const blockOf = (el) => {
    // The smallest ancestor that contains a name badge is the turn block.
    while (el && !el.matches('[role="region"]')) {
      if (el.querySelector(BADGE)) return el;
      el = el.parentElement;
    }
    return null;
  };

  const record = (node) => {
    const el = node instanceof HTMLElement ? node : node.parentElement;
    if (!el || !inCaptions(el)) return;
    const block = blockOf(el);
    if (!block) return;
    if (!ids.has(block)) ids.set(block, nextId++);
    const badge = block.querySelector(BADGE);
    const clone = block.cloneNode(true);
    clone.querySelectorAll(BADGE).forEach((b) => b.remove());
    const text = (clone.textContent || "").trim();
    if (text) dirty.set(ids.get(block), { speaker: (badge?.textContent || "").trim(), text });
  };

  new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === "characterData") record(m.target);
      else m.addedNodes.forEach(record);
    }
  }).observe(document.body, { childList: true, characterData: true, subtree: true });

  setInterval(() => {
    if (!dirty.size) return;
    const batch = [...dirty.entries()].map(([id, v]) => ({ id, ...v }));
    dirty.clear();
    window.onCaptions(batch);
  }, 1000);
}
"""

# Best of two independent readings, because Meet changes its markup: the
# participant tiles, and the number on the People button ("3" / "Show
# everyone (3)"). 0 means neither could be read.
PARTICIPANT_COUNT_JS = """
() => {
  const tiles = new Set(
    [...document.querySelectorAll("[data-participant-id]")].map((e) => e.getAttribute("data-participant-id"))
  ).size;
  let badge = 0;
  for (const el of document.querySelectorAll("button[aria-label], [role=button][aria-label]")) {
    const label = el.getAttribute("aria-label") || "";
    if (!/people|participant|everyone/i.test(label)) continue;
    const match = label.match(/(\\d+)/) || (el.textContent || "").match(/(\\d+)\\s*$/);
    if (match) badge = Math.max(badge, Number(match[1]));
  }
  return Math.max(tiles, badge);
}
"""

# Captions this recent mean someone else is in the call (the bot never
# speaks), whatever the participant count says.
SPEECH_IS_COMPANY_SECONDS = 30
# "Charcha, <question>" said aloud. Captions spell the name a few ways.
WAKE_RE = re.compile(r"(?:^|[.!?]\s+|\b(?:hey|hi|ok|okay|so|achha|acha)\s+)(?:char\s?cha+|charchaa|carcha|charchya)\b[\s,:.!-]+(.+?)(?=$|\b(?:hey\s+)?(?:char\s?cha+|charchaa|carcha)\b)", re.IGNORECASE)
# A spoken question is answered once its speaker has paused this long.
SPOKEN_QUESTION_PAUSE_SECONDS = 2.5

# Meet's own wording when the bot is the only one left in the call.
ALONE_PHRASES = [
    "you're the only one here",
    "you’re the only one here",
    "no one else is here",
]


def _rejection_reason(page_text: str, signed_out: bool) -> str:
    """Say who actually turned the notetaker away. "You can't join this video
    call" right after asking means Meet refused before the host ever saw a
    request — usually a meeting that only admits signed-in Google accounts."""
    if "denied your request" in page_text:
        return "Someone in the call denied the notetaker's request to join"
    if "no one responded" in page_text:
        return "Nobody admitted the notetaker before Meet gave up"
    if "can't join this video call" in page_text or "can’t join this video call" in page_text:
        if signed_out:
            return (
                "Google Meet blocked the notetaker before the host saw a request: it joins signed out, "
                "and this meeting only lets signed-in Google accounts ask to join. Sign the notetaker in "
                "to Google (backend/bot/README.md), or allow guests in the meeting's host controls"
            )
        return "Google Meet blocked the notetaker before the host saw a request (the meeting's access settings don't allow it)"
    return "The notetaker wasn't admitted to the meeting"


class AdmissionDenied(RuntimeError):
    pass


class AdmissionTimeout(RuntimeError):
    pass


class StopRequested(RuntimeError):
    pass


class MeetingUnavailable(RuntimeError):
    """The link leads nowhere. Nobody turned the notetaker away."""


STOP_CHECK_SECONDS = 15
# Without captions there are no speaker names, so the bot keeps trying to
# turn them on (and back on, if someone's shortcut turns them off).
CAPTION_RETRY_SECONDS = 30

# Nobody listens to the notetaker live, so it trades latency for audio that
# survives CPU spikes. Chromium plays into PulseAudio with ~10-20 ms buffers
# by default; any stall longer than that reaches the recording as hard
# silence. libpulse honours PULSE_LATENCY_MSEC for every client. Buffering
# only absorbs spikes — a CPU that stays short (a 2026-10 recording lost ~35%
# of its audio as 80-100 ms gaps every ~250 ms once a screen share started)
# needs the video work removed, see HIDE_VIDEO_JS.
PULSE_LATENCY_MS = 300
# ~0.5 s of 48 kHz stereo s16 per read from the sink monitor.
PULSE_FRAGMENT_BYTES = 48000 * 2 * 2 // 2

# The notetaker only needs Meet's audio and captions. Drawing video —
# above all a full-screen presentation — is pure CPU on a server with no GPU,
# and it is what starved the audio. Hidden <video> elements are never
# painted, and Meet asks for low-resolution streams for tiles that aren't
# visible. Audio plays from separate elements, so it is unaffected.
HIDE_VIDEO_JS = """
(() => {
  const css = "video { display: none !important; }";
  const add = () => {
    if (document.getElementById("charcha-no-video")) return;
    const style = document.createElement("style");
    style.id = "charcha-no-video";
    style.textContent = css;
    (document.head || document.documentElement).appendChild(style);
  };
  if (document.documentElement) add();
  else document.addEventListener("DOMContentLoaded", add, { once: true });
})();
"""


# The notetaker's camera in Meet: the Charcha avatar drawn on a canvas,
# switching to the speaking face (mouth open, marigold rings) while
# window.__charchaSpeaking is set. Audio still comes from the real
# (virtual) microphone. A canvas at 5 fps costs next to nothing.
AVATAR_CAMERA_JS = """
(() => {
  const media = navigator.mediaDevices;
  if (!media) return;
  const canvas = document.createElement("canvas");
  canvas.width = 640;
  canvas.height = 360;
  const ctx = canvas.getContext("2d");
  const idle = new Image();
  const speaking = new Image();
  idle.src = "data:image/png;base64,__IDLE__";
  speaking.src = "data:image/png;base64,__SPEAKING__";
  let tick = 0;
  setInterval(() => {
    tick += 1;
    // Alternate the faces while speaking so the mouth moves.
    const face = window.__charchaSpeaking && tick % 2 === 0 ? speaking : idle;
    if (face.complete && face.naturalWidth) ctx.drawImage(face, 0, 0, canvas.width, canvas.height);
  }, 200);
  const getUserMedia = media.getUserMedia.bind(media);
  media.getUserMedia = async (constraints) => {
    if (!constraints || !constraints.video) return getUserMedia(constraints);
    const stream = canvas.captureStream(5);
    if (constraints.audio) {
      try {
        const audio = await getUserMedia({ audio: constraints.audio });
        audio.getAudioTracks().forEach((track) => stream.addTrack(track));
      } catch {}
    }
    return stream;
  };
  const enumerateDevices = media.enumerateDevices.bind(media);
  media.enumerateDevices = async () => {
    const devices = await enumerateDevices();
    if (devices.some((device) => device.kind === "videoinput")) return devices;
    const camera = { deviceId: "charcha-avatar", groupId: "charcha", kind: "videoinput", label: "Charcha", toJSON() { return this; } };
    return [...devices, camera];
  };
})();
"""


def _norm(word: str) -> str:
    return "".join(ch for ch in word.lower() if ch.isalnum())


def _plain(text: str) -> str:
    """Lower-case words only: captions add commas, full stops and splits
    ("Note taker, please leave.") that an exact phrase match would miss."""
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


_LEAVE_RE = re.compile(
    r"\b(?:note\s?taker|charcha|char\s?cha|carcha)\b(?:\s+\w+){0,2}?\s+"
    r"(?:please\s+|pls\s+|plz\s+|ab\s+|aap\s+)?(?:leave|chale\s+jao|chali\s+jao|nikal\s+jao|bye|stop\s+recording)\b"
)


def wants_exit(text: str) -> bool:
    """True when someone asks the notetaker to leave, however captions
    punctuate it: the configured phrases, or notetaker/Charcha followed
    within a couple of words by "leave", "chale jao", "bye"."""
    plain = _plain(text)
    return any(_plain(phrase) in plain for phrase in config.EXIT_PHRASES) or bool(_LEAVE_RE.search(plain))


def spoken_summary(text: str, limit: int = 420) -> str:
    """What the notetaker says aloud: the reply's opening, cut at a
    sentence, without the quoted question or list dashes."""
    lines = [line.strip().lstrip("-").strip() for line in text.splitlines() if line.strip()]
    if lines and lines[0].startswith('"') and lines[0].endswith(":"):
        lines = lines[1:]
    spoken = ". ".join(lines)
    if len(spoken) > limit:
        cut = spoken[:limit]
        stop = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
        spoken = cut[: stop + 1] if stop > limit // 3 else cut
    return spoken


class CaptionLog:
    """Every word Meet captioned, timed by when it first appeared.

    Meet keeps one block open per speaker for as long as they hold the floor
    (often 30-170 s), shows only its last couple of lines, and keeps revising
    them. Storing the block's latest text as one caption kept ~15% of what was
    said, spread over the whole block's time — too little, too vaguely timed,
    for the backend to tell three or more speakers apart. So each update is
    aligned with what the block showed before: words trimmed off the front are
    kept, revised words keep their original time, new words are stamped now.
    """

    # A block is exported as chunks of speech split at pauses this long, and
    # never longer than CHUNK_SECONDS, so each caption is about one sentence.
    CHUNK_GAP_SECONDS = 2.0
    CHUNK_SECONDS = 8.0

    def __init__(self) -> None:
        self.audio_started_at: float | None = None
        # Meet block id -> {"speaker", "words": [[word, seen_at]], "visible": n}
        self._blocks: dict[int, dict] = {}
        self._last_heard: float | None = None
        self.exit_requested = asyncio.Event()
        # Meet block id -> (speaker, latest text, last change); read by the
        # spoken wake word ("Charcha, ...") detector.
        self.latest: dict[int, tuple[str, str, float]] = {}

    def heard_within(self, seconds: float) -> bool:
        return self._last_heard is not None and time.monotonic() - self._last_heard <= seconds

    def _now(self) -> float:
        return time.monotonic() - (self.audio_started_at or time.monotonic())

    async def on_captions(self, batch: list[dict]) -> None:
        now = self._now()
        for item in batch:
            text = (item.get("text") or "").strip()
            if not text:
                continue
            self._last_heard = time.monotonic()
            if wants_exit(text):
                self.exit_requested.set()
            self.latest[item["id"]] = (item.get("speaker") or "", text, time.monotonic())
            block = self._blocks.setdefault(item["id"], {"speaker": "", "words": [], "visible": 0})
            block["speaker"] = block["speaker"] or item.get("speaker") or ""
            words = text.split()
            block["words"] = self._merge(block["words"], block["visible"], words, now)
            block["visible"] = len(words)

    @staticmethod
    def _merge(known: list[list], visible: int, words: list[str], now: float) -> list[list]:
        head, tail = known[: len(known) - visible], known[len(known) - visible :]
        opcodes = difflib.SequenceMatcher(
            None, [_norm(w) for w, _ in tail], [_norm(w) for w in words], autojunk=False
        ).get_opcodes()
        if not any(tag == "equal" for tag, *_ in opcodes):
            # Nothing in common with what was on screen: a new stretch of
            # speech in a reused block.
            return known + [[w, now] for w in words]
        merged, aligned = list(head), False
        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                aligned = True
                merged += [[words[j1 + k], tail[i1 + k][1]] for k in range(i2 - i1)]
            elif tag == "delete":
                if not aligned:  # scrolled off the top, not retracted
                    merged += tail[i1:i2]
            elif tag == "insert":
                merged += [[w, now] for w in words[j1:j2]]
            else:  # replace: a revision keeps the time the words were first seen
                times = [t for _, t in tail[i1:i2]]
                merged += [[w, times[k] if k < len(times) else now] for k, w in enumerate(words[j1:j2])]
        return merged

    def export(self) -> list[dict]:
        chunks: list[dict] = []
        for block in self._blocks.values():
            current: dict | None = None
            for word, seen in block["words"]:
                if (
                    current is None
                    or seen - current["end"] > self.CHUNK_GAP_SECONDS
                    or seen - current["start"] > self.CHUNK_SECONDS
                ):
                    current = {"speaker": block["speaker"], "words": [], "start": seen, "end": seen}
                    chunks.append(current)
                current["words"].append(word)
                current["end"] = max(current["end"], seen)
        return sorted(
            (
                {
                    "speaker": c["speaker"],
                    "text": " ".join(c["words"]),
                    "start": round(max(c["start"], 0.0), 2),
                    "end": round(max(c["end"], c["start"] + 0.5, 0.0), 2),
                }
                for c in chunks
            ),
            key=lambda c: c["start"],
        )


def _pactl(*args: str) -> str:
    return subprocess.run(["pactl", *args], check=True, capture_output=True, text=True).stdout.strip()


async def _click_if_visible(page: Page, selector: str, timeout_ms: int = 2000) -> bool:
    try:
        locator = page.locator(selector).first
        await locator.wait_for(state="visible", timeout=timeout_ms)
        await locator.click()
        return True
    except Exception:
        return False


async def _page_text(page: Page) -> str:
    try:
        return (await page.evaluate("() => document.body.innerText || ''")).lower()
    except Exception:
        return ""


class MeetingSession:
    LEAVE_BUTTON = LEAVE_BUTTON
    WAITING_ROOM_PHRASES = WAITING_ROOM_PHRASES
    REJECTED_PHRASES = REJECTED_PHRASES
    ENDED_PHRASES = ENDED_PHRASES
    ALONE_PHRASES = ALONE_PHRASES
    CAPTION_WATCHER_JS = CAPTION_WATCHER_JS
    PARTICIPANT_COUNT_JS = PARTICIPANT_COUNT_JS
    # The saved login is a Google one: only Meet gets it, and only Meet may
    # rewrite it.
    USES_GOOGLE_LOGIN = True

    def __init__(self, job: dict) -> None:
        self.admitted_by_host = False
        self.job = job
        self.session_id = f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
        self.dir = config.SESSIONS_DIR / self.session_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.audio_path = self.dir / "audio.webm"
        self.sink = f"meet_{uuid.uuid4().hex[:8]}"
        self.voice_sink = f"voice_{uuid.uuid4().hex[:8]}"
        self.voice_mic = f"{self.voice_sink}_mic"
        self.sink_module: str | None = None
        self.ffmpeg: subprocess.Popen | None = None
        self.captions = CaptionLog()
        self.recorded_seconds = 0.0
        self.captions_enabled = False
        self.avatar_camera = config.MEET_AVATAR_CAMERA and config.AVATAR_IDLE.exists() and config.AVATAR_SPEAKING.exists()
        self.chat = meet_chat.ChatWatcher()
        self.chat_ready = False
        # Set only for "add the notetaker to this link" visits; calendar
        # visits have nobody waiting on a status.
        self.capture_request_id: str | None = job.get("capture_request_id")

    def report(self, status: str, detail: str | None = None) -> None:
        if self.capture_request_id:
            uploader.report_capture_event(self.capture_request_id, status, detail)

    def stop_requested(self) -> bool:
        """Also picks up a new end time when the calendar event was extended
        (or shortened) after the notetaker joined."""
        if not self.capture_request_id:
            return False
        state = uploader.capture_state(self.capture_request_id)
        if not state:
            return False
        if state.get("scheduled_end") and state["scheduled_end"] != self.job.get("event_end"):
            log.info("Meeting end moved to %s", state["scheduled_end"])
            self.job["event_end"] = state["scheduled_end"]
        return bool(state.get("stop_requested"))

    async def shot(self, page: Page, name: str) -> None:
        try:
            await page.screenshot(path=str(self.dir / f"{name}.png"))
        except Exception:
            pass

    # --- audio -------------------------------------------------------------

    def create_sink(self) -> None:
        self.sink_module = _pactl(
            "load-module", "module-null-sink",
            f"sink_name={self.sink}", f"sink_properties=device.description={self.sink}",
        )
        # The notetaker's voice: Timbre audio is played into voice_sink, and
        # Chromium uses voice_mic (that sink's monitor) as its microphone.
        try:
            self.voice_modules = [
                _pactl("load-module", "module-null-sink", f"sink_name={self.voice_sink}",
                       f"sink_properties=device.description={self.voice_sink}"),
                _pactl("load-module", "module-remap-source", f"master={self.voice_sink}.monitor",
                       f"source_name={self.voice_mic}", f"source_properties=device.description={self.voice_mic}"),
            ]
        except Exception:
            log.warning("Could not create the notetaker's voice device; it will answer in chat only")
            self.voice_modules = []

    def start_recording(self) -> None:
        self.ffmpeg = subprocess.Popen(
            [
                "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
                # Read the sink in large pieces with a deep queue, so a busy
                # CPU (a screen share being decoded) delays ffmpeg instead of
                # overflowing the sink and dropping audio.
                "-thread_queue_size", "4096",
                "-f", "pulse", "-fragment_size", str(PULSE_FRAGMENT_BYTES), "-i", f"{self.sink}.monitor",
                # Pulse timestamps follow the wall clock, so if ffmpeg itself
                # ever stalls the file would get a hole in its timeline, which
                # players stutter over. Fill any hole with silence instead.
                "-af", "aresample=async=1:first_pts=0",
                "-ac", "1", "-ar", "48000",
                "-c:a", "libopus", "-b:a", "48k", "-application", "voip",
                "-f", "webm", str(self.audio_path),
            ],
            stdin=subprocess.DEVNULL,
            env={**os.environ, "PULSE_LATENCY_MSEC": str(PULSE_LATENCY_MS)},
        )
        self.captions.audio_started_at = time.monotonic()
        log.info("Recording %s.monitor -> %s", self.sink, self.audio_path)

    def stop_recording(self) -> None:
        if self.ffmpeg and self.ffmpeg.poll() is None:
            # SIGINT lets ffmpeg write the WebM trailer; a kill would not.
            self.ffmpeg.send_signal(signal.SIGINT)
            try:
                self.ffmpeg.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.ffmpeg.kill()
        if self.captions.audio_started_at is not None and not self.recorded_seconds:
            self.recorded_seconds = time.monotonic() - self.captions.audio_started_at

    def remove_sink(self) -> None:
        for module in reversed(getattr(self, "voice_modules", [])):
            try:
                _pactl("unload-module", module)
            except Exception:
                pass
        if self.sink_module:
            try:
                _pactl("unload-module", self.sink_module)
            except Exception:
                log.warning("Could not unload sink %s", self.sink)

    # --- Meet --------------------------------------------------------------

    async def join(self, page: Page) -> None:
        url = self.job["meet_url"]
        await page.goto(url + ("&" if "?" in url else "?") + "hl=en", wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)
        await self.shot(page, "01_loaded")

        if "accounts.google.com" in page.url:
            raise RuntimeError(
                "Google sent the notetaker to a sign-in page — its saved session has "
                "expired. Re-run generate_auth.py and copy the new auth.json to the server."
            )

        # Signed out, Meet asks for a guest name instead. Joining as a named
        # guest still works — it just always needs the host to admit it.
        name_box = page.locator('input[aria-label="Your name"], input[placeholder="Your name"]').first
        signed_out = await name_box.is_visible()
        if signed_out:
            log.warning("Notetaker is not signed in to Google; joining as guest %r", config.BOT_DISPLAY_NAME)
            await name_box.fill(config.BOT_DISPLAY_NAME)

        await _click_if_visible(page, 'button[aria-label*="Turn off microphone"]')
        if self.avatar_camera:
            await _click_if_visible(page, 'button[aria-label*="Turn on camera"]')
        else:
            await _click_if_visible(page, 'button[aria-label*="Turn off camera"]')
        await _click_if_visible(page, 'button:has-text("Got it")')
        # Meet's "hear you / see you" permission modals. Both can be in the DOM
        # at once with only one visible, so dismiss them blind.
        for _ in range(3):
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
        await self.shot(page, "02_prejoin")

        for text in JOIN_BUTTON_TEXTS:
            if await _click_if_visible(page, f'button:has-text("{text}")', timeout_ms=2500):
                log.info('Clicked "%s"', text)
                if text == "Ask to join":
                    # Someone had to let us in, so someone was in the call.
                    self.admitted_by_host = True
                    self.report("waiting_for_admission", "Asked to join — waiting for the host to admit the notetaker")
                break
        else:
            text = await _page_text(page)
            if any(p in text for p in REJECTED_PHRASES):
                raise AdmissionDenied(f"Meet refused entry before the lobby: {text[:200]!r}")
            raise RuntimeError("No join button found on the Meet pre-join screen")

        await self.await_admission(page, signed_out)

    def rejection_reason(self, page_text: str, signed_out: bool) -> str:
        return _rejection_reason(page_text, signed_out)

    async def lobby_tick(self, page: Page, text: str) -> None:
        """Anything else to check while waiting to be let in."""

    async def await_admission(self, page: Page, signed_out: bool = False) -> None:
        url = teams_dom.loggable_url(self.job["meet_url"])
        deadline = time.monotonic() + config.LOBBY_TIMEOUT_SECONDS
        last_stop_check = time.monotonic()
        while time.monotonic() < deadline:
            text = await _page_text(page)
            await self.lobby_tick(page, text)
            waiting_room = any(p in text for p in self.WAITING_ROOM_PHRASES)
            if await page.locator(self.LEAVE_BUTTON).count() and not waiting_room:
                log.info("Admitted to %s", url)
                await self.shot(page, "03_admitted")
                return
            if waiting_room and not self.admitted_by_host:
                # Someone has to bring the bot in, so someone is in the call.
                self.admitted_by_host = True
                log.info("In the waiting room — waiting for a host")
                self.report("waiting_for_admission", "In the waiting room — waiting for the host to bring the notetaker in")
            if any(p in text for p in self.REJECTED_PHRASES):
                await self.shot(page, "03_rejected")
                raise AdmissionDenied(self.rejection_reason(text, signed_out))
            if time.monotonic() - last_stop_check > STOP_CHECK_SECONDS:
                last_stop_check = time.monotonic()
                if self.stop_requested():
                    raise StopRequested("Stopped from Charcha before the host admitted the notetaker")
            await page.wait_for_timeout(2000)
        await self.shot(page, "03_lobby_timeout")
        raise AdmissionTimeout(f"Not admitted within {config.LOBBY_TIMEOUT_SECONDS // 60} minutes")

    async def captions_on(self, page: Page) -> bool:
        return bool(
            await page.locator('button[aria-label*="Turn off captions"]').count()
            or await page.locator('[role="region"][aria-label*="aption"]').count()
        )

    async def try_captions(self, page: Page) -> None:
        if not await _click_if_visible(page, 'button[aria-label*="Turn on captions"]', timeout_ms=1500):
            await page.keyboard.press("Shift+KeyC")

    async def enable_captions(self, page: Page) -> bool:
        """Captions carry the speakers' names. A failure here is not final:
        stay() keeps retrying for the whole meeting."""
        await page.wait_for_timeout(3000)
        for _ in range(5):
            if await self.captions_on(page):
                log.info("Captions on")
                return True
            await self.try_captions(page)
            await page.wait_for_timeout(2000)
        await self.shot(page, "04_captions_failed")
        log.warning("Could not turn captions on yet — retrying every %ss", CAPTION_RETRY_SECONDS)
        return False

    async def announce(self, page: Page) -> None:
        """Tells everyone in the call, in chat, that the notetaker is here and
        recording, who invited it, and how to make it leave."""
        if not config.ANNOUNCE_IN_CHAT:
            return
        notice = meet_chat.join_notice(
            config.BOT_DISPLAY_NAME,
            self.job.get("requested_by_name"),
            self.job.get("app_url"),
            config.EXIT_PHRASES[0] if config.EXIT_PHRASES else "notetaker please leave",
        )
        self.chat.remember_sent(notice)
        if await meet_chat.send(page, notice):
            log.info("Posted the join notice in chat")
            self.chat_ready = True
        else:
            await self.shot(page, "05_chat_failed")

    async def speak(self, page: Page, text: str) -> None:
        """Says `text` in the call with Gnani Timbre: unmute, play the audio
        into the notetaker's microphone, mute again. Never raises."""
        if not config.SPEAK_IN_CALL or not getattr(self, "voice_modules", None):
            return
        audio = await asyncio.to_thread(uploader.speech, spoken_summary(text))
        if not audio:
            return
        path = self.dir / f"speech_{uuid.uuid4().hex[:6]}.mp3"
        path.write_bytes(audio)
        try:
            if not await _click_if_visible(page, 'button[aria-label*="Turn on microphone"]', timeout_ms=1500):
                await page.keyboard.press("Control+KeyD")
            await page.wait_for_timeout(400)
            await page.evaluate("window.__charchaSpeaking = true")
            await asyncio.to_thread(
                subprocess.run,
                ["ffmpeg", "-nostdin", "-loglevel", "error", "-re", "-i", str(path), "-ac", "1", "-ar", "48000",
                 "-f", "pulse", "-device", self.voice_sink, "charcha-voice"],
                timeout=120,
            )
            await page.wait_for_timeout(300)
            log.info("Spoke %d bytes of audio in the call", len(audio))
        except Exception as error:
            log.warning("Could not speak in the call: %s", error)
        finally:
            await page.evaluate("window.__charchaSpeaking = false")
            if not await _click_if_visible(page, 'button[aria-label*="Turn off microphone"]', timeout_ms=1500):
                await page.keyboard.press("Control+KeyD")

    async def post_reply(self, page: Page, reply: str | None, kind: str) -> None:
        if not reply:
            log.warning("No %s reply came back from Charcha", kind)
            return
        self.chat.remember_sent(reply)
        sent = await meet_chat.send(page, reply)
        log.info("Chat %s %s: %s", kind, "posted" if sent else "NOT posted", reply[:160].replace("\n", " / "))
        await self.speak(page, reply)
        self.replies = getattr(self, "replies", 0) + 1
        await self.shot(page, f"06_chat_{kind}_{self.replies}")

    def spoken_questions(self) -> list[tuple[str, str]]:
        """(speaker, question) for each "Charcha, ..." said aloud, once the
        speaker has paused, so the whole question is in the captions."""
        found = []
        handled = getattr(self, "_spoken_handled", set())
        self._spoken_handled = handled
        now = time.monotonic()
        for block_id, (speaker, text, changed) in list(self.captions.latest.items()):
            if now - changed < SPOKEN_QUESTION_PAUSE_SECONDS:
                continue
            if speaker.strip().lower() in {"you", config.BOT_DISPLAY_NAME.lower()}:
                continue  # the notetaker's own voice
            for match in WAKE_RE.finditer(text):
                question = re.split(r"(?<=[.!?])\s", match.group(1).strip())[0].strip(" ,.?!")
                key = (block_id, match.start())
                if key in handled or len(question) < 4:
                    continue
                handled.add(key)
                if wants_exit(f"charcha {question}"):
                    continue
                found.append((speaker, question))
        return found

    async def answer_chat(self, page: Page) -> None:
        """Answers new "Charcha, ..." messages in the call's chat from what
        was said so far. Never raises: chat must not cost the recording."""
        if not self.chat_ready or not config.ANSWER_IN_CHAT:
            return
        spoken = [(f"asked aloud by {who}" if who else "asked aloud", q) for who, q in self.spoken_questions()]
        typed = [("", q) for q in await self.chat.new_questions(page)]
        for asked, question in (typed + spoken)[:3]:
            log.info("%s question: %s", "Spoken" if asked else "Chat", question[:120])
            task = meet_chat.task_text(question)
            if task and self.capture_request_id:
                reply = await asyncio.to_thread(uploader.live_task, task, self.capture_request_id)
                await self.post_reply(page, reply, "task")
                continue
            reply = await asyncio.to_thread(
                uploader.live_answer,
                question,
                self.captions.export(),
                self.capture_request_id,
                self.job.get("title") or "",
            )
            if reply and asked:
                reply = f'"{question}" ({asked}):\n{reply}'
            await self.post_reply(page, reply, "answer")

    async def stay(self, page: Page) -> str:
        """Blocks until the bot should leave; returns why."""
        joined = time.monotonic()

        def hard_stop() -> float:
            """Calendar end + OVERRUN_MINUTES (re-read: the event may be
            extended mid-meeting), never past MAX_MEETING_MINUTES and never
            sooner than 15 minutes after joining."""
            limit = joined + config.MAX_MEETING_MINUTES * 60
            if self.job.get("event_end"):
                event_end = datetime.fromisoformat(self.job["event_end"])
                overrun = (event_end + timedelta(minutes=config.OVERRUN_MINUTES) - datetime.now(UTC)).total_seconds()
                limit = min(limit, max(time.monotonic() + overrun, joined + 15 * 60))
            return limit

        # Only a counted second person, or someone talking, is company. Being
        # admitted isn't: the host may admit and step away, and Meet's count
        # (the bot draws no video tiles) can read 1 for a moment — which made
        # the bot leave admitted calls after 13-54 s with nothing recorded
        # (production, 2026-10-06..09).
        others_seen = False
        alone_since: float | None = None
        last_count = -1
        last_stop_check = 0.0
        last_caption_check = time.monotonic()
        captions_were_on = self.captions_enabled
        while True:
            if page.is_closed():
                return "page closed"
            if time.monotonic() - last_caption_check > CAPTION_RETRY_SECONDS:
                last_caption_check = time.monotonic()
                if await self.captions_on(page):
                    if not captions_were_on:
                        log.info("Captions on (after retrying)")
                    captions_were_on = True
                else:
                    if captions_were_on:
                        log.warning("Captions went off — turning them back on")
                    captions_were_on = False
                    await self.try_captions(page)
            if time.monotonic() - last_stop_check > STOP_CHECK_SECONDS:
                last_stop_check = time.monotonic()
                if self.stop_requested():
                    return "stopped from Charcha"
            if self.captions.exit_requested.is_set():
                return "asked to leave"
            if time.monotonic() > hard_stop():
                return "time limit"
            if self.ffmpeg and self.ffmpeg.poll() is not None:
                return "audio recorder stopped"
            text = await _page_text(page)
            if any(p in text for p in self.ENDED_PHRASES) and not await page.locator(self.LEAVE_BUTTON).count():
                return "meeting ended or bot removed"

            try:
                count = await page.evaluate(self.PARTICIPANT_COUNT_JS)
            except Exception:
                count = 0
            if any(p in text for p in self.ALONE_PHRASES):
                count = 1
            if count != last_count:
                log.info("Participants in the call: %s", count or "unknown")
                last_count = count
            # 0 means the DOM did not tell us anything — never act on that.
            if count >= 2:
                others_seen, alone_since = True, None
            elif count == 1 and self.captions.heard_within(SPEECH_IS_COMPANY_SECONDS):
                others_seen, alone_since = True, None
            elif count == 1:
                alone_since = alone_since or time.monotonic()
                limit = config.ALONE_TIMEOUT_SECONDS if others_seen else config.WAIT_FOR_OTHERS_SECONDS
                if time.monotonic() - alone_since > limit:
                    return "everyone else left" if others_seen else "nobody joined"
            await self.answer_chat(page)
            await asyncio.sleep(5)

    async def leave(self, page: Page) -> None:
        if page.is_closed():
            return
        if not await _click_if_visible(page, self.LEAVE_BUTTON, timeout_ms=2000):
            await page.keyboard.press("Control+Alt+KeyQ")
        await page.wait_for_timeout(1500)

    async def save_auth(self, context: BrowserContext) -> None:
        """Google rotates session cookies; persisting them after every meeting
        is what keeps a one-time login working for months."""
        try:
            tmp = config.AUTH_STATE_PATH.with_suffix(".tmp")
            await context.storage_state(path=str(tmp))
            tmp.replace(config.AUTH_STATE_PATH)
        except Exception:
            log.warning("Could not refresh saved Google session", exc_info=True)

    async def grant_media(self, context: BrowserContext) -> None:
        await context.grant_permissions(["microphone", "camera"], origin="https://meet.google.com")
        if self.avatar_camera:
            await context.add_init_script(
                AVATAR_CAMERA_JS
                .replace("__IDLE__", base64.b64encode(config.AVATAR_IDLE.read_bytes()).decode())
                .replace("__SPEAKING__", base64.b64encode(config.AVATAR_SPEAKING.read_bytes()).decode())
            )

    async def run(self) -> str:
        self.create_sink()
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=False,  # on Xvfb — headless Chromium renders no WebRTC audio
                    env={**os.environ, "PULSE_SINK": self.sink, "PULSE_SOURCE": self.voice_mic, "PULSE_LATENCY_MSEC": str(PULSE_LATENCY_MS)},
                    ignore_default_args=["--enable-automation"],
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--use-fake-ui-for-media-stream",
                        "--autoplay-policy=no-user-gesture-required",
                        "--disable-blink-features=AutomationControlled",
                        "--window-size=1280,800",
                    ],
                )
                storage = str(config.AUTH_STATE_PATH) if self.USES_GOOGLE_LOGIN and config.AUTH_STATE_PATH.exists() else None
                context = await browser.new_context(storage_state=storage, viewport={"width": 1280, "height": 800})
                await self.grant_media(context)
                await context.add_init_script(HIDE_VIDEO_JS)
                page = await context.new_page()
                try:
                    self.report("joining", "Opening the meeting")
                    await self.join(page)
                    self.start_recording()
                    self.report("capturing", "Admitted — recording")
                    await page.expose_function("onCaptions", self.captions.on_captions)
                    await page.evaluate(self.CAPTION_WATCHER_JS)
                    self.captions_enabled = await self.enable_captions(page)
                    await self.announce(page)
                    reason = await self.stay(page)
                    log.info("Leaving: %s", reason)
                    await self.leave(page)
                    self.report("stopped", f"Left the meeting: {reason}")
                    return reason
                except Exception:
                    await self.shot(page, "99_error")
                    raise
                finally:
                    self.stop_recording()
                    if storage:
                        await self.save_auth(context)
                    await browser.close()
        finally:
            self.stop_recording()
            self.remove_sink()

    def hand_off(self) -> Path | None:
        captions = self.captions.export()
        has_audio = self.audio_path.exists() and self.audio_path.stat().st_size > 0
        if not has_audio and not captions:
            log.info("Nothing captured; not uploading")
            return None
        metadata = {
            "event_id": self.job.get("event_id") or f"adhoc-{self.session_id}",
            "event_start": self.job.get("event_start") or datetime.now(UTC).isoformat(),
            "title": self.job.get("title") or "",
            "organizer_email": self.job.get("organizer_email"),
            "attendees": self.job.get("attendees") or [],
            "captions": captions,
            "duration_seconds": int(self.recorded_seconds),
            "language": config.MEETING_LANGUAGE,
            "bot_display_name": config.BOT_DISPLAY_NAME,
            "capture_request_id": self.capture_request_id,
        }
        return uploader.stage(self.session_id, metadata, self.audio_path if has_audio else None)


class TeamsSession(MeetingSession):
    """A Microsoft Teams meeting, joined as an anonymous guest."""

    LEAVE_BUTTON = teams_dom.LEAVE_BUTTON
    WAITING_ROOM_PHRASES = teams_dom.WAITING_ROOM_PHRASES
    REJECTED_PHRASES = teams_dom.REJECTED_PHRASES
    ENDED_PHRASES = teams_dom.ENDED_PHRASES
    ALONE_PHRASES = teams_dom.ALONE_PHRASES
    CAPTION_WATCHER_JS = teams_dom.CAPTION_WATCHER_JS
    PARTICIPANT_COUNT_JS = teams_dom.PARTICIPANT_COUNT_JS
    USES_GOOGLE_LOGIN = False

    PREJOIN_TIMEOUT_SECONDS = 45
    JOIN_ENABLE_SECONDS = 10

    async def announce(self, page: Page) -> None:
        # Anonymous Teams guests often can't post in chat; the notice is Meet-only.
        return

    def __init__(self, job: dict) -> None:
        super().__init__(job)
        # The menu items are toggles and the caption list only exists once
        # someone has spoken, so a click can't be checked at once. It's made
        # once; pressing it again later would turn captions off.
        self.captions_requested = False
        self.logo_camera = config.TEAMS_LOGO_CAMERA and config.TEAMS_LOGO_IMAGE.exists()
        if config.TEAMS_LOGO_CAMERA and not self.logo_camera:
            log.warning("TEAMS_LOGO_CAMERA is on but %s is missing; joining with the camera off", config.TEAMS_LOGO_IMAGE)

    async def grant_media(self, context: BrowserContext) -> None:
        # Not tied to one origin: the link's host and the client's can differ.
        await context.grant_permissions(["microphone", "camera"])
        if self.logo_camera:
            # Not Chromium's --use-fake-device-for-media-stream: with it, Teams
            # sat on "Connecting" and never reached the lobby (live, 2026-11-04).
            image = base64.b64encode(config.TEAMS_LOGO_IMAGE.read_bytes()).decode()
            await context.add_init_script(teams_dom.LOGO_CAMERA_JS.replace("__LOGO_BASE64__", image))

    def rejection_reason(self, page_text: str, signed_out: bool) -> str:
        return teams_dom.rejection_reason(page_text)

    def check_reachable(self, page: Page, text: str) -> None:
        if teams_dom.is_login_url(page.url):
            raise AdmissionDenied(
                "Microsoft Teams blocked the notetaker: this meeting only lets people with a Microsoft account "
                "join, so the host never saw a request. Allow anonymous participants in the meeting options "
                "(or in the Teams admin center)"
            )
        if any(phrase in text for phrase in teams_dom.NOT_FOUND_PHRASES):
            raise MeetingUnavailable(
                "Teams can't find this meeting. It may have ended, or the link may be wrong or missing its "
                "passcode. Copy the whole link from the invite"
            )

    async def lobby_tick(self, page: Page, text: str) -> None:
        self.check_reachable(page, text)
        # Teams can ask this after "Join now", which then has to be pressed again.
        if await _click_if_visible(page, teams_dom.NO_AV_CONFIRM, timeout_ms=200):
            await _click_if_visible(page, teams_dom.JOIN_BUTTON, timeout_ms=1500)

    async def join(self, page: Page) -> None:
        await page.goto(self.job["meet_url"], wait_until="domcontentloaded")
        await self.shot(page, "01_loaded")
        # The launcher offers the desktop app first; links can also skip it.
        await _click_if_visible(page, teams_dom.CONTINUE_IN_BROWSER, timeout_ms=15000)
        await self.wait_for_prejoin(page)
        await self.set_up_prejoin(page)
        await self.shot(page, "02_prejoin")
        # Can appear after the join screen does, and blocks its buttons.
        await _click_if_visible(page, teams_dom.NO_AV_CONFIRM, timeout_ms=1000)

        join = page.locator(teams_dom.JOIN_BUTTON).first
        deadline = time.monotonic() + self.JOIN_ENABLE_SECONDS
        while not await join.is_enabled():
            if time.monotonic() > deadline:
                said = await page.evaluate(teams_dom.NAME_REJECTED_JS)
                raise RuntimeError(f"Teams kept \"Join now\" disabled for the name {config.BOT_DISPLAY_NAME!r}. {said}".strip())
            await page.wait_for_timeout(500)
        await join.click()
        log.info('Clicked "Join now"')
        await self.await_admission(page)

    async def wait_for_prejoin(self, page: Page) -> None:
        deadline = time.monotonic() + self.PREJOIN_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            self.check_reachable(page, await _page_text(page))
            await _click_if_visible(page, teams_dom.NO_AV_CONFIRM, timeout_ms=200)
            if await page.locator(teams_dom.JOIN_BUTTON).count():
                return
            await page.wait_for_timeout(1000)
        await self.shot(page, "02_no_prejoin")
        raise MeetingUnavailable(
            "Teams never showed its join screen for this link. Check that it's the whole link from the invite, "
            "including the passcode"
        )

    async def set_up_prejoin(self, page: Page) -> None:
        name = page.locator(teams_dom.NAME_INPUT).first
        if await name.count():
            await name.fill(config.BOT_DISPLAY_NAME)
        for toggle, wanted in ((teams_dom.CAMERA_TOGGLE, self.logo_camera), (teams_dom.MIC_TOGGLE, False)):
            box = page.locator(toggle).first
            try:
                if await box.is_checked(timeout=3000) != wanted:
                    await box.click(force=True)  # the switch's input sits under its label
            except Exception:
                log.info("No %s on the Teams join screen", toggle)
        audio = page.locator(teams_dom.COMPUTER_AUDIO).first
        try:
            if not await audio.is_checked(timeout=3000):
                await audio.click(force=True)
        except Exception:
            log.warning("Could not confirm Computer audio on the Teams join screen")
        await _click_if_visible(page, teams_dom.SPEAKER_ON, timeout_ms=500)

    async def captions_on(self, page: Page) -> bool:
        return self.captions_requested or bool(await page.locator(teams_dom.CAPTIONS_RENDERER).count())

    async def try_captions(self, page: Page) -> None:
        if not await _click_if_visible(page, teams_dom.MORE_BUTTON, timeout_ms=3000):
            return
        await page.wait_for_timeout(800)
        result = await page.evaluate(teams_dom.CLICK_CAPTIONS_ITEM_JS)
        if result:
            log.info("Teams captions: %s", result)
            self.captions_requested = True
        await page.keyboard.press("Escape")

    async def leave(self, page: Page) -> None:
        if page.is_closed():
            return
        await _click_if_visible(page, self.LEAVE_BUTTON, timeout_ms=2000)
        # Otherwise closing the browser, which follows, drops the call anyway.
        await _click_if_visible(page, teams_dom.LEAVE_CONFIRM, timeout_ms=1500)
        await page.wait_for_timeout(1500)


def session_for(job: dict) -> MeetingSession:
    return TeamsSession(job) if teams_dom.is_teams_url(job["meet_url"]) else MeetingSession(job)


def log_label(job: dict) -> str:
    """Goes inside a logging format string, where a URL's %7b would blow up."""
    url = teams_dom.loggable_url(job["meet_url"]).rstrip("/")
    return re.sub(r"[^\w-]", "", job.get("meeting_code") or url.rsplit("/", 1)[-1])[:40]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, help="Job JSON written by the scheduler")
    parser.add_argument("--url", help="Join this Meet or Teams link directly (ad hoc)")
    parser.add_argument("--organizer", help="Ad hoc only: Charcha email to file the meeting under")
    args = parser.parse_args()
    if args.job:
        job = json.loads(args.job.read_text(encoding="utf-8"))
    elif args.url:
        job = {"meet_url": args.url, "organizer_email": args.organizer, "attendees": []}
    else:
        parser.error("pass --job or --url")

    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [{log_label(job)}] %(levelname)s %(message)s",
    )
    session = session_for(job)
    exit_code = 0
    try:
        asyncio.run(session.run())
    except AdmissionDenied as error:
        log.warning("Not admitted: %s", error)
        session.report("denied", str(error))
        exit_code = 1
    except AdmissionTimeout as error:
        log.warning("Gave up waiting in the lobby: %s", error)
        session.report("timed_out", str(error))
        exit_code = 1
    except StopRequested as error:
        log.info("%s", error)
        # Never got in, so there's no recording to wait for: "stopped" would
        # leave Charcha showing "processing the recording" until it times out.
        session.report("cancelled", str(error))
    except MeetingUnavailable as error:
        log.warning("Meeting unavailable: %s", error)
        session.report("failed", str(error))
        exit_code = 1
    except Exception as error:
        log.exception("Meeting session failed")
        session.report("failed", f"{type(error).__name__}: {str(error)[:300]}")
        exit_code = 1
    # Whatever was captured before a failure is still worth keeping.
    folder = session.hand_off()
    if folder is not None:
        uploader.upload(folder)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
