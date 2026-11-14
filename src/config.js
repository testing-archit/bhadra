const buildEnv = import.meta.env || {};
const production = buildEnv.PROD && buildEnv.VITE_DEPLOY_TARGET === "production";

export const BACKEND_URL = production
  ? "https://charcha.example.com"
  : "http://localhost:8080";
export const DASHBOARD_URL = production
  ? "https://charcha.example.com"
  : "http://localhost:3001";

export const DASHBOARD_URL_PATTERNS = [
  "http://localhost:3001/*",
  "https://charcha.example.com/*",
];

export function backendUrlForDashboardOrigin(origin) {
  return origin === DASHBOARD_URL ? BACKEND_URL : null;
}
