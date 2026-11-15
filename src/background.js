// Wilco's extension no longer records audio itself: a notetaker bot joins the
// Meet and the backend does transcription and notes. This worker keeps the
// session in sync with the dashboard, sends/stops the notetaker, watches its
// progress (badge + notifications), and exports finished notes to Google Sheets.
import { BACKEND_URL, DASHBOARD_URL, DASHBOARD_URL_PATTERNS, backendUrlForDashboardOrigin } from "./config.js";
import { ApiError, api, clearSession, getSession, isLive, meetCodeFromUrl, randomKey, workspaceUrl } from "./api.js";
import { MEETING_COLUMNS, TASK_COLUMNS, formatRequests, hasHeader, headerRow, meetingRow, taskRows } from "./sheets.js";

const POLL_ALARM = "poll-notetakers";
const CAPTURE_CACHE_MS = 4_000;
const DEFAULT_SETTINGS = { autoInvite: false, notifyReady: true, sheetsExport: true };

// ---------------------------------------------------------------- lifecycle

async function init() {
  await chrome.storage.sync.set({ charchaBackendUrl: BACKEND_URL, charchaDashboardUrl: DASHBOARD_URL });
  // Older builds kept audio queues and per-meeting state here; none of it is used any more.
  await chrome.storage.local.remove(["meetingHistory", "pendingCaptures", "activeMeetings"]);
  chrome.alarms.create(POLL_ALARM, { periodInMinutes: 1 });
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: "ask-charcha", title: "Ask Wilco about “%s”", contexts: ["selection"] });
  });
  chrome.omnibox.setDefaultSuggestion({ description: "Ask Wilco: <match>%s</match>" });
  void pollCaptures();
}

chrome.runtime.onInstalled.addListener(() => void init());
chrome.runtime.onStartup.addListener(() => void init());

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === POLL_ALARM) void pollCaptures();
});

async function getSettings() {
  return chrome.storage.sync.get(DEFAULT_SETTINGS);
}

function openTab(url) {
  return chrome.tabs.create({ url });
}

// ---------------------------------------------------------------- auth

function getGoogleAuthToken(interactive) {
  return new Promise((resolve, reject) => {
    chrome.identity.getAuthToken({ interactive }, (token) => {
      if (chrome.runtime.lastError || !token) reject(new Error(chrome.runtime.lastError?.message || "Google sign-in failed"));
      else resolve(typeof token === "string" ? token : token.token);
    });
  });
}

async function loginWithGoogle() {
  const googleToken = await getGoogleAuthToken(true);
  const response = await fetch(`${BACKEND_URL}/api/auth/google`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ google_access_token: googleToken }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Wilco couldn't sign you in with Google.");
  await storeSession(data.token);
}

