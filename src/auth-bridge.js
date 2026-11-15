// Runs on the Wilco dashboard page. Content scripts execute in an isolated
// JS world but share the page's actual localStorage (it's storage-layer, not
// JS-heap), so we can read/write the dashboard's session directly here and
// mirror it against the extension's own session via the background worker —
// giving a single shared login between the extension and the web dashboard.
const TOKEN_KEY = "charchaToken";

function getPageToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function setPageToken(token) {
  if (token) {
    if (localStorage.getItem(TOKEN_KEY) === token) return;
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    if (localStorage.getItem(TOKEN_KEY) === null) return;
    localStorage.removeItem(TOKEN_KEY);
  }
  // The React app only reads localStorage on mount — force it to pick up
  // the session (or lack of one) we just applied on its behalf.
  location.reload();
}

// Extension -> webpage: if the extension already has a session and this
// page doesn't (or vice versa), reconcile once on load before the app
// decides whether to show the login screen.
chrome.runtime.sendMessage({ type: "get-extension-token", pageOrigin: location.origin }, (response) => {
  if (chrome.runtime.lastError || !response?.ok) return;
  if (response.environmentMismatch) {
    if (getPageToken()) syncFromPage();
    return;
  }
  if (response.token !== getPageToken()) setPageToken(response.token);
});

// Webpage -> extension: whenever this page's session changes (including
// same-tab login/logout, via the postMessage the app sends), mirror it into
// the extension's storage.
function syncFromPage() {
  chrome.runtime.sendMessage(
    { type: "sync-token-from-webpage", token: getPageToken(), pageOrigin: location.origin },
    () => void chrome.runtime.lastError
  );
}

window.addEventListener("message", (event) => {
  if (event.source !== window || event.origin !== location.origin) return;
  if (event.data?.source === "charcha-webapp" && event.data?.type === "auth-changed") {
    syncFromPage();
  }
});

// Cross-tab: another tab of the dashboard logging in/out fires "storage" here.
window.addEventListener("storage", (event) => {
  if (event.key === TOKEN_KEY) syncFromPage();
});

// Extension -> webpage, for a tab that's already open when the extension
// itself logs in/out (e.g. via the popup) — see background.js's
// chrome.storage.onChanged listener, which is the only other trigger point.
chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "extension-token-changed") {
    setPageToken(message.token);
  }
});
