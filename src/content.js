// Runs on Google Meet. Shows one small Charcha control in the call: invite the
// notetaker, see whether it's waiting, recording or done, and stop it.
// All backend calls go through background.js (Meet's CORS blocks them here).

const CHECK_URL_MS = 1_500;
const POLL_MS = 8_000;
// How soon an auto-invite is retried after Charcha couldn't be reached.
const AUTO_INVITE_RETRY_MS = 30_000;

const ICON = {
  logo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M5 17.5V8.8L12 4l7 4.8v8.7L12 21l-7-3.5Z"/><path d="M8.5 15V10.8L12 8.5l3.5 2.3V15L12 17l-3.5-2Z"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  chevron: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m9 6 6 6-6 6"/></svg>',
};

const STYLE = `
:host { all: initial; }
* { box-sizing: border-box; font-family: "Google Sans", Roboto, ui-sans-serif, system-ui, sans-serif; }
.root { position: fixed; left: 16px; bottom: 92px; z-index: 2147483000; color: #faf7f1; }
.card { width: 288px; border-radius: 16px; background: rgba(29, 26, 59, .96); border: 1px solid rgba(255,255,255,.1);
  box-shadow: 0 18px 50px -18px rgba(0,0,0,.6); padding: 12px; backdrop-filter: blur(10px);
  animation: in .18s ease-out; }
@keyframes in { from { opacity: 0; transform: translateY(6px); } }
@media (prefers-reduced-motion: reduce) { .card, .dot.live::after { animation: none !important; } }
.head { display: flex; align-items: center; gap: 8px; }
.mark { width: 26px; height: 26px; border-radius: 8px; background: #2e2a8c; color: #fff; display: grid; place-items: center; flex: none; }
.mark svg { width: 16px; height: 16px; }
.title { flex: 1; min-width: 0; font-size: 13px; font-weight: 600; letter-spacing: .1px; }
.icon-btn { width: 26px; height: 26px; border-radius: 8px; border: 0; background: transparent; color: #bdb9e0; display: grid; place-items: center; cursor: pointer; flex: none; }
.icon-btn:hover { background: rgba(255,255,255,.08); color: #fff; }
.icon-btn svg { width: 14px; height: 14px; }
.body { margin: 10px 2px 0; font-size: 12.5px; line-height: 1.45; color: #c8c4eb; }
.status { display: flex; align-items: center; gap: 8px; color: #faf7f1; font-weight: 500; font-size: 13px; }
.dot { position: relative; width: 8px; height: 8px; border-radius: 50%; background: #f0a020; flex: none; }
.dot.live { background: #ef4444; }
.dot.live::after { content: ""; position: absolute; inset: -4px; border-radius: 50%; border: 2px solid rgba(239,68,68,.5); animation: ping 1.6s ease-out infinite; }
.dot.done { background: #5fae74; }
@keyframes ping { to { transform: scale(1.6); opacity: 0; } }
.actions { display: flex; gap: 6px; margin-top: 12px; }
.btn { flex: 1; height: 34px; border-radius: 10px; border: 0; font-size: 13px; font-weight: 600; cursor: pointer; padding: 0 12px; }
.btn.primary { background: #f0a020; color: #3a2606; }
.btn.primary:hover { background: #f5b13f; }
.btn.ghost { background: rgba(255,255,255,.08); color: #faf7f1; }
.btn.ghost:hover { background: rgba(255,255,255,.14); }
.btn.danger { background: rgba(239,68,68,.16); color: #fca5a5; }
.btn.danger:hover { background: rgba(239,68,68,.26); }
.btn:disabled { opacity: .55; cursor: default; }
.btn:focus-visible, .icon-btn:focus-visible, .pill:focus-visible { outline: 2px solid #f5b13f; outline-offset: 2px; }
.note { margin-top: 8px; font-size: 11.5px; color: #9e9ac4; }
.error { margin-top: 8px; font-size: 12px; color: #fca5a5; }
.pill { display: flex; align-items: center; gap: 8px; height: 36px; padding: 0 12px 0 6px; border-radius: 999px; border: 1px solid rgba(255,255,255,.12);
  background: rgba(29, 26, 59, .94); color: #faf7f1; font-size: 12.5px; font-weight: 600; cursor: pointer; box-shadow: 0 10px 30px -14px rgba(0,0,0,.6); }
.pill .mark { width: 24px; height: 24px; border-radius: 999px; }
`;

let host = null;
let shadow = null;
let currentCode = null;
let joinedCodes = new Set();
let state = { loading: true };
let busy = false;
let lastError = null;
// Set while Charcha can't be reached; cleared by the next successful check.
let connectionError = null;
let pollTimer = null;
let collapsed = sessionStorage.getItem("charcha-collapsed") === "1";

function meetCode() {
  const match = /^\/([a-z]{3}-[a-z]{4}-[a-z]{3})(?:\/|$)/i.exec(location.pathname);
  return match ? match[1].toLowerCase() : null;
}

