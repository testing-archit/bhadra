# Wilco web app

The Wilco workspace for software teams: Home, meetings, tasks, Delivery Radar, decisions, projects, memory, Live, recording, and admin. Built with Next.js 16, React 19, TypeScript, and Tailwind CSS. The current Signal Room contract is in [`../DESIGN.md`](../DESIGN.md). Shared tokens live in `src/app/globals.css`; route-family palettes live in scoped CSS files under `src/app/`.

## Run it

```bash
echo "NEXT_PUBLIC_BACKEND_URL=http://localhost:8080" > .env.local
npm ci
npm run dev                  # http://localhost:3000
```

Run `npm run typecheck` before you commit. `npm run lint` is currently broken upstream because typescript-eslint doesn't support TypeScript 7 yet.

## Environment

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_BACKEND_URL` | Backend origin, e.g. `http://localhost:8080` |
| `NEXT_PUBLIC_APP_URL` | This app's public origin, used for links in shares and emails |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | Web OAuth client for "Sign in with Google" (optional: email and password work without it) |
| `NEXT_PUBLIC_CHROME_WEB_STORE_URL` | Once the extension is listed, `/extension` sends people to the Store instead of the ZIP |

## Where things live

| Path | What it is |
|---|---|
| `src/app/(app)/dashboard` | Home: what needs you today, recent meetings, calendar agenda |
| `src/app/(app)/meetings` | Meeting list, detail, setup, prep, and live meeting board with native FigJam actions |
| `src/app/(app)/live` | Wilco Live, the hands-free spoken conversation (`components/live-session.tsx`, `talking-mascot.tsx`) |
| `src/app/(app)/tasks` | Tasks as a board or list, with task cards and focus mode |
| `src/app/(app)/delivery` | Delivery Radar: open follow-ups, attention items, decisions, and project activity from accessible meetings |
| `src/app/(app)/decisions`, `projects` | Decision history and project workspaces |
| `src/app/(app)/memory` | Ask your meetings, with citations, by text or voice |
| `src/app/(app)/gnani` | Voice lab: live speech and voice demos, with advanced model controls |
| `src/app/(app)/record` | In-person recorder (5-minute segments kept in IndexedDB) |
| `src/components/brand.tsx` | Wilco logo, wordmark and voice disc |
| `src/components/shell/` | Visible sidebar destinations, mobile navigation, top-bar search, and the ⌘K command palette |
| `src/lib/api.ts` | Typed client for the backend API |
| `public/` | Wilco favicon and icons, plus the extension and FigJam plugin downloads in `public/downloads/` |

Some storage keys and event names still start with `charcha` (the product's earlier name), for example `charchaToken` and `charcha-theme`. Leave them as they are: renaming them would sign everyone out and reset saved settings.

The sidebar renders its destinations as direct links. `/khata` redirects to `/delivery` for old bookmarks; the legacy khata backend API remains available to existing integrations. The UI uses scoped CSS graphics and short animations with `prefers-reduced-motion` fallbacks.
