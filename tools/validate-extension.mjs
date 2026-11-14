import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { BACKEND_URL, DASHBOARD_URL, DASHBOARD_URL_PATTERNS, backendUrlForDashboardOrigin } from "../src/config.js";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (path) => readFileSync(resolve(root, path), "utf8");
const manifest = JSON.parse(read("manifest.json"));
const pkg = JSON.parse(read("package.json"));
const popupHtml = read("src/popup.html");
const popupJs = read("src/popup.js");
const backgroundJs = read("src/background.js");
const contentJs = read("src/content.js");
const apiJs = read("src/api.js");

// --- Manifest -----------------------------------------------------------------
for (const path of [
  manifest.action.default_popup,
  manifest.background.service_worker,
  ...manifest.content_scripts.flatMap((entry) => entry.js),
  ...Object.values(manifest.action.default_icon),
]) {
  assert(existsSync(resolve(root, path)), `Manifest target is missing: ${path}`);
}

for (const permission of ["storage", "identity", "notifications", "alarms", "contextMenus", "tabs"]) {
  assert(manifest.permissions.includes(permission), `Required permission missing: ${permission}`);
}
// The notetaker bot records meetings now. The extension must not ask for
// capture permissions it no longer uses — Chrome shows them at install time.
for (const permission of ["tabCapture", "offscreen", "unlimitedStorage", "scripting"]) {
  assert(!manifest.permissions.includes(permission), `Unused permission must be removed: ${permission}`);
}
for (const origin of ["https://meet.google.com/*", "http://localhost:8080/*", "https://charcha.example.com/*", "https://sheets.googleapis.com/*"]) {
  assert(manifest.host_permissions.includes(origin), `Required host permission missing: ${origin}`);
}
assert(manifest.oauth2.scopes.includes("https://www.googleapis.com/auth/spreadsheets"), "Sheets export needs the spreadsheets scope");
assert.equal(manifest.omnibox?.keyword, "mem", "Address-bar keyword is missing");
assert.equal(manifest.version, pkg.version, "manifest.json and package.json versions must match");
assert(manifest.content_scripts.some((entry) => entry.matches?.includes("https://charcha.example.com/*")), "Auth bridge must run on the hosted dashboard");

for (const removed of ["src/offscreen.html", "src/offscreen.js", "src/storage.js"]) {
  assert(!existsSync(resolve(root, removed)), `Recording code should be gone: ${removed}`);
}
assert(!/tabCapture|getUserMedia|MediaRecorder|offscreen/.test(backgroundJs + contentJs + popupJs), "No audio capture code may remain");

// --- Environments -------------------------------------------------------------
assert.equal(backendUrlForDashboardOrigin("http://localhost:3000"), null);
assert.equal(backendUrlForDashboardOrigin("http://localhost:3001"), "http://localhost:8080");
assert.equal(backendUrlForDashboardOrigin("https://charcha.example.com"), null);
assert.equal(BACKEND_URL, "http://localhost:8080");
assert.equal(DASHBOARD_URL, "http://localhost:3001");
assert(DASHBOARD_URL_PATTERNS.includes("http://localhost:3001/*"));
assert(DASHBOARD_URL_PATTERNS.includes("https://charcha.example.com/*"));

// --- Popup --------------------------------------------------------------------
const htmlIds = [...popupHtml.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
assert.equal(new Set(htmlIds).size, htmlIds.length, "Popup contains duplicate element IDs");
for (const [, id] of popupJs.matchAll(/\$\("#([A-Za-z][\w-]*)"\)/g)) {
  assert(htmlIds.includes(id), `popup.js references missing element #${id}`);
}
for (const tab of ["now", "tasks", "ask", "meetings"]) {
  assert(popupHtml.includes(`data-tab="${tab}"`) && popupHtml.includes(`data-panel="${tab}"`), `Popup tab missing: ${tab}`);
}
assert(popupHtml.includes('id="email-login-form"'), "Email/password login form is missing");
assert(popupHtml.includes('id="send-consent"'), "Sending the notetaker from the popup must ask for recording consent");

// --- Messaging contract -------------------------------------------------------
const sentTypes = new Set(
  [...(popupJs + contentJs).matchAll(/(?:message|send)\("([a-z-]+)"/g)].map((match) => match[1]),
);
for (const type of sentTypes) {
  assert(backgroundJs.includes(`"${type}"`) || backgroundJs.includes(`${type}(`), `No background handler for "${type}"`);
}
for (const type of ["login", "login-with-password", "logout", "meet-status", "meet-joined", "invite-notetaker", "stop-notetaker", "list-captures", "get-extension-token", "sync-token-from-webpage"]) {
  assert(new RegExp(`(^|\\s)"?${type}"?\\(message\\)|async "?${type}"?\\(`, "m").test(backgroundJs), `Background handler missing: ${type}`);
}

// --- Behaviour invariants -----------------------------------------------------
assert(backgroundJs.includes("consent_acknowledged: true"), "Capture requests must carry the consent acknowledgement");
assert(backgroundJs.includes("autoInvited:"), "Auto-invite must be limited to once per room per day");
assert(backgroundJs.includes("exportedMeetings"), "Sheets export must not append the same meeting twice");
assert(backgroundJs.includes("firstRun"), "Signing in must not replay old notetaker notifications");
assert(contentJs.includes("setInterval(() =>"), "Meet SPA URL watcher is missing");
assert(contentJs.includes("attachShadow"), "In-Meet control must be isolated from Meet's styles");
assert(apiJs.includes("clearSession()"), "A 401 must sign the extension out");
assert(!existsSync(resolve(root, "dist/extension-key.pem")), "Private extension key must never be included in dist/");

console.log("Extension checks passed.");
