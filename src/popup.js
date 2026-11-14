import { api, getSession, isLive, isMine, isTeamsLink, meetCodeFromUrl, workspaceUrl } from "./api.js";

const $ = (selector) => document.querySelector(selector);
// Opened as a plain page (design review), there is no extension runtime:
// everything is served from the fixtures at the bottom of this file.
const PREVIEW = !globalThis.chrome?.runtime?.id;

const backend = PREVIEW ? previewBackend() : {
  session: getSession,
  request: (path, options) => api(path, options),
  message: (type, payload = {}) =>
    new Promise((resolve) => chrome.runtime.sendMessage({ type, ...payload }, (response) => resolve(response || { ok: false }))),
  settings: () => chrome.storage.sync.get({ autoInvite: false, notifyReady: true, sheetsExport: true }),
  saveSetting: (key, value) => chrome.storage.sync.set({ [key]: value }),
  activeTabUrl: async () => (await chrome.tabs.query({ active: true, currentWindow: true }))[0]?.url || "",
  open: (path) => chrome.tabs.create({ url: workspaceUrl(path) }),
};

let session = null;
let captures = [];
let meetingsLoaded = false;
let lastQuestion = "";

// ---------------------------------------------------------------- helpers

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

function formatDay(value) {
  const date = new Date(value);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) return date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (node.hidden = true), 2600);
}

function setStatus(node, message, tone = "") {
  node.textContent = message || "";
  node.className = `status-line${tone ? ` is-${tone}` : ""}`;
}

function empty(container, title, detail) {
  container.innerHTML = "";
  const box = document.createElement("div");
  box.className = "empty";
  box.innerHTML = `<strong>${escapeHtml(title)}</strong>${escapeHtml(detail)}`;
  container.replaceWith(box);
  box.id = container.id;
  box.dataset.empty = "1";
}

/** Lists can be swapped for an empty-state box and back. */
function listNode(id) {
  let node = document.getElementById(id);
  if (node.dataset.empty) {
    const list = document.createElement("div");
    list.id = id;
    list.className = "list";
    node.replaceWith(list);
    node = list;
  }
  return node;
}

function dueLabel(task) {
  if (task.due_date) {
    const due = new Date(task.due_date);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const overdue = due < today;
    const label = due.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
    return { text: overdue ? `Overdue, ${label}` : `Due ${label}`, overdue };
  }
  return task.deadline ? { text: `Due ${task.deadline}`, overdue: false } : null;
}

// ---------------------------------------------------------------- screens

async function boot() {
  session = await backend.session();
  $("#login-screen").hidden = Boolean(session);
  $("#app-screen").hidden = !session;
  if (!session) return;
  const initials = (session.userName || session.userEmail).split(/[\s@.]+/).filter(Boolean).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
  $("#account-initials").textContent = initials || "M";
  $("#account-name").textContent = session.userName || "";
  $("#account-email").textContent = session.userEmail || "";
  void loadNow();
  void loadTasks();
}

function selectTab(name) {
  for (const tab of document.querySelectorAll(".tab")) tab.setAttribute("aria-selected", String(tab.dataset.tab === name));
  for (const panel of document.querySelectorAll(".panel")) panel.hidden = panel.dataset.panel !== name;
  if (name === "meetings" && !meetingsLoaded) void loadMeetings();
  if (name === "ask") $("#ask-input").focus();
}

// ---------------------------------------------------------------- Now

async function loadNow() {
  const [response, tabUrl] = await Promise.all([backend.message("list-captures"), backend.activeTabUrl()]);
  captures = response.ok ? response.captures : [];
  const code = meetCodeFromUrl(tabUrl);
  // The meeting's own status, so a colleague's notetaker in this call shows.
  const meet = code ? await backend.message("meet-status", { url: tabUrl }) : null;
  renderThisMeeting(code, meet?.ok ? meet.capture : undefined);
  renderLive(code);
  const current = code ? captureFor(code) : null;
  if (code && !$("#send-url").value && !(current && isLive(current))) $("#send-url").value = `https://meet.google.com/${code}`;
}

function captureFor(code) {
  const forCode = captures.filter((item) => item.meeting_code === code);
  return forCode.find(isLive) || forCode.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))[0] || null;
}

