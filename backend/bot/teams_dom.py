"""What the notetaker knows about Microsoft Teams' web client.

Everything here is Microsoft's markup and wording, kept apart so that when
Teams changes, this is the only file to touch. The join screens were read off
the live client (2026-11); the in-call parts are confirmed only by a real
meeting, so a miss must degrade (no speaker names, no early exit), never fail
the visit.

The notetaker joins as an anonymous guest: there's no Microsoft account behind
it, so the host admits it from the lobby unless the meeting lets guests skip.
"""

from urllib.parse import urlsplit

TEAMS_HOSTS = ("teams.microsoft.com", "teams.live.com", "teams.cloud.microsoft")
LOGIN_HOSTS = ("login.microsoftonline.com", "login.microsoft.com", "login.live.com", "login.windows.net")


def is_teams_url(url: str) -> bool:
    return (urlsplit(url).hostname or "").lower() in TEAMS_HOSTS


def is_login_url(url: str) -> bool:
    return (urlsplit(url).hostname or "").lower() in LOGIN_HOSTS


def loggable_url(url: str) -> str:
    """Teams links carry the meeting passcode in the query; logs don't need it."""
    return url.split("?", 1)[0]


CONTINUE_IN_BROWSER = '[data-tid="joinOnWeb"]'
NAME_INPUT = '[data-tid="prejoin-display-name-input"]'
JOIN_BUTTON = '[data-tid="prejoin-join-button"]'
CAMERA_TOGGLE = '[data-tid="toggle-video"]'
MIC_TOGGLE = '[data-tid="toggle-mute"]'
# "Don't use audio" would leave the recording silent, so this is forced on.
COMPUTER_AUDIO = 'input[aria-label="Computer audio"]'
SPEAKER_ON = 'button[aria-label*="Turn speaker on"], button[aria-label*="Speaker is off"]'
# Teams asks this when joining with camera and mic off. It holds up the join,
# and only concerns what the notetaker sends: it still hears the call.
NO_AV_CONFIRM = 'button:has-text("Continue without audio or video")'

LEAVE_BUTTON = '#hangup-button, button[data-tid="hangup-main-btn"], button[aria-label="Leave"]'
LEAVE_CONFIRM = '[role="dialog"] button:has-text("Leave"), [role="alertdialog"] button:has-text("Leave")'

MORE_BUTTON = '#callingButtons-showMoreBtn, button[aria-label="More"], button[aria-label="More options"]'

# All lower-cased page text, with both apostrophes where Teams uses them.
WAITING_ROOM_PHRASES = [
    "someone will let you in shortly",
    "when the meeting starts, we'll let people know you're here",
    "when the meeting starts, we’ll let people know you’re here",
    "we've let people in the meeting know you're waiting",
    "we’ve let people in the meeting know you’re waiting",
    "waiting for someone to let you in",
    "waiting to be admitted",
    "you're in the lobby",
    "you’re in the lobby",
]
REJECTED_PHRASES = [
    "you were denied",
    "denied access",
    "denied entry",
    "no one responded",
    "nobody responded",
]
NOT_FOUND_PHRASES = ["we can't find this meeting", "we can’t find this meeting"]
ENDED_PHRASES = [
    "you've been removed from this meeting",
    "you’ve been removed from this meeting",
    "you have been removed from this meeting",
    "you left the meeting",
    "you left the call",
    "meeting ended",
    "call ended",
    "rejoin",
]
ALONE_PHRASES = [
    "you're the only one here",
    "you’re the only one here",
    "waiting for others to join",
]

# Teams keeps "Join now" disabled until the name passes its rule (letters,
# numbers, spaces and - ' . _ @); this is its own explanation of why.
NAME_REJECTED_JS = """
() => (document.body.innerText || "").split("\\n").map((l) => l.trim()).find((l) => /can only include/i.test(l)) || ""
"""

# Guest menu: More -> "Captions". Host menu: More -> "Language and speech" ->
# "... live captions". Returns what it did. An item already checked is left
# alone — these are toggles, so clicking again would turn captions off.
CLICK_CAPTIONS_ITEM_JS = """
async () => {
  const items = () => [...document.querySelectorAll('[role="menuitem"], [role="menuitemcheckbox"], [role="menuitemradio"]')]
    .filter((el) => el.offsetParent);
  const press = (el) => {
    if (el.getAttribute("aria-checked") === "true") return "already on";
    const label = (el.textContent || "").trim().toLowerCase();
    if (label.includes("turn off") || label.includes("hide")) return "already on";
    el.click();
    return "clicked";
  };
  const direct = items().find((el) =>
    ["captions", "show live captions", "turn on live captions"].includes((el.textContent || "").trim().toLowerCase())
  );
  if (direct) return press(direct);
  const language = items().find((el) => /language.*speech/i.test(el.textContent || ""));
  if (!language) return "";
  language.click();
  await new Promise((resolve) => setTimeout(resolve, 800));
  const live = items().find((el) => /live captions/i.test(el.textContent || ""));
  return live ? press(live) : "";
}
"""