async function loginWithPassword(email, password) {
  const response = await fetch(`${BACKEND_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Email sign-in failed.");
  await storeSession(data.token);
}

async function storeSession(token) {
  const me = await api("/api/auth/me", { token });
  await chrome.storage.sync.set({
    charchaApiToken: token,
    userEmail: me.email,
    userName: me.name || me.email.split("@")[0],
    loggedIn: true,
    charchaBackendUrl: BACKEND_URL,
    charchaDashboardUrl: DASHBOARD_URL,
  });
  await chrome.storage.local.remove(["captureStatuses"]);
  void pollCaptures();
}

// Keep already-open dashboard tabs in step with extension sign-in/out.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "sync" && changes.charchaApiToken) {
    void broadcastTokenToDashboardTabs(changes.charchaApiToken.newValue || null);
    if (!changes.charchaApiToken.newValue) void setBadge([]);
  }
});

async function broadcastTokenToDashboardTabs(token) {
  const tabs = await chrome.tabs.query({ url: DASHBOARD_URL_PATTERNS });
  for (const tab of tabs) {
    if (!tab.url || new URL(tab.url).origin !== DASHBOARD_URL) continue;
    chrome.tabs.sendMessage(tab.id, { type: "extension-token-changed", token }).catch(() => {});
  }
}

// ---------------------------------------------------------------- notetaker

let captureCache = { at: 0, items: [] };

async function listCaptures({ fresh = false } = {}) {
  if (!fresh && Date.now() - captureCache.at < CAPTURE_CACHE_MS) return captureCache.items;
  const items = await api("/api/capture/requests");
  captureCache = { at: Date.now(), items };
  return items;
}

/** The request that matters for one Meet room: the live one, or else the
 * newest from the last 12 hours (so "Notes ready" stays visible after the call). */
function captureForCode(items, code) {
  const forCode = items.filter((item) => item.meeting_code === code);
  const live = forCode.find(isLive);
  if (live) return live;
  const recent = forCode
    .filter((item) => item.updated_at && Date.now() - new Date(item.updated_at).getTime() < 12 * 3_600_000)
    .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
  return recent[0] || null;
}

async function inviteNotetaker(url, title) {
  const created = await api("/api/capture/requests", {
    method: "POST",
    body: {
      meeting_url: url,
      title: (title || "").slice(0, 200),
      template: "general",
      consent_acknowledged: true,
      idempotency_key: randomKey(),
    },
  });
  await rememberStatus(created);
  captureCache.at = 0;
  void pollCaptures();
  return created;
}

async function stopNotetaker(id) {
  const updated = await api(`/api/capture/requests/${id}/stop`, { method: "POST" });
  captureCache.at = 0;
  void pollCaptures();
  return updated;
}

async function rememberStatus(request) {
  const { captureStatuses = {} } = await chrome.storage.local.get("captureStatuses");
  captureStatuses[request.id] = request.status;
  await chrome.storage.local.set({ captureStatuses });
}

// MV3 workers can be woken by an alarm and a message at once; one poll at a time.
let polling = null;
function pollCaptures() {
  polling ||= runPoll().finally(() => {
    polling = null;
  });
  return polling;
}

async function runPoll() {
  if (!(await getSession())) return;
  let items;
  try {
    items = await listCaptures({ fresh: true });
  } catch (error) {
    if (error instanceof ApiError && error.status === 503) return; // notetaker not configured on this server
    if (error instanceof ApiError && (error.status === 0 || error.status >= 500)) {
      // Don't leave a stale "REC" up while Wilco can't be reached.
      await chrome.action.setBadgeBackgroundColor({ color: "#6b7280" });
      await chrome.action.setBadgeText({ text: "!" });
      await chrome.action.setTitle({ title: "Wilco can't be reached right now. Retrying every minute." });
    }
    return;
  }
  await setBadge(items);

  const { captureStatuses } = await chrome.storage.local.get("captureStatuses");
  const firstRun = !captureStatuses;
  const next = {};
  const settings = await getSettings();

  for (const request of items) {
    next[request.id] = request.status;
    const previous = captureStatuses?.[request.id];
    if (firstRun || previous === request.status) continue;
    // A request we've never seen before only notifies once it's recent —
    // otherwise signing in would replay a week of history.
    const recent = request.updated_at && Date.now() - new Date(request.updated_at).getTime() < 15 * 60_000;
    if (!previous && !recent) continue;
    const name = request.title || request.meeting_code;

    if (request.status === "capturing") {
      notify(`capture-${request.id}`, "Wilco is taking notes", `The notetaker is recording “${name}”.`, null);
    } else if (request.status === "waiting_for_admission") {
      notify(`admit-${request.id}`, "Admit the Wilco notetaker", `It's waiting in the lobby of “${name}”. Let it in from the call.`, request.meeting_url);
    } else if (request.status === "completed" && request.meeting_id) {
      if (settings.notifyReady) {
        notify(`ready-${request.id}`, "Meeting notes are ready", `“${name}”: transcript, summary and tasks are in Wilco.`, workspaceUrl(`/meetings/${request.meeting_id}`));
      }
      if (settings.sheetsExport) void exportToSheets(request.meeting_id);
    } else if (["denied", "timed_out", "failed"].includes(request.status)) {
      notify(`problem-${request.id}`, "The notetaker couldn't record", `“${name}”: ${request.status_label}${request.status_detail ? `. ${request.status_detail}` : ""}`, workspaceUrl("/meetings"));
    }
  }
  await chrome.storage.local.set({ captureStatuses: next });
}