function renderThisMeeting(code, meetCapture) {
  const card = $("#this-meeting");
  card.hidden = !code;
  if (!code) return;
  const capture = meetCapture === undefined ? captureFor(code) : meetCapture;
  const dot = $("#this-meeting-dot");
  const actions = $("#this-meeting-actions");
  actions.replaceChildren();
  const button = (label, kind, run) => {
    const node = document.createElement("button");
    node.type = "button";
    node.className = `btn btn--${kind}`;
    node.textContent = label;
    node.addEventListener("click", run);
    actions.append(node);
  };

  if (capture && isLive(capture) && capture.subscribed === false) {
    dot.className = `dot ${capture.status === "capturing" ? "is-live" : "is-wait"}`;
    $("#this-meeting-title").textContent = "Already being recorded";
    $("#this-meeting-detail").textContent = `${capture.requested_by || "A colleague"}'s notetaker covers this call.`;
    button("Get the notes too", "primary", async () => {
      const response = await backend.message("invite-notetaker", { url: `https://meet.google.com/${code}`, title: "" });
      toast(response.ok ? "You'll get the notes too." : response.error || "That didn't work.");
      void loadNow();
    });
  } else if (capture && isLive(capture)) {
    const recording = capture.status === "capturing";
    dot.className = `dot ${recording ? "is-live" : "is-wait"}`;
    $("#this-meeting-title").textContent = recording ? "Charcha is taking notes" : capture.status_label;
    $("#this-meeting-detail").textContent = capture.status === "waiting_for_admission"
      ? "It's in the lobby. Admit it from the call."
      : recording ? "Notes appear in Charcha a few minutes after the call." : capture.status_detail || "";
    if (capture.active && !capture.stop_requested) button(recording ? "Stop notetaker" : "Cancel", "danger", () => stop(capture.id));
  } else if (capture?.status === "completed" && capture.meeting_id) {
    dot.className = "dot is-done";
    $("#this-meeting-title").textContent = "Notes are ready";
    $("#this-meeting-detail").textContent = capture.title || "";
    button("Open notes", "primary", () => backend.open(`/meetings/${capture.meeting_id}`));
  } else {
    dot.className = "dot";
    $("#this-meeting-title").textContent = "No notetaker yet";
    $("#this-meeting-detail").textContent = "Everyone in the call will see it join, and anyone can ask it to leave.";
    button("Invite notetaker", "primary", async () => {
      const response = await backend.message("invite-notetaker", { url: `https://meet.google.com/${code}`, title: "" });
      toast(
        !response.ok || response.alreadyThere
          ? response.error || "The notetaker couldn't be sent."
          : response.joinedExisting
            ? "A colleague's notetaker is already here. You'll get the notes too."
            : "Sent. Admit the notetaker when it asks to join.",
      );
      void loadNow();
    });
  }
}

function renderLive(currentCode) {
  const live = captures.filter((item) => isLive(item) && item.meeting_code !== currentCode);
  $("#live-block").hidden = !live.length;
  const list = $("#live-list");
  list.replaceChildren();
  for (const item of live) {
    const row = document.createElement("div");
    row.className = "item";
    row.innerHTML = `<span class="dot ${item.status === "capturing" ? "is-live" : "is-wait"}" style="margin-top:6px"></span>
      <span class="item__main"><span class="item__title">${escapeHtml(item.title || item.meeting_code)}</span><span class="item__meta">${escapeHtml(item.status_label)}</span></span>`;
    if (item.active && !item.stop_requested) {
      const stopButton = document.createElement("button");
      stopButton.type = "button";
      stopButton.className = "btn btn--danger";
      stopButton.style.height = "28px";
      stopButton.textContent = item.status === "capturing" ? "Stop" : "Cancel";
      stopButton.addEventListener("click", () => stop(item.id));
      row.append(stopButton);
    }
    list.append(row);
  }
}

async function stop(id) {
  const response = await backend.message("stop-notetaker", { id });
  toast(
    !response.ok
      ? response.error || "The notetaker couldn't be stopped."
      : response.keptForOthers
        ? "Colleagues still want these notes, so it stays. You won't get them."
        : "The notetaker is leaving the call.",
  );
  void loadNow();
}

