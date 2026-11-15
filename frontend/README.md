# Wilco web app

The Wilco workspace: Home, meetings, tasks, memory, Wilco Live, the in-person recorder and admin. Built with Next.js 16, React 19, TypeScript and Tailwind CSS. The design system is in [`../DESIGN.md`](../DESIGN.md), and its tokens are in `src/app/globals.css`. Components use those tokens and never raw hex colours.

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
| `src/app/(app)/meetings` | Meeting list, meeting pages, and the live meeting page (`meetings/live/[captureId]`, which includes FigJam pairing) |
| `src/app/(app)/live` | Wilco Live, the hands-free spoken conversation (`components/live-session.tsx`, `talking-mascot.tsx`) |
| `src/app/(app)/tasks` | Tasks as a board or list, with task cards and focus mode |
| `src/app/(app)/memory` | Ask your meetings, with citations, by text or voice |
| `src/app/(app)/record` | In-person recorder (5-minute segments kept in IndexedDB) |
| `src/components/brand.tsx` | Wilco logo, wordmark and voice disc |
| `src/components/shell/` | Sidebar, mobile navigation and the ⌘K command palette |
| `src/lib/api.ts` | Typed client for the backend API |
| `public/` | Wilco favicon and icons, plus the extension and FigJam plugin downloads in `public/downloads/` |

Some storage keys and event names still start with `charcha` (the product's earlier name), for example `charchaToken` and `charcha-theme`. Leave them as they are: renaming them would sign everyone out and reset saved settings.