async function setBadge(items) {
  const recording = items.some((item) => item.status === "capturing");
  const pending = items.filter(isLive).length;
  if (recording) {
    await chrome.action.setBadgeBackgroundColor({ color: "#dc2626" });
    await chrome.action.setBadgeText({ text: "REC" });
    await chrome.action.setTitle({ title: "Wilco: the notetaker is recording" });
  } else if (pending) {
    await chrome.action.setBadgeBackgroundColor({ color: "#b7791f" });
    await chrome.action.setBadgeText({ text: String(pending) });
    await chrome.action.setTitle({ title: "Wilco: notetaker on its way in or processing" });
  } else {
    await chrome.action.setBadgeText({ text: "" });
    await chrome.action.setTitle({ title: "Wilco" });
  }
}

// ---------------------------------------------------------------- notifications

async function notify(id, title, message, link) {
  if (link) {
    const { notificationLinks = {} } = await chrome.storage.session.get("notificationLinks");
    notificationLinks[id] = link;
    await chrome.storage.session.set({ notificationLinks });
  }
  chrome.notifications.create(id, { type: "basic", iconUrl: chrome.runtime.getURL("icons/icon128.png"), title, message, priority: 1 });
}

chrome.notifications.onClicked.addListener(async (id) => {
  const { notificationLinks = {} } = await chrome.storage.session.get("notificationLinks");
  if (notificationLinks[id]) void openTab(notificationLinks[id]);
  chrome.notifications.clear(id);
});

// ---------------------------------------------------------------- Google Sheets export

/** Appends a finished meeting to the spreadsheet set in Wilco settings: one
 * row per task on the tasks tab, one row for the meeting on the notes tab,
 * both formatted tables (src/sheets.js). Runs here because Google Sheets
 * access belongs to the person's browser sign-in. */
async function exportToSheets(meetingId) {
  try {
    const { exportedMeetings = [] } = await chrome.storage.local.get("exportedMeetings");
    if (exportedMeetings.includes(meetingId)) return;
    const settings = await api("/api/auth/integrations/google-sheets");
    if (!settings.spreadsheet_id) return;
    const meeting = await api(`/api/meetings/${meetingId}`);
    const jira = await api("/api/jira/status").catch(() => null);
    const token = await getGoogleAuthToken(false);
    const tasksTab = settings.tasks_tab || "Tasks";
    const notesTab = settings.notes_tab || "Meeting Notes";
    const context = { appUrl: workspaceUrl("").replace(/\/$/, ""), jiraSiteUrl: jira?.site_url || null };
    await prepareTab(settings.spreadsheet_id, tasksTab, TASK_COLUMNS, token);
    await prepareTab(settings.spreadsheet_id, notesTab, MEETING_COLUMNS, token);
    const rows = taskRows(meeting, context);
    if (rows.length) await appendRows(settings.spreadsheet_id, tasksTab, rows, token);
    await appendRows(settings.spreadsheet_id, notesTab, [meetingRow(meeting, context)], token);
    await chrome.storage.local.set({ exportedMeetings: [meetingId, ...exportedMeetings].slice(0, 200) });
  } catch (error) {
    console.warn("Google Sheets export skipped:", error?.message || error);
  }
}

function a1(tab, range) {
  return encodeURIComponent(`'${tab.replace(/'/g, "''")}'!${range}`);
}