async function sendNotetaker(event) {
  event.preventDefault();
  const status = $("#send-status");
  const url = $("#send-url").value.trim();
  const link = url.startsWith("http") ? url : `https://${url}`;
  if (!meetCodeFromUrl(link) && !isTeamsLink(link)) {
    setStatus(status, "Paste a Google Meet or Microsoft Teams meeting link.", "error");
    return;
  }
  $("#send-btn").disabled = true;
  setStatus(status, "Sending…");
  const response = await backend.message("invite-notetaker", { url: url.startsWith("http") ? url : `https://${url}`, title: "" });
  $("#send-btn").disabled = false;
  if (!response.ok) setStatus(status, response.error || "The notetaker couldn't be sent.", "error");
  else if (response.alreadyThere) setStatus(status, response.error, "error");
  else {
    setStatus(status, response.joinedExisting ? "Already being recorded by a colleague's notetaker. You'll get the notes too." : "Sent. Admit the notetaker when it asks to join.", "ok");
    $("#send-consent").checked = false;
  }
  void loadNow();
}

// ---------------------------------------------------------------- Tasks

async function loadTasks() {
  let tasks;
  try {
    tasks = await backend.request("/api/tasks");
  } catch (error) {
    empty(listNode("tasks-list"), "Tasks couldn't load", error.message);
    return;
  }
  // The server's `mine` also covers tasks resolved to your account whose
  // stated owner is written differently ("Raj K." for Raj Kumar).
  const mine = tasks.filter((task) => task.status !== "done" && (task.mine ?? isMine(task, session)));
  mine.sort((a, b) => {
    const dueA = a.due_date ? new Date(a.due_date).getTime() : Infinity;
    const dueB = b.due_date ? new Date(b.due_date).getTime() : Infinity;
    return dueA - dueB;
  });
  const count = $("#task-count");
  count.hidden = !mine.length;
  count.textContent = String(mine.length);
  if (!mine.length) {
    empty(listNode("tasks-list"), "You're all caught up", "Tasks show up here when a meeting names you as the owner.");
    return;
  }
  const list = listNode("tasks-list");
  list.replaceChildren();
  for (const task of mine.slice(0, 25)) {
    const due = dueLabel(task);
    const row = document.createElement("label");
    row.className = "item";
    row.innerHTML = `<input type="checkbox" aria-label="Mark done" />
      <span class="item__main"><span class="item__title">${escapeHtml(task.description)}</span>
      <span class="item__meta">${due ? `<span class="${due.overdue ? "overdue" : ""}">${escapeHtml(due.text)}</span> · ` : ""}${escapeHtml(task.meeting_title)}</span></span>`;
    row.querySelector("input").addEventListener("change", async (event) => {
      const checked = event.target.checked;
      row.classList.toggle("is-done", checked);
      try {
        await backend.request(`/api/tasks/${task.id}`, { method: "PATCH", body: { status: checked ? "done" : "pending" } });
        if (checked) toast("Marked done.");
      } catch (error) {
        event.target.checked = !checked;
        row.classList.toggle("is-done", !checked);
        toast(error.message);
      }
    });
    list.append(row);
  }
}

// ---------------------------------------------------------------- Ask