/** In the call itself (not the lobby or the "you left" screen). */
function inCall() {
  return Boolean(document.querySelector('[aria-label*="Leave call" i], [data-is-muted]'));
}

function meetingTitle() {
  const fromTitle = document.title.replace(/\s*[-|]\s*Google Meet\s*$/i, "").replace(/^Meet\s*[-–]\s*/i, "").trim();
  return fromTitle && !/^[a-z]{3}-[a-z]{4}-[a-z]{3}$/i.test(fromTitle) && fromTitle !== "Google Meet" ? fromTitle : "";
}

function send(type, payload = {}) {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage({ type, ...payload }, (response) => {
        if (chrome.runtime.lastError) resolve({ ok: false, error: "Reload this tab to reconnect Charcha." });
        else resolve(response || { ok: false });
      });
    } catch {
      // The extension was updated or reloaded underneath this page.
      resolve({ ok: false, error: "Reload this tab to reconnect Charcha." });
    }
  });
}

function mount() {
  if (host) return;
  host = document.createElement("div");
  host.id = "charcha-meet-control";
  shadow = host.attachShadow({ mode: "closed" });
  const style = document.createElement("style");
  style.textContent = STYLE;
  shadow.append(style, Object.assign(document.createElement("div"), { className: "root" }));
  document.documentElement.append(host);
}

function unmount() {
  host?.remove();
  host = null;
  shadow = null;
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "onclick") node.addEventListener("click", value);
    else if (key === "html") node.innerHTML = value;
    else if (value !== undefined && value !== null && value !== false) node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of [].concat(children)) if (child) node.append(typeof child === "string" ? document.createTextNode(child) : child);
  return node;
}

function view() {
  const capture = state.capture;
  if (state.loading) return null;
  if (!state.loggedIn) {
    return {
      pill: "Charcha: sign in",
      status: null,
      body: "Sign in to Charcha to send the notetaker into this call.",
      actions: [{ label: "Open Charcha", kind: "primary", run: () => send("open-workspace", { path: "/login" }) }],
    };
  }
  if (!capture || ["cancelled", "denied", "timed_out", "failed"].includes(capture.status)) {
    const previous = capture && capture.status !== "cancelled"
      ? `Last attempt: ${capture.status_label}${capture.status_detail ? `. ${capture.status_detail}` : ""}`
      : null;
    return {
      pill: "Take notes with Charcha",
      status: null,
      body: "Invite the notetaker to transcribe this call and pull out tasks and decisions.",
      note: previous || "Everyone in the call will see it join. Anyone can ask it to leave.",
      actions: [{ label: "Invite notetaker", kind: "primary", run: invite }],
    };
  }
  // A colleague's notetaker is already here: no second bot, just get the notes.
  if (capture.subscribed === false && ["requested", "joining", "waiting_for_admission", "capturing"].includes(capture.status)) {
    const who = capture.requested_by ? `${capture.requested_by}'s notetaker` : "A colleague's notetaker";
    return {
      pill: "Charcha is already here",
      status: { label: capture.status === "capturing" ? "Already recording this call" : "Already on its way", dot: capture.status === "capturing" ? "live" : "" },
      body: `${who} covers this call, so it's recorded once for everyone. Get the notes too?`,
      actions: [{ label: "Get the notes too", kind: "primary", run: invite }],
    };
  }
  if (capture.status === "capturing") {
    return {
      pill: "Charcha is taking notes",
      status: { label: "Recording this call", dot: "live" },
      body: "Notes, tasks and decisions appear in Charcha a few minutes after the call ends.",
      actions: [
        { label: capture.stop_requested ? "Leaving…" : "Stop notetaker", kind: "danger", run: stop, disabled: capture.stop_requested },
      ],
    };
  }
  if (capture.status === "completed") {
    return {
      pill: "Notes ready",
      status: { label: "Notes are ready", dot: "done" },
      body: capture.title ? `“${capture.title}” is in Charcha.` : "This call's transcript and notes are in Charcha.",
      actions: [
        { label: "Open notes", kind: "primary", run: () => send("open-workspace", { path: `/meetings/${capture.meeting_id}` }) },
        { label: "Record again", kind: "ghost", run: invite },
      ],
    };
  }
  if (capture.status === "stopped") {
    return {
      pill: "Charcha is writing notes",
      status: { label: "Writing up notes", dot: "" },
      body: "The notetaker has left. Transcription and notes usually take a few minutes.",
      actions: [],
    };
  }
  const waiting = capture.status === "waiting_for_admission";
  return {
    pill: waiting ? "Admit the Charcha notetaker" : "Notetaker joining",
    status: { label: waiting ? "Waiting to be let in" : capture.status_label || "Joining", dot: "" },
    body: waiting
      ? "It's in the lobby. Admit it from the people panel, or the host can let it in."
      : "The notetaker is on its way into this call.",
    actions: [{ label: "Cancel", kind: "ghost", run: stop, disabled: capture.stop_requested }],
  };
}