async function sheetsFetch(spreadsheetId, path, token, init = {}) {
  const response = await fetch(`https://sheets.googleapis.com/v4/spreadsheets/${encodeURIComponent(spreadsheetId)}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(init.headers || {}) },
  });
  if (!response.ok) throw new Error(`Google Sheets ${init.method || "GET"} ${path.split("?")[0]} failed (${response.status})`);
  return response.json();
}

/** Makes `tab` a formatted table with this layout's header. A tab of the
 * old, header-less export is kept under "<tab> (old format)" and a fresh
 * one takes its name, so earlier rows aren't mixed with new columns. */
async function prepareTab(spreadsheetId, tab, columns, token) {
  const info = await sheetsFetch(spreadsheetId, "?fields=sheets.properties(sheetId,title)", token);
  const sheets = (info.sheets || []).map((sheet) => sheet.properties);
  const existing = sheets.find((sheet) => sheet.title === tab);
  if (existing) {
    const top = await sheetsFetch(spreadsheetId, `/values/${a1(tab, "A1:Z2")}`, token);
    const rows = top.values || [];
    if (hasHeader(rows[0], columns)) return;
    if (rows.length) {
      const taken = new Set(sheets.map((sheet) => sheet.title));
      let archived = `${tab} (old format)`;
      for (let n = 2; taken.has(archived); n += 1) archived = `${tab} (old format ${n})`;
      await sheetsFetch(spreadsheetId, ":batchUpdate", token, {
        method: "POST",
        body: JSON.stringify({ requests: [{ updateSheetProperties: { properties: { sheetId: existing.sheetId, title: archived }, fields: "title" } }] }),
      });
    } else {
      await writeHeader(spreadsheetId, tab, existing.sheetId, columns, token);
      return;
    }
  }
  const created = await sheetsFetch(spreadsheetId, ":batchUpdate", token, {
    method: "POST",
    body: JSON.stringify({ requests: [{ addSheet: { properties: { title: tab } } }] }),
  });
  await writeHeader(spreadsheetId, tab, created.replies[0].addSheet.properties.sheetId, columns, token);
}

async function writeHeader(spreadsheetId, tab, sheetId, columns, token) {
  await sheetsFetch(spreadsheetId, `/values/${a1(tab, "A1")}?valueInputOption=RAW`, token, {
    method: "PUT",
    body: JSON.stringify({ values: [headerRow(columns)] }),
  });
  await sheetsFetch(spreadsheetId, ":batchUpdate", token, {
    method: "POST",
    body: JSON.stringify({ requests: formatRequests(sheetId, columns) }),
  });
}

async function appendRows(spreadsheetId, tab, rows, token) {
  await sheetsFetch(spreadsheetId, `/values/${a1(tab, "A1")}:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS`, token, {
    method: "POST",
    body: JSON.stringify({ values: rows }),
  });
}

// ---------------------------------------------------------------- auto-invite

/** With auto-invite on, joining a Meet sends the notetaker once per room per
 * day — leaving and rejoining the same call doesn't send a second one. */
async function maybeAutoInvite(url, title) {
  const code = meetCodeFromUrl(url);
  if (!code || !(await getSession())) return null;
  const { autoInvite } = await getSettings();
  if (!autoInvite) return null;
  const day = new Date().toDateString();
  const key = `autoInvited:${code}:${day}`;
  const stored = await chrome.storage.local.get(key);
  if (stored[key]) return null;
  await chrome.storage.local.set({ [key]: true });
  try {
    const items = await listCaptures({ fresh: true });
    if (captureForCode(items, code) && isLive(captureForCode(items, code))) return null;
    return await inviteNotetaker(url, title);
  } catch (error) {
    // Wilco down or unreachable: forget this attempt so the Meet tab can
    // retry, and say so once rather than on every retry.
    const transient = error instanceof ApiError && (error.status === 0 || error.status >= 500);
    const warnedKey = `autoInviteWarned:${code}:${day}`;
    const warned = transient && (await chrome.storage.local.get(warnedKey))[warnedKey];
    if (transient) await chrome.storage.local.remove(key);
    if (!warned) {
      if (transient) await chrome.storage.local.set({ [warnedKey]: true });
      notify(
        `auto-${code}`,
        "Wilco couldn't send the notetaker",
        transient ? `${error.message} It will keep trying while you're in the call.` : error.message,
        null,
      );
    }
    return transient ? { retry: true } : null;
  }
}

