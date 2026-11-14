import { defineConfig } from "vite";
import { crx } from "@crxjs/vite-plugin";
import manifest from "./manifest.json" with { type: "json" };

// Both development and production use the self-contained dist/ folder.
// Loading the repository root makes Chrome scan unrelated project files
// (including ignored signing keys) and produces misleading extension errors.
// `npm run dev` rebuilds dist/ in watch mode; reload the unpacked extension
// after a rebuild. `npm run build` creates the one-off distributable build.
// Production builds drop the localhost entries (dev backend and web app) from
// every match list, so the released extension asks for no permission it
// doesn't use — the Chrome Web Store review flags that.
function forTarget(source) {
  if (process.env.VITE_DEPLOY_TARGET !== "production") return source;
  const strip = (value) =>
    Array.isArray(value)
      ? value.filter((item) => !(typeof item === "string" && item.startsWith("http://localhost"))).map(strip)
      : value && typeof value === "object"
        ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, strip(item)]))
        : value;
  return strip(source);
}

export default defineConfig({
  plugins: [crx({ manifest: forTarget(manifest) })],
  server: {
    cors: {
      origin: [/chrome-extension:\/\//],
    },
  },
});