function renderAnswer(text) {
  const blocks = escapeHtml(text).split(/\n{2,}/);
  return blocks.map((block) => {
    const lines = block.split("\n");
    const inline = (line) => line.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\[(M\d+(?:[:#][^\]]*)?)\]/g, '<span class="cite">$1</span>');
    if (lines.every((line) => /^\s*[-*•]\s+/.test(line))) {
      return `<ul>${lines.map((line) => `<li>${inline(line.replace(/^\s*[-*•]\s+/, ""))}</li>`).join("")}</ul>`;
    }
    return `<p>${lines.map(inline).join("<br>")}</p>`;
  }).join("");
}

async function ask(question) {
  question = question.trim();
  if (!question) return;
  lastQuestion = question;
  const answer = $("#ask-answer");
  const body = $("#ask-answer-body");
  answer.hidden = false;
  $("#ask-suggestions").hidden = true;
  body.className = "answer__body is-loading";
  body.textContent = "Searching your meetings…";
  $("#ask-sources").replaceChildren();
  $("#ask-btn").disabled = true;
  try {
    const result = await backend.request("/api/chat", { method: "POST", body: { query: question, meeting_ids: [], history: [] } });
    body.className = "answer__body";
    body.innerHTML = renderAnswer(result.answer);
    const sources = $("#ask-sources");
    const seen = new Set();
    for (const source of result.sources || []) {
      if (!source.meeting_id || seen.has(source.meeting_id)) continue;
      seen.add(source.meeting_id);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "source";
      button.innerHTML = `<span>${source.tag ? `<strong>${escapeHtml(source.tag)}</strong> ` : ""}${escapeHtml(source.meeting_title)}</span><span>${formatDay(source.meeting_date)}</span>`;
      button.addEventListener("click", () => backend.open(`/meetings/${source.meeting_id}`));
      sources.append(button);
    }
  } catch (error) {
    body.className = "answer__body";
    body.textContent = error.message;
  } finally {
    $("#ask-btn").disabled = false;
  }
}

// ---------------------------------------------------------------- Meetings

async function loadMeetings(query = "") {
  meetingsLoaded = true;
  let meetings;
  try {
    meetings = await backend.request(`/api/meetings${query ? `?q=${encodeURIComponent(query)}` : ""}`);
  } catch (error) {
    empty(listNode("meetings-list"), "Meetings couldn't load", error.message);
    return;
  }
  if (!meetings.length) {
    empty(listNode("meetings-list"), query ? "No meetings match" : "No meetings yet", query ? "Try different words." : "Send the notetaker into your next Google Meet.");
    return;
  }
  const list = listNode("meetings-list");
  list.replaceChildren();
  for (const meeting of meetings.slice(0, 30)) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "item";
    const counts = meeting.task_count || meeting.decision_count
      ? `${meeting.task_count} task${meeting.task_count === 1 ? "" : "s"}, ${meeting.decision_count} decision${meeting.decision_count === 1 ? "" : "s"}`
      : "No action items";
    row.innerHTML = `<span class="item__main"><span class="item__title">${escapeHtml(meeting.title)}</span><span class="item__meta">${escapeHtml(counts)}</span></span><span class="item__side">${formatDay(meeting.date)}</span>`;
    row.addEventListener("click", () => backend.open(`/meetings/${meeting.id}`));
    list.append(row);
  }
}

// ---------------------------------------------------------------- settings

async function openSettings() {
  const settings = await backend.settings();
  $("#auto-invite").checked = settings.autoInvite;
  $("#notify-ready").checked = settings.notifyReady;
  $("#sheets-export").checked = settings.sheetsExport;
  $("#settings-sheet").hidden = false;
}

// ---------------------------------------------------------------- wiring

$("#google-login-btn").addEventListener("click", async () => {
  setStatus($("#login-status"), "Opening Google…");
  const response = await backend.message("login");
  if (response.ok) void boot();
  else setStatus($("#login-status"), response.error || "Google sign-in failed.", "error");
});

$("#email-login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#email-login-btn").disabled = true;
  setStatus($("#login-status"), "Signing in…");
  const response = await backend.message("login-with-password", { email: $("#login-email").value.trim(), password: $("#login-password").value });
  $("#email-login-btn").disabled = false;
  if (response.ok) void boot();
  else setStatus($("#login-status"), response.error || "Sign-in failed.", "error");
});

$("#create-account-btn").addEventListener("click", () => backend.open("/login"));
// Resets a password — or, for an account made with Google, sets a first one
// (the emailed link proves the inbox either way).
$("#forgot-password-btn").addEventListener("click", () => {
  const email = $("#login-email").value.trim();
  backend.open(`/forgot-password${email ? `?email=${encodeURIComponent(email)}` : ""}`);
});
$("#open-workspace-btn").addEventListener("click", () => backend.open("/dashboard"));
$("#all-tasks-btn").addEventListener("click", () => backend.open("/tasks?owner=me"));
$("#ask-continue-btn").addEventListener("click", () => backend.open(`/memory?q=${encodeURIComponent(lastQuestion)}`));
$("#sheets-settings-btn").addEventListener("click", (event) => {
  event.preventDefault();
  backend.open("/settings");
});
for (const tab of document.querySelectorAll(".tab")) tab.addEventListener("click", () => selectTab(tab.dataset.tab));
$("#send-form").addEventListener("submit", sendNotetaker);
$("#ask-form").addEventListener("submit", (event) => {
  event.preventDefault();
  void ask($("#ask-input").value);
});
$("#ask-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void ask($("#ask-input").value);
  }
});
for (const chip of document.querySelectorAll(".chip")) {
  chip.addEventListener("click", () => {
    $("#ask-input").value = chip.textContent;
    void ask(chip.textContent);
  });
}
let searchTimer;
$("#meeting-search").addEventListener("input", (event) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => void loadMeetings(event.target.value.trim()), 280);
});
$("#settings-btn").addEventListener("click", () => void openSettings());
$("#settings-close-btn").addEventListener("click", () => ($("#settings-sheet").hidden = true));
for (const [id, key] of [["#auto-invite", "autoInvite"], ["#notify-ready", "notifyReady"], ["#sheets-export", "sheetsExport"]]) {
  $(id).addEventListener("change", async (event) => {
    await backend.saveSetting(key, event.target.checked);
    toast("Saved.");
  });
}
$("#logout-btn").addEventListener("click", async () => {
  await backend.message("logout");
  $("#settings-sheet").hidden = true;
  void boot();
});