function render() {
  if (!shadow) return;
  const root = shadow.querySelector(".root");
  root.replaceChildren();
  const model = view();
  if (!model) return;

  if (collapsed) {
    const dot = model.status?.dot !== undefined ? el("span", { class: `dot ${model.status.dot}` }) : null;
    root.append(
      el("button", {
        class: "pill",
        type: "button",
        "aria-label": `${model.pill}. Show Charcha controls`,
        onclick: () => {
          collapsed = false;
          sessionStorage.setItem("charcha-collapsed", "0");
          render();
        },
      }, [el("span", { class: "mark", html: ICON.logo }), dot, model.pill]),
    );
    return;
  }

  const card = el("div", { class: "card", role: "region", "aria-label": "Charcha notetaker" }, [
    el("div", { class: "head" }, [
      el("span", { class: "mark", html: ICON.logo }),
      el("span", { class: "title" }, "Charcha"),
      el("button", {
        class: "icon-btn",
        type: "button",
        "aria-label": "Minimise",
        title: "Minimise",
        html: ICON.close,
        onclick: () => {
          collapsed = true;
          sessionStorage.setItem("charcha-collapsed", "1");
          render();
        },
      }),
    ]),
    el("div", { class: "body" }, [
      model.status ? el("div", { class: "status" }, [el("span", { class: `dot ${model.status.dot}` }), model.status.label]) : null,
      el("div", { style: model.status ? "margin-top:6px" : undefined }, model.body),
      model.note ? el("div", { class: "note" }, model.note) : null,
      lastError ? el("div", { class: "error", role: "alert" }, lastError) : null,
      connectionError && connectionError !== lastError ? el("div", { class: "error", role: "status" }, `${connectionError} Retrying…`) : null,
    ]),
    model.actions.length
      ? el("div", { class: "actions" }, model.actions.map((action) =>
          el("button", { class: `btn ${action.kind}`, type: "button", disabled: busy || action.disabled, onclick: action.run }, busy ? "Working…" : action.label),
        ))
      : null,
  ]);
  root.append(card);
}

async function refresh() {
  const response = await send("meet-status", { url: location.href });
  if (!response.ok && !response.loggedIn) {
    state = { loading: false, loggedIn: false };
    lastError = response.error || null;
  } else if (response.error) {
    // Charcha is unreachable: keep showing what we last knew (a notetaker
    // already in the call must not turn into a "Send notetaker" button) and
    // say so until the next successful check clears it.
    state = { ...state, loading: false, loggedIn: response.loggedIn, autoInvite: response.autoInvite };
    connectionError = response.error;
  } else {
    state = { loading: false, loggedIn: response.loggedIn, capture: response.capture, autoInvite: response.autoInvite };
    connectionError = null;
  }
  render();
}

async function invite() {
  busy = true;
  lastError = null;
  render();
  const response = await send("invite-notetaker", { url: `https://meet.google.com/${currentCode}`, title: meetingTitle() });
  busy = false;
  if (!response.ok) lastError = response.error || "The notetaker couldn't be sent.";
  else if (response.alreadyThere) lastError = response.error;
  else state.capture = response.capture;
  if (response.ok && response.joinedExisting) lastError = null;
  render();
  void refresh();
}

async function stop() {
  if (!state.capture) return;
  busy = true;
  lastError = null;
  render();
  const response = await send("stop-notetaker", { id: state.capture.id });
  busy = false;
  if (!response.ok) lastError = response.error || "The notetaker couldn't be stopped.";
  else {
    state.capture = response.capture;
    if (response.keptForOthers) {
      lastError = "Colleagues still want these notes, so the notetaker stays. Anyone can say “notetaker please leave”.";
    }
  }
  render();
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(() => {
    if (document.visibilityState === "visible") void refresh();
  }, POLL_MS);
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

// Meet is a single-page app: the room code appears, changes and disappears
// without a page load, so watch the URL instead of relying on load events.
setInterval(() => {
  const code = meetCode();
  if (code !== currentCode) {
    currentCode = code;
    lastError = null;
    connectionError = null;
    state = { loading: true };
    if (code) {
      mount();
      void refresh();
      startPolling();
    } else {
      stopPolling();
      unmount();
    }
  }
  if (code && inCall() && !joinedCodes.has(code)) {
    joinedCodes.add(code);
    void send("meet-joined", { url: `https://meet.google.com/${code}`, title: meetingTitle() }).then((response) => {
      if (response?.capture) {
        state.capture = response.capture;
        render();
      }
      // Charcha was unreachable: try the auto-invite again in a little while.
      if (response?.retry) setTimeout(() => joinedCodes.delete(code), AUTO_INVITE_RETRY_MS);
    });
  }
}, CHECK_URL_MS);

// The popup and background can ask the Meet tab to refresh immediately.
chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "charcha-refresh" && currentCode) void refresh();
});