# Presents a still logo as the notetaker's camera. Teams asks for media through
# these two calls, so nothing else in the browser changes: the microphone stays
# the real, silent one. 5 fps of an unchanging picture keeps encoding cheap.
LOGO_CAMERA_JS = """
(() => {
  const media = navigator.mediaDevices;
  if (!media) return;
  const canvas = document.createElement("canvas");
  canvas.width = 640;
  canvas.height = 360;
  const ctx = canvas.getContext("2d");
  const logo = new Image();
  const draw = () => {
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (logo.complete && logo.naturalWidth) ctx.drawImage(logo, 0, 0, canvas.width, canvas.height);
  };
  logo.src = "data:image/png;base64,__LOGO_BASE64__";
  // A canvas stream only produces frames when the canvas is drawn on.
  setInterval(draw, 200);

  const getUserMedia = media.getUserMedia.bind(media);
  media.getUserMedia = async (constraints) => {
    if (!constraints || !constraints.video) return getUserMedia(constraints);
    const stream = canvas.captureStream(5);
    if (constraints.audio) {
      // The server has no microphone, and one failed request would fail the
      // camera with it. The notetaker never speaks, so going without is fine.
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
    const camera = { deviceId: "charcha-logo", groupId: "bhadra", kind: "videoinput", label: "Bhadra", toJSON() { return this; } };
    return [...devices, camera];
  };
})();
"""

# Polled rather than observed: Teams' caption list is virtualized and drops
# mutations. Each text is paired with the name above it in document order, so
# a turn with no name of its own keeps the previous speaker. An element reused
# for someone else's words gets a new id, so they aren't filed under the old
# name. Guests carry a tag ("Priya (Guest)") that isn't part of their name.
CAPTION_WATCHER_JS = """
() => {
  const ids = new WeakMap();
  const seen = new Map();
  let nextId = 1;
  const clean = (name) => name.replace(/\\s*\\((guest|external|unverified)\\)\\s*$/i, "").trim();

  setInterval(() => {
    const batch = [];
    let speaker = "";
    const nodes = document.querySelectorAll(
      '[data-tid="closed-caption-renderer-wrapper"] [data-tid="author"], ' +
      '[data-tid="closed-caption-renderer-wrapper"] [data-tid="closed-caption-text"]'
    );
    for (const node of nodes) {
      const value = (node.textContent || "").trim();
      if (node.getAttribute("data-tid") === "author") {
        speaker = clean(value);
        continue;
      }
      if (!value) continue;
      const known = ids.get(node);
      if (!known || known.speaker !== speaker) ids.set(node, { id: nextId++, speaker });
      const { id } = ids.get(node);
      if (seen.get(id) === value) continue;
      seen.set(id, value);
      batch.push({ id, speaker, text: value });
    }
    if (batch.length) window.onCaptions(batch);
  }, 1000);
}
"""
CAPTIONS_RENDERER = '[data-tid="closed-caption-renderer-wrapper"]'

# Tiles can only prove company: with video hidden and people off camera, one
# visible tile doesn't mean the notetaker is alone, and leaving on that would
# cut a live recording short. So "1" only ever comes from the People button;
# 0 means unknown, which is never acted on.
PARTICIPANT_COUNT_JS = """
() => {
  const tiles = document.querySelectorAll("[data-stream-type], [data-tid*='participant-tile']").length;
  let badge = 0;
  for (const el of document.querySelectorAll("button[aria-label], [role=button][aria-label], #roster-button")) {
    const label = el.getAttribute("aria-label") || "";
    if (el.id !== "roster-button" && !/people|participant/i.test(label)) continue;
    // Seen live: aria-label "People", text "10\\nPeople".
    const match = label.match(/(\\d+)/) || (el.textContent || "").match(/(\\d+)/);
    if (match) badge = Math.max(badge, Number(match[1]));
  }
  return badge || (tiles >= 2 ? tiles : 0);
}
"""


def rejection_reason(page_text: str) -> str:
    if "no one responded" in page_text or "nobody responded" in page_text:
        return "Nobody admitted the notetaker before Teams gave up"
    return "Someone in the call denied the notetaker's request to join"
