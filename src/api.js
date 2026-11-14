// Shared by the background worker and the popup. Content scripts can't call
// the backend directly (they're bound by the Meet page's CORS), so they go
// through background.js messages instead.
import { BACKEND_URL, DASHBOARD_URL } from "./config.js";

export const SESSION_KEYS = ["charchaApiToken", "userEmail", "userName", "userPicture", "userSub", "loggedIn"];

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export async function getSession() {
  const stored = await chrome.storage.sync.get({ charchaApiToken: "", userEmail: "", userName: "", userPicture: "" });
  return stored.charchaApiToken ? stored : null;
}

export async function clearSession() {
  await chrome.storage.sync.remove([...SESSION_KEYS, "charchaBackendUrl", "charchaDashboardUrl"]);
}

export function workspaceUrl(path = "/dashboard") {
  return `${DASHBOARD_URL}${path}`;
}

export async function api(path, { method = "GET", body, token } = {}) {
  const session = token ? { charchaApiToken: token } : await getSession();
  if (!session) throw new ApiError(401, "Sign in to Charcha first.");
  let response;
  try {
    response = await fetch(`${BACKEND_URL}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${session.charchaApiToken}`,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Charcha can't be reached. Check your connection.");
  }
  if (response.status === 401 && !token) {
    // The session expired or was revoked; signing out here keeps every
    // surface (popup, Meet button, dashboard tabs) from showing stale data.
    await clearSession();
    throw new ApiError(401, "Your Charcha session expired. Sign in again.");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = typeof data.detail === "string" ? data.detail : `Charcha returned ${response.status}`;
    throw new ApiError(response.status, detail);
  }
  return response.json();
}

export function randomKey() {
  return crypto.randomUUID().replace(/-/g, "");
}

/** "abc-defg-hij" from a Meet URL, or null when the URL isn't a meeting room. */
export function meetCodeFromUrl(url) {
  const match = /^https:\/\/meet\.google\.com\/(?:meet\/)?([a-z]{3}-[a-z]{4}-[a-z]{3})(?:[/?#]|$)/i.exec(url || "");
  return match ? match[1].toLowerCase() : null;
}

/** Loose on purpose: the server checks the many Teams link forms. */
export function isTeamsLink(url) {
  return /^https:\/\/([\w-]+\.)*(teams\.microsoft\.com|teams\.live\.com|teams\.cloud\.microsoft|safelinks\.protection\.outlook\.com)\//i.test(url || "");
}

/** Notetaker requests that are on their way in, recording, or processing. */
export function isLive(request) {
  return Boolean(request.active || request.status === "stopped");
}

/** Mirrors the web app's rule: transcript owners are free text, so a first
 * name, full name, email or email handle all count as "mine". */
export function isMine(task, user) {
  if (!task.owner || !user?.userEmail) return false;
  const owner = task.owner.trim().toLowerCase();
  const email = user.userEmail.toLowerCase();
  const candidates = new Set([email, email.split("@")[0]]);
  if (user.userName) {
    const name = user.userName.trim().toLowerCase();
    candidates.add(name);
    candidates.add(name.split(/\s+/)[0]);
  }
  return candidates.has(owner);
}