void boot();

// ---------------------------------------------------------------- preview fixtures

function previewBackend() {
  const params = new URLSearchParams(location.search);
  const loggedIn = params.get("preview") !== "login";
  const day = (offset, hour = 10) => {
    const date = new Date(Date.now() - offset * 864e5);
    date.setHours(hour, 0, 0, 0);
    return date.toISOString();
  };
  const previewCaptures = [
    { id: "c1", meeting_code: "abc-defg-hij", title: "Design partner call", status: "capturing", status_label: "Recording", active: true, stop_requested: false, updated_at: day(0) },
    { id: "c2", meeting_code: "xyz-wxyz-xyz", title: "Hiring sync", status: "waiting_for_admission", status_label: "Waiting to be admitted", active: true, stop_requested: false, updated_at: day(0) },
  ];
  const fixtures = {
    "/api/tasks": [
      { id: "t1", description: "Send Nimbus the CSV export of SIP AUM by fund", owner: "Archit", status: "pending", due_date: day(1), meeting_title: "Client onboarding: Nimbus" },
      { id: "t2", description: "Review attendee sharing edge cases with legal", owner: "Archit", status: "pending", due_date: day(-2), meeting_title: "Weekly product sync" },
      { id: "t3", description: "Draft the Q4 roadmap one-pager", owner: "archit@example.com", status: "in_progress", deadline: "Friday", meeting_title: "Q4 roadmap planning" },
    ],
    "/api/meetings": [
      { id: "m1", title: "Weekly product sync", date: day(0, 11), task_count: 4, decision_count: 2 },
      { id: "m2", title: "Client onboarding: Nimbus Capital", date: day(0, 15), task_count: 3, decision_count: 1 },
      { id: "m3", title: "Infra cost review", date: day(3), task_count: 0, decision_count: 0 },
    ],
    "/api/chat": { answer: "You decided to **stay on the Neon free tier until 50 seats** because usage is far below the limits [M1]. This reversed the earlier plan to move to a paid tier in October.\n\n- Ravi owns the migration plan [M2]\n- Revisit at 40 seats", sources: [{ meeting_id: "m3", meeting_title: "Infra cost review", meeting_date: day(3), tag: "M1" }, { meeting_id: "m1", meeting_title: "Weekly product sync", meeting_date: day(0), tag: "M2" }] },
  };
  return {
    session: async () => (loggedIn ? { charchaApiToken: "preview", userEmail: "archit@example.com", userName: "Archit Jain" } : null),
    request: async (path) => fixtures[path.split("?")[0]] ?? [],
    message: async (type) =>
      type === "list-captures"
        ? { ok: true, captures: previewCaptures }
        : type === "meet-status"
          ? { ok: true, capture: params.get("tab") === "meet-colleague" ? { ...previewCaptures[0], subscribed: false, requested_by: "Asha" } : previewCaptures[0] }
          : { ok: true },
    settings: async () => ({ autoInvite: false, notifyReady: true, sheetsExport: true }),
    saveSetting: async () => {},
    activeTabUrl: async () => (params.get("tab")?.startsWith("meet") ? "https://meet.google.com/abc-defg-hij" : ""),
    open: (path) => console.log("open", path),
  };
}