// ---------------------------------------------------------------- ask Wilco

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === "ask-charcha" && info.selectionText) {
    void openTab(workspaceUrl(`/memory?q=${encodeURIComponent(info.selectionText.trim().slice(0, 500))}`));
  }
});

chrome.omnibox.onInputChanged.addListener((text, suggest) => {
  const query = text.trim();
  if (!query) return;
  const escaped = query.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  suggest([{ content: `meetings: ${query}`, description: `Search meetings for <match>${escaped}</match>` }]);
});

chrome.omnibox.onInputEntered.addListener((text, disposition) => {
  const query = text.trim();
  const url = query.startsWith("meetings: ")
    ? workspaceUrl(`/meetings?q=${encodeURIComponent(query.slice(10))}`)
    : workspaceUrl(query ? `/memory?q=${encodeURIComponent(query)}` : "/memory");
  if (disposition === "currentTab") chrome.tabs.update({ url });
  else chrome.tabs.create({ url, active: disposition === "newForegroundTab" });
});

// ---------------------------------------------------------------- messages

const handlers = {
  async login() {
    await loginWithGoogle();
    return {};
  },
  async "login-with-password"(message) {
    await loginWithPassword(message.email, message.password);
    return {};
  },
  async logout() {
    await clearSession();
    await chrome.storage.local.remove(["captureStatuses"]);
    return {};
  },

  /** Everything the in-Meet button needs for one room. */
  async "meet-status"(message) {
    const session = await getSession();
    if (!session) return { loggedIn: false };
    const code = meetCodeFromUrl(message.url);
    let capture = null;
    let error = null;
    try {
      // Asks about the meeting itself, so a colleague's notetaker already in
      // this call shows up too (and isn't invited a second time).
      if (code) capture = (await api(`/api/capture/meet/${code}`)).capture;
    } catch (cause) {
      error = cause.message;
    }
    const { autoInvite } = await getSettings();
    return { loggedIn: true, capture, autoInvite, error, dashboardUrl: DASHBOARD_URL };
  },
  async "meet-joined"(message) {
    const result = await maybeAutoInvite(message.url, message.title);
    if (result?.retry) return { capture: null, retry: true };
    return { capture: result };
  },
  async "invite-notetaker"(message) {
    try {
      const capture = await inviteNotetaker(message.url, message.title);
      return { capture, joinedExisting: Boolean(capture.joined_existing) };
    } catch (error) {
      // 409: someone else's notetaker is already in this call.
      if (error instanceof ApiError && error.status === 409) return { alreadyThere: true, error: error.message };
      throw error;
    }
  },
  async "stop-notetaker"(message) {
    const capture = await stopNotetaker(message.id);
    return { capture, keptForOthers: Boolean(capture.kept_for_others) };
  },
  async "list-captures"() {
    return { captures: await listCaptures({ fresh: true }) };
  },
  async "open-workspace"(message) {
    await openTab(workspaceUrl(message.path || "/dashboard"));
    return {};
  },

  // Session bridge with the web dashboard (src/auth-bridge.js).
  async "get-extension-token"(message) {
    const session = await getSession();
    const token = session?.charchaApiToken || null;
    const environmentMismatch = Boolean(token && message.pageOrigin && message.pageOrigin !== DASHBOARD_URL);
    return { token: environmentMismatch ? null : token, environmentMismatch };
  },
  async "sync-token-from-webpage"(message) {
    const current = (await getSession())?.charchaApiToken || null;
    if ((message.token || null) === current) return {};
    if (!message.token) {
      await clearSession();
      return {};
    }
    if (!backendUrlForDashboardOrigin(message.pageOrigin || DASHBOARD_URL)) {
      throw new Error("This page is not a supported Wilco workspace");
    }
    await storeSession(message.token);
    return {};
  },
};

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const handler = handlers[message?.type];
  if (!handler) return false;
  handler(message)
    .then((result) => sendResponse({ ok: true, ...result }))
    .catch((error) => sendResponse({ ok: false, error: error?.message || String(error) }));
  return true;
});
