<!-- Team coordination: read docs/coordination.md before edits, commits, pulls, merges, or pushes. -->
<!-- Design skills: see docs/design-skills.md; use .claude/skills/ links and preserve DESIGN.md and existing components. -->

# Charcha — Claude Code project guide
# Claude Code reads this automatically on every session.

---

## 🎯 Current target (read first, 15 Nov 2026)

**The product is now called Wilco** (formerly Charcha; logo in `frontend/public/wilco-*`, extension icons in `icons/`). Use "Wilco" in all user-facing text. Keep lowercase `charcha` identifiers (storage keys, env vars, the Jira `charcha` label, compose project, secrets): renaming them breaks existing sessions, Jira sync and deploys. The bot answers to both "Wilco" and "Charcha".

We are entering **Gnani AI's "Great Indian AI Internship Challenge"** (https://www.gnani.ai/internship). The Scaler hackathon below is maybe-later.
- **Deadline:** 15 Nov 2026, 18:00 IST.
- **Requirement:** a working app built on Gnani models. Charcha uses **Prisma v3** for speech-to-text and **Timbre v2.5** for text-to-speech.
- **Submission:**
  - A public demo video on LinkedIn or X that tags Gnani AI, with `#GreatIndianAIInternshipChallenge #GnaniAI`.
  - The form at https://forms.cloud.microsoft/r/dfFShbp7W7.
- **Judging:** shortlisting is driven by post engagement, then interviews.
- **Data:** synthetic only.

**Live app:** https://34-58-54-115.sslip.io. HTTPS uses Let's Encrypt through certbot; the server-local `nginx/ssl.conf` is git-ignored. Plain-HTTP requests to the IP redirect to HTTPS.

**Docs every session should know:**
- `docs/claude-meetings.md`: Claude Meetings research and Charcha's parity status, per capability.
- `docs/testing-guide.md`: what to test, with questions and expected answers.
- `DESIGN.md`: the design system.

Keep these updated, and commit doc changes with the code: the whole team works through Claude Code.

**Notetaker:**
- It signs in to Google as `gnanihackathon@gmail.com` (`/data/auth.json` in the notetaker container).
- To redo the sign-in, run `backend/bot/generate_auth.py` on a laptop, then `docker compose cp` the file to `notetaker:/data/auth.json`. Never commit it.
- Without it, Meet refuses the bot ("You can't join this video call").

**Gnani models used** (show them at `/gnani`): Prisma v3 (all speech-to-text), Timbre v2.5 + v3 (all speech; `tts_service.language_for_text` picks the language from the script), Timbre voice cloning `vachana-vc-v1` (opt-in own voice, `voice_clone_service.py`, encrypted embedding only; in-call "Wilco, play updates"), Evon v3.3 (optional, `EVON_URL` OpenAI-compatible server, Live falls back to Gemini). Warp has no public API.

**Charcha Live** (`/live`): a Gemini-Live-style spoken conversation built on Gnani.
- **Request:** `POST /api/live/turn` takes one utterance. Prisma transcribes it with Auto-LID, Gemini answers from a cached digest of recent meetings, and Timbre speaks the answer: v2.5 for Hinglish, v3.0 for other Indian languages.
- **Browser:** voice detection and barge-in run in `components/live-session.tsx`.

**Live call features:** say or type "Charcha, …" in Meet. The bot answers from the call's captions and speaks the answer through a virtual microphone (Timbre). "Charcha recap" and "Charcha, add task: …" also work.

**Demo data:** `backend/scripts/seed_demo.py <owner email> <teammate email>` (10 Hinglish meetings). It adds whatever is missing; `--reset` rebuilds everything.

## 🏁 Hackathon context (read first)

**Team:** Bhadra. **Product:** Charcha (चर्चा, "discussion"; the same word in Hindi, Marathi, Bengali and Gujarati).
**Repo:** https://github.com/testing-archit/bhadra (default branch `main`).

**Event:** "India Runs on Voice", a Scaler × Wispr Flow hackathon, https://hackos.scaler.com/wispr/
- Theme: voice-first tools for India, where speaking is the main way in. Builders are expected to work hands-free with Wispr Flow.
- Tracks (pick one): civic services, healthcare, education, small business, everyday access. Any Indian language is allowed, including switching mid-sentence.
- Teams: solo or up to 3 people. The team is **locked after the first submission**.
- Timeline (2026):
  - Round 1, warm-up, online, 5 to 26 Nov: Idea (5 Nov), Prompt (13 Nov), Impact (20 Nov).
  - Registration closes 27 Nov, 11:59 pm IST.
  - Round 2, the build: one shared problem statement is released 27 Nov and the **build is due 29 Nov** (a 2-day window). The shortlist is announced 2 Dec.
  - Round 3: in-person finale on campus, 13 Dec, demoing to Wispr leadership, founders and investors.
- Prizes total ₹30 L: ₹7 L for 1st, ₹5 L for 2nd, ₹3 L for 3rd, and ₹1.25 L each for 4th to 15th. All top 15 teams get Flow Pro, and there is also a Singapore trip and an interview at Wispr.
- Judging criteria and submission rules are published per round when it goes live. Check the site before each round.
- Support: wispr.support@scaler.com, plus the Discord linked from the site.

**Our pitch angle:** Charcha is voice-first meeting memory for Indian teams. You speak in Hindi, English or Hinglish, in a call or in person, and Charcha turns the conversation into owners, tasks, decisions and searchable memory. The in-person recorder (`/record`) is the voice-first entry point. Keep extending the product toward the Round 2 problem statement when it is released.

### Origin and naming rules (IP hygiene)
- This codebase began as an internal meeting-notes project and was fully rebranded for the hackathon. **Never reintroduce the old product or company names**, in code, docs, assets, commit messages or URLs. The team keeps the list of old names to check for outside the repo, and a `git grep` for them must return nothing before every push.
- Git history was restarted with a single fresh commit for the same reason. Do not push or merge the old history.
- Placeholders replace real infrastructure: the domain is `charcha.example.com`, emails are `@example.com`, the notetaker account is `notetaker@example.com`, Jira is `acme.atlassian.net`, and the GCP project is `charcha-hackathon`. Set the real values through env vars (`NEXT_PUBLIC_APP_URL`, `NOTETAKER_EMAIL`, etc.) when deploying.
- The policy assistant (`/policy`) runs on **sample** content in `backend/app/data/company_policies.py` (the "Sample Team Handbook"). It holds no real company data. Replace it with your own, then run `scripts/ingest_policies.py`.
- The org or company name shown in the UI and prompts is "Bhadra".

### Design system (Claude engagement pass)
- `docs/design/redesign-spec.md`, especially section 3b, pins the requested design. `DESIGN.md` documents the built result. Ink frame, stone tray, bright working sheets and one signal-yellow voice/action accent replace the previous night-glow direction.
- Tokens live in `frontend/src/app/globals.css`. Use existing Base UI components, Geist/Mukta, labelled tint chips and Doto only for Home counts. No new raw component colours, gradient text, glass or decorative waveforms.
- Timed debrief strips derive from actual API transcript segments; marks resolve item evidence IDs. No timing means no strip. The software-company demo contains authored synthetic timings and linked evidence, explicitly labelled as sample content.
- Keep Home free of generation on load. Question clicks initiate requests. Done, Undo, confirmations, scope changes and Jira writes retain existing APIs and privacy checks. Never simulate an external write as successful.
- Render desktop/mobile/light/dark and test the interactions before handoff. Reduced motion stops sequences and auto-advance. The supplied external Claude canvas is Cloudflare-blocked here; exact visual comparison remains unverified until it is accessible.
- The extension palette is outside this pass. Preserve colleagues' bot, latency, FigJam and Live-task functionality.

### Dev quickstart
- Frontend: `cd frontend && npm ci && npm run dev`. Then run `npm run typecheck`. ESLint is currently broken upstream because typescript-eslint does not support TS 7.
- Extension: `npm ci && npm run build && npm test` at the repo root. Zip `dist/` into `frontend/public/downloads/charcha-extension-v<version>.zip` (the version in `manifest.json` must match `extensionVersion` in `frontend/src/app/extension/page.tsx`).
- Backend tests need Postgres:
  ```
  DATABASE_URL=postgresql+asyncpg://…
  DATABASE_SSL=false
  APP_ENV=development
  ADMIN_EMAILS=ci-admin@example.com
  ```
  With those set, run `python scripts/init_db.py`, then `pytest tests`. All 364 tests passed after the rebrand (14 Nov 2026).

---

## ⚠️ ARCHITECTURE ADDENDUM (supersedes conflicting sections below)

The sections below this point describe the *original* design (self-hosted Postgres+pgvector,
Ollama, Redis/Celery, DigitalOcean). That design was revised before any code was written,
based on real constraints: no dedicated server to keep alive, and existing Claude + Groq +
Pinecone accounts already in hand. **The system actually being built uses this stack instead:**

| Component | Original plan | Actual |
|---|---|---|
| Relational DB | Self-hosted Postgres + pgvector | **Neon** (managed Postgres, free tier) — no pgvector needed |
| Vector search + embeddings | Ollama `nomic-embed-text` + self-hosted pgvector | **Pinecone** in production: serverless index `charcha` (`VECTOR_STORE=pinecone`, `PINECONE_INDEX`), collections `company_memory` / `company_policy` as namespaces, `app/services/pinecone_store.py` (REST, API version 2025-04). Vectors are `multilingual-e5-large` (1024-d) from **Pinecone Inference** (`PINECONE_API_KEY`, free ≤5M tokens/month) — run locally via fastembed it held ~2.5 GB of the 4 GB VM and starved the notetaker (2026-10-07). `qdrant_service` keeps the public API and dispatches; Qdrant + local fastembed remain the default without those settings, and production's Qdrant data was kept as a rollback after `scripts/migrate_qdrant_to_pinecone.py` |
| Memory-chat synthesis | Ollama `qwen2.5:7b` | **Claude Haiku 4.5** (same key as extraction, reused) |
| Background jobs | Redis + Celery | **None** — `/api/meetings/ingest` does transcribe → extract → store → embed → sheets-write inline in the request (volume is a few meetings/day, this is fine) |
| Backend hosting | DigitalOcean $6/mo droplet | Not yet decided — code is host-agnostic (plain FastAPI + Uvicorn); candidates are Cloud Run, Render, or Fly.io |
| Extension location | `extension/` subfolder in a fresh `charcha/` repo | Existing extension stays at the **project root** (`manifest.json`, `src/`) — this repo already had a working "Meet Notes to Sheets" extension before Charcha; `backend/` was added alongside it, not nested under a new top-level layout |

### Key implementation details that differ from the original snippets below

- **Claude model ID**: use the alias `claude-haiku-4-5` (not date-suffixed). Confirmed current as of 2026-07.
- **Prompt caching**: the `anthropic-beta: prompt-caching-2024-07-31` header shown below is **obsolete** — caching is GA now. Just put `cache_control: {"type": "ephemeral"}` on the system block in `system=[...]`, no beta header, no `client.beta.*` namespace. See `backend/app/services/ai_extractor.py`.
- **No `memory` table in Postgres** — vectors and their metadata (`meeting_title`, `meeting_date`, `content_type`) live entirely in Pinecone; Postgres only holds `users`, `meetings`, `tasks`, `decisions`, `traces`.
- **Pinecone SDK specifics** (verified against the installed `pinecone` package, not guessed): `index.upsert_records(namespace=..., records=[...])` and `index.search(namespace=..., top_k=..., inputs={"text": ...}, fields=[...])` are **keyword-only** — the docs' positional-arg examples don't match the installed client. See `backend/app/services/pinecone_service.py`.
- **Neon connection**: SQLAlchemy async engine uses `postgresql+asyncpg://...` with `connect_args={"ssl": "require"}` — the `sslmode`/`channel_binding` query params from the raw Neon connection string are libpq-specific and don't apply to asyncpg; they're stripped from the URL and handled via `connect_args` instead. See `backend/app/database/db.py`.
- **Auth**: the extension gets a Google OAuth access token via `chrome.identity.getAuthToken`, POSTs it to `/api/auth/google`, which verifies it against `https://www.googleapis.com/oauth2/v3/userinfo` (not ID-token verification) and issues a Charcha-specific JWT (HS256, 30-day expiry) that the extension then sends as `Authorization: Bearer <jwt>` on every other call. A Google sign-in only links to an existing account by email (case-insensitive) when Google reports `email_verified`. `ALLOWED_SIGNUP_DOMAINS` (comma-separated, empty = anyone) limits who can *create* an account by password or first Google sign-in; existing accounts and admin invites are unaffected. `ADMIN_EMAILS` matching is case-insensitive.
- **Meeting visibility is invite-based** — a meeting is readable by the account that recorded it and by colleagues on it in `meeting_attendees` with `access='granted'`: calendar invitees, colleagues who asked for the notetaker (capture subscribers), and anyone the organizer shared it with. People the notetaker heard in the call who weren't invited are stored with `access='pending'` until the recorder, the calendar organizer (`meetings.organizer_user_id`) or a Charcha admin shares it (`POST /api/meetings/{id}/attendees/{aid}/access`, `POST /api/meetings/{id}/share`; rule in `user_can_manage_meeting_access`). The public no-login share link (`/share-link`) follows the same rule — only the recorder, organizer or an admin can create or revoke it. `meeting_visibility_clause` / `user_can_read_meeting` in `app/dependencies.py` are the single source of the rule. **Admins get no list exemption**: their Home/Meetings/Tasks/digest/memory chat show only their meetings; they see everyone's via `GET /api/admin/meetings` (Admin → All meetings) and can open any single meeting (`viewing_as_admin` flag) — except a confidential one. A colleague who signs up after being invited gets those invites linked at account creation when their email is on the recorder's domain (`attendee_service.link_new_account`; clients stay external).
- **Privacy layer** (`app/services/privacy_service.py`): (1) **held tasks** — a task whose owner can't open its meeting (not the recorder or a granted attendee; admin exemption doesn't count) is invisible to them: no Tasks page, notification, email, due-soon or Jira auto-send, until the recorder/organizer sends it (`POST /api/tasks/{id}/owner-access` send | keep_private → `owner_shared_at` / `owner_kept_private_at`). Sending shares the task only — the owner's task list shows "A meeting you weren't in" with no link (`meeting_hidden`). Managers get one `tasks_held` notification per meeting. A person reassigning a task is a deliberate share (except in a confidential meeting); manual tasks too. Tasks are matched to people by account (`owner_user_id`), never by owner name text, outside meetings they can read. (2) **Confidential meetings** (`meetings.confidential`, `_source` ai|manual, `_reason`): only the recorder, organizer and granted attendees open them — no admin exemption (`user_can_read_meeting`, `user_can_manage_meeting_access`), listed to other admins as "Confidential meeting" with no title or content search, never sent to Jira, no public share link, titles kept out of auto vocabulary. Anyone in it can mark (`POST /api/meetings/{id}/confidential`); only recorder/organizer unmark. The extraction call returns `confidential` + `confidentialReason` (personnel, pay, legal, deals, health — prompt 2026-10-grounded-4+, no extra AI call) and `apply_ai_flag` marks it; a person's choice is never overruled.
- **One recording per meeting** — every notetaker request (web, extension, linked calendars, invites to the bot's address via `POST /api/bot/invites`) goes through `capture_service.request_capture`. At most one active `capture_requests` row per Meet code (partial unique index); later requesters become `capture_subscribers`. Stop releases only the caller; the bot leaves when the last subscriber stops (admins stop outright). Requests wait in a queue while notetakers are busy (`capture_queue_timeout_minutes`) and time out fast only when the notetaker is offline.
- **Linked Google Calendars** (`app/services/calendar_service.py`, `app/routes/calendar.py`) — per-user OAuth (events.readonly), refresh tokens encrypted with `secret_box` (key derived from JWT_SECRET). A loop started in `app.main` lifespan (Postgres advisory lock, one process) keeps a Google push channel (`events.watch` → `POST /api/calendar/push`, per-channel secret token, renewed a day before its 7-day expiry) on each calendar and re-reads it the moment Google reports a change — so a meeting added two minutes before it starts is still joined; safety-net sync every `calendar_sync_interval_seconds` (600) with push, every `calendar_poll_seconds` (60) when Google refused the channel (`watch_error`) and queues the notetaker `calendar_join_lead_seconds` before each Meet event per the person's rule (`all` / `organized` / `manual`, per-event `record_override`). Needs `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `PUBLIC_API_URL`, `PUBLIC_APP_URL`, and `{PUBLIC_API_URL}/api/calendar/callback` registered as a redirect URI on that OAuth client.
- **Pre-meeting briefs** (`app/services/prep_service.py`): shared by `POST /api/meetings/prep` and the calendar loop (`calendar_service.prepare_briefs`), which writes one brief per person per linked-calendar event `pre_meeting_brief_lead_minutes` (10) before it starts — Meet, Teams or Webex alike — into `calendar_events.brief`, then notifies with a `/dashboard?brief=<event id>` link. Built only from meetings that person can read: colleagues matched by account id, external guests by email, plus the previous occurrence's open items for a series. Attempted once (`brief_generated_at`), never retried on failure; billed as `pre_meeting_brief`.
- **Post-meeting follow-ups** (`app/services/followup_service.py`): once a meeting's notes are ready (inline ingest, upload pipeline, stage retry), every task owner with `owner_user_id` gets one `tasks_assigned` notification per meeting ("You were given N tasks in …") — to `?tab=actions` if they can read it, else the Tasks page. The meeting page's follow-up draft opens in Gmail / the mail app addressed to the invitees (`components/meeting/follow-up-draft.tsx`); Charcha never sends email itself.
- **Admin → Notetaker** (`app/services/notetaker_monitor.py`, `GET /api/admin/notetaker`): live and queued visits org-wide, capacity per notetaker instance (each claim call reports `instance`, `max_concurrent`, `active`, `has_auth` and writes a `service_heartbeats` row `notetaker:<instance>` besides the shared `notetaker` row), and 7-day failures bucketed by `failure_reason` (denied / not admitted / blocked by Meet / signed out / queue timeout / offline / error). More capacity = another notetaker container with the same `BOT_API_SECRET` (claims use SKIP LOCKED).
- **Stand-up digest** (`app/services/standup_service.py`, `GET /api/meetings/{id}/series/standup`): for a `standup`-template series, each person's updates / blockers / plans across the last 5 readable occurrences, from `template_sections`. Person = the item's `person` field (extractor prompt `2026-10-grounded-2`+), else a spoken "Name:" prefix; first names fold into a unique full name. Blockers in 2+ occurrences are flagged by deterministic word overlap (`same_blocker`), not an AI call.
- **Calendar/notetaker edge cases**: a calendar event moved after its visit was queued drags the visit's `scheduled_start/end` along (`calendar_service._follow_move`), and `/claim` won't hand out a visit more than `CLAIM_EARLY` (5 min) before its start; an extended event updates `scheduled_end`, which the bot re-reads every 15 s; a finished visit for an event moved into the future is queued again. "Coming up" keeps a meeting that is still being recorded past its end. When Meet turns the notetaker away because it's signed out of Google, every admin is told (≤ once per 12 h, `notetaker_monitor.alert_if_signed_out`). The extension keeps the last known state and retries (auto-invite every 30 s) when Charcha is unreachable. A recurring series whose last 3 finished visits were all "nobody admitted it" is no longer auto-joined (`calendar_service._series_keeps_refusing`, one `notetaker_skipped` notification); switching an occurrence on resumes it. The bot only treats a counted second participant or recent captions as company — being admitted isn't (it used to leave after 30 s on a misread count). Tests share the local DB with any local notetaker container — queue fixtures with a future `scheduled_start` so it can't claim them.
- **Email** (`app/services/email_service.py`, `email_stories.py`, `email_templates.py`, `app/routes/email.py`): Brevo transactional API (`BREVO_API_KEY`), sent as `Charcha <charcha@example.com>` (example.com is authenticated in Brevo), replies to connect@example.com. Everything goes through the `email_outbox` table — queued in the same transaction as its cause (`enqueue`, or automatically for in-app notifications of `NOTIFICATION_KINDS` via an after_flush hook), rendered at send time by one story per kind, deduped by `dedupe_key`, sent by a loop in `app.main` lifespan (advisory lock). Free plan = 300/day: non-security mail stops at `EMAIL_DAILY_LIMIT - EMAIL_SECURITY_RESERVE`, password resets/invites always go. **Notes ready is one email per meeting**: To the organizer (else the recorder), everyone else with access in CC (`payload.cc`), recipients re-checked at send time (active, wants it, can still read the meeting — the next one moves up to To). **Meeting email stays inside the company by default**: notes ready, tasks from a meeting, "added to a meeting", access-pending and series check-ins only go to people on `INTERNAL_EMAIL_DOMAINS` (default `example.com`) — anyone else (e.g. a client with an account who was on the calendar invite) only once the recorder, organizer or an admin shares the meeting with them in Charcha (`meeting_attendees.shared_at`, set by share / grant / the attendee editor), or if they recorded it or asked for its notetaker themselves (`email_service.may_email_about_meeting`), tasks grouped by person, no one-click unsubscribe on shared mail; the daily limit counts each recipient (`payload.sent_cc`). Stories: password reset (+ Google-only variant, which now carries a set-a-password link), password changed, admin invite (set your own password, 7 days), welcome, calendar disconnected, notetaker signed out (admins), pre-meeting brief, notes ready (recorder + granted attendees; bot/capture/upload meetings only), series review, tasks assigned, task assigned, access shared/pending, 09:00 IST due-today/overdue reminder, Monday weekly digest. Per-person preferences (`users.email_prefs`, Settings → Email); security mail can't be switched off; one-click unsubscribe (RFC 8058 POST; GET only redirects to /unsubscribe). Password reset/change sets `users.sessions_valid_after`, signing out older JWTs (they carry `iat`). New email = a `KINDS` entry + a renderer in `email_stories.RENDERERS` (an assert enforces it).
- **AI cost ledger** (`app/services/usage_ledger.py`): every Gemini generation (`gemini_service.generate_text/structured`, pass `feature=`) and Deepgram transcription writes an `ai_usage_events` row with tokens/audio seconds, USD cost from Google's published price table (`usage_ledger.default_token_prices`, date-aware: 3.6–3.8 Flash prices double on 2027-01-01; override with `AI_PRICING_JSON`), the USD→INR rate fetched at that moment (`exchange_rate_service`: free keyless daily sources only — open.er-api.com, Frankfurter/ECB, fawazahmed0 currency-api — cached `FX_CACHE_SECONDS`, default 1 h; no Tatum), INR cost, and the user/meeting from request context (`usage_ledger.attribute`). Events recorded before their meeting exists (bot/inline ingest) are linked to it when `attribute(meeting_id=…)` is called after the meeting commits. Admin → AI spend reads `GET /api/admin/ai-costs`. New AI features must go through `gemini_service` so they're billed.
- **Calendar-invited notetaker bot** (`backend/bot/`, Fireflies-style): inviting `notetaker@example.com` to a calendar event makes the bot scheduler queue it via `POST /api/bot/invites` (same single queue as everything else); the `notetaker` container claims it, joins the Meet, records audio + captions, and POSTs to `/api/bot/ingest` (shared-secret auth, `BOT_API_SECRET`). Filed under the organizer, or the first invitee with a Charcha account. Setup lives in `backend/bot/README.md`.
- **Microsoft Teams, by link** (`bot/teams_dom.py`, `TeamsSession` in `bot/meeting_session.py`, `capture_service._normalize_teams_url`): a Teams link pasted into Send notetaker goes through the same queue (`platform='microsoft_teams'`). The notetaker joins as an anonymous guest (no Microsoft account, never given the Google `auth.json`), so the host usually admits it. Links are rebuilt from validated parts on known hosts, keeping `p`/`context`; `meeting_code` is `teams-<id or hash>` and never contains the passcode. A `/meet/<id>` link and a `/l/meetup-join/` link to the same meeting get different codes, so they aren't deduplicated. Claims send `platforms`; a notetaker that sends none only gets Google Meet, so one awaiting restart during a deploy never takes a Teams job. Calendars still auto-join Meet only (`find_unsupported`).
- **Jira Cloud** (`app/services/jira_service.py`, `app/routes/jira.py`, Admin → Integrations): one company connection (`jira_connection` row id=1, secrets encrypted with `secret_box`) — **Connect with Jira** (Atlassian OAuth 2.0 3LO, `ATLASSIAN_CLIENT_ID`/`SECRET`, callback `{PUBLIC_API_URL}/api/jira/oauth/callback`, rotating refresh token refreshed under a row lock) or a service account's email + API token (`*.atlassian.net` only). Send per task, selected tasks (`POST /api/tasks/jira/bulk`), a meeting's open tasks, or automatically when notes are ready (`auto_send`: off/mapped/all); project via `project_map` else the default; a subtask whose parent is linked becomes a Jira sub-task; issues get the `charcha` label, the transcript quote and a link back. **People**: `jira_user_links` maps Charcha users ↔ Jira accounts — auto by email then exact unique display name (Jira Free hides most emails), admin overrides are `manual` and never auto-changed. **Two-way sync** of summary↔text, assignee↔owner, due date, priority, status *category*, and comments (deduped by `task_comments.jira_comment_id`): each task stores `jira_snapshot` (the issue as last synced); a poll copies only fields that differ from it (changed in Jira) and logs them as `task_history.source='jira'`; Charcha edits push at once (`push_changes`, background), failures go to `tasks.jira_error`, a 404 unlinks. **Access**: sending a task to Jira never opens its meeting to anyone — the issue carries the task; confidential meetings refuse (`JiraError`) and auto-send skips them and held tasks (`grant_team_access` was removed; `scripts/privacy_migration.py` set the old `source='jira'` grants back to pending for the organizer to decide). Workflows without an In Progress status (MT on Jira Free) are fine — no transition, no error. Loop in `app.main` lifespan (advisory lock 7_311_204_120, every 2 min, people re-matched hourly) polls `labels = charcha AND updated >= "-Nm"` via `/rest/api/3/search/jql` with fields + comments — polling, not webhooks, so it works on Jira Free with no setup.
- **Deploying to production**: the repo is `testing-archit/bhadra` (secrets `CHARCHA_VM_HOST`, `CHARCHA_VM_SSH_KEY`). A `test` job (backend tests, extension checks, frontend type check) must pass first. The VM has no GitHub access (the org disables deploy keys), so CI sends it the code as a git bundle; by hand use `SKIP_PULL=1 tools/deploy.sh`. Pushing to `main` deploys (`.github/workflows/deploy-vm.yml`): GitHub builds the changed images (never the e2-medium VM — builds there starved live meetings) with layers cached in GitHub's build cache (`type=gha`, base images re-pulled each run; `workflow_dispatch` `no_cache` rebuilds from scratch), pushes them through an SSH tunnel to a throwaway `registry:3` the deploy starts on the VM (bound to 127.0.0.1, digest-pinned, garbage-collected and stopped after) so only changed layers travel, then runs `SKIP_BUILD=1 tools/deploy.sh <services>` so each service restarts only when idle (a compose change restarts all three). By hand on the VM: `tools/deploy.sh [services]` (`--check` shows what's running). Qdrant is behind `profiles: [qdrant]` (rollback only; Pinecone serves search). VM tuning: 4 GB swap, `vm.swappiness=10`, Docker `live-restore` + 20 MB×3 log rotation (`/etc/docker/daemon.json`), notetaker `cpu_shares: 2048`, `MAX_CONCURRENT_MEETINGS` (default 3 in compose) — one Chrome per meeting ≈ 0.5 GB RAM and up to ½ vCPU. It builds first while the old containers serve, restarts the frontend at once, the backend only when no meeting is being processed or waiting to be ingested (120 s graceful stop), and the notetaker only when it isn't in a meeting — skipping, never forcing, anything still busy after `MAX_WAIT_MINUTES`. Never `docker compose up -d notetaker` by hand: it cuts a live recording off. nginx config is `nginx/default.conf`, mounted as a directory (a single-file bind mount kept serving the old file after `git reset`). The notetaker scheduler exits at once on SIGTERM when idle; during a meeting it stops taking work and finishes.
- **Vocabulary / learned corrections** (`app/services/vocabulary_service.py`, `app/routes/vocabulary.py`, `/vocabulary` page): `term_corrections` holds "heard as → actually" rules (`wrong` → `right`) and keywords (`wrong` NULL), `source` `learned` | `manual` | `suggested` | `auto` (+ `note`: where an auto/suggested one came from). Editing a task/decision/risk description, a transcript line or the summary runs `correct_from_edit`: a small, similar-sounding swap to a capitalised term whose old word isn't a real person's name (reassignments don't count) is applied across that meeting — segments, summary, insights, follow-up draft, other items, evidence — and learned; responses carry `learned_corrections`, which the web client broadcasts as `charcha:learned-corrections` so open pages reload. `apply_text` is idempotent (the right spelling is matched first and kept, so "Lattice" → "Sky Lattice" never doubles). **Deepgram keyterms** (max 50, `keyterms`) are per meeting, in priority order: the meeting's people (`people=` on `transcribe_audio_detailed` — invitees + Meet caption speakers for the bot, stored attendees/participants elsewhere), `TEAM_ROSTER`, keywords, rule right-spellings, every active account + `known_people`, then `auto` keywords. **Notes**: `insight_service.regenerate` calls `prepare_for_notes` (applies every current rule to the stored transcript and items, user None, then builds `prompt_hint`), the hint goes in the extraction *user* content (`vocabulary_hint=`, never the cached system prompt), and `clean_extraction` re-applies the rules to Gemini's output; the inline ingest does the same for pasted/caption transcripts. **Teammates** (`GET/POST/DELETE /api/vocabulary/people`): accounts (automatic), `known_people` guests anyone can add, TEAM_ROSTER, and regular guests (external attendees in ≥2 of *your readable* meetings in 180 days); "heard as" for a person is an ordinary rule with `right` = their name; a real person's name can't be a `wrong`. **Suggestions** (`term_suggestions`, `learn_from_meeting` after every notes-ready hook): a capitalised mid-sentence word never seen in lower case that sounds like exactly one invitee name word (`sound_key` + similarity), not a real name or known term; Meet captions (`captions.json` next to the recording) at the same moment mark it `captions`. Listed only to people who can read one of its meetings; accept → `suggested` rule + fix past meetings, dismiss sticks; nobody deciding → applied after `VOCABULARY_AUTO_APPLY_MEETINGS` (3; captions one fewer, min 2; 0 = never) distinct meetings, to those meetings only. **Auto keywords** (`refresh_auto_keywords`, ≤ hourly per process, after meetings): Charcha project names, Jira project names, capitalised words recurring in ≥2 meeting titles (90 days, stoplist); dropped when no longer derived unless switched off (stays off). Every Deepgram request applies the rules to the turns (case-insensitive, whole words). Adding a rule on the page can also fix past meetings (`fix_past_meetings`, background).
- **Attendees can be internal or external** — an internal attendee resolves to a Charcha account and gains access; an external attendee (a client, vendor, or candidate) is recorded on the meeting with `user_id = NULL` and never gains access. `app/services/attendee_service.py` does the resolution: by user id, then email, then an *exact, unambiguous* case-insensitive name match — a name shared by two active users resolves to nobody rather than guessing.

- **Meeting Assistant workspace** (`app/routes/meeting_workspace.py`, `app/routes/capture.py`): `transcript_segments` are the authoritative transcript once they exist — `meetings.transcript` is re-rendered from them. AI items carry validated `evidence` (segment id + verified quote) and `ai_flags`; regeneration (`insight_service.regenerate`) replaces only untouched AI items. Per-stage state lives in `meeting_processing_stages` (retry resumes at the failed stage, never re-transcribes). "Add notetaker by link" creates `capture_requests` that the bot claims via `/api/bot/capture-requests/claim` (also its heartbeat); status only moves on bot-reported events. Uploads go through `/api/meetings/upload` (ffprobe-validated, background pipeline). `FIXTURE_MODE` is dev-only and refused when `APP_ENV=production`.

- **Chrome extension v2 (no audio capture)**: the extension no longer records. `src/background.js` sends/stops the notetaker via `/api/capture/requests`, polls its status (toolbar badge, notifications), auto-invites when enabled (once per room per day), exports finished meetings to Google Sheets (the only path that still writes Sheets), and handles the `mem` omnibox keyword and "Ask Charcha" context menu. `src/content.js` is the in-Meet control; `src/popup.*` has Now / Tasks / Ask / Meetings tabs. `npm test` (`tools/validate-extension.mjs`) asserts no capture code or permissions return.
- **Web app information architecture**: left sidebar shell (`frontend/src/components/shell/`) with ⌘K command palette and light/dark theme (`frontend/src/lib/theme.tsx`; use theme tokens, never hard-coded hex colours). `/dashboard` is Home (my tasks, recent meetings, weekly digest); the meeting list lives at `/meetings`. Board is a view of `/tasks`, Digest is part of Home, Profile is part of `/settings` — the old routes only redirect. **Tasks page** opens on *My tasks* in the **Board** view (a chosen layout is remembered per browser; `?view=list`, `?scope=waiting|unassigned|all`). `GET /api/tasks` marks each task `mine` (owner_user_id, or owner text = your email/local part/name/first name) and `delegated` (from a meeting you recorded/organised or added by you, owned by someone else). Intelligence is deterministic, client-side in `lib/tasks.ts` (no AI cost): due buckets, `urgency` score + reasons → *Up next*, stale (open, untouched ≥14 days) with Done / +1 week / Delete, `possibleDuplicates` (word overlap ≥0.6; "Not duplicates" kept in localStorage), and per-owner *Waiting on* chips with a copyable reminder. Delete is on board cards, list rows, the task dialog and selected rows (`POST /api/tasks/delete`, same access rule as single delete).

Everything under **DATABASE SCHEMA**, **DOCKER COMPOSE**, **REQUIREMENTS.TXT** (Celery/Redis lines),
and the Ollama endpoints in **EXACT API SYNTAX** below is retained for historical reference only —
do not implement those parts as written.

---

## WHO YOU ARE AND WHAT YOU ARE BUILDING

You are the sole engineer on Charcha, an internal organizational memory platform
for an Indian startup team. You have full context on the product, architecture,
all API syntax, and all constraints. You do not ask clarifying questions before
coding — you make the right decision and explain it inline.

The product has two parts that work together:

1. A Chrome Extension (Manifest V3) that sits inside Google Meet,
   captures audio, transcribes it, extracts tasks and decisions using AI,
   and writes structured output to Google Sheets AND the Charcha backend.

2. A backend platform (FastAPI + PostgreSQL + pgvector + Redis + Ollama)
   that stores every meeting permanently, makes it searchable via vector
   similarity, and answers questions like "why did we choose PostgreSQL
   three months ago?" using a company memory chat interface.

The frontend is Next.js + TypeScript + Tailwind + shadcn/ui.

---

## THE ONLY RULE THAT OVERRIDES EVERYTHING ELSE: KEEP IT NEARLY FREE

Every architectural decision must minimize API cost. The target is ₹0–500/month
in API costs for a team of 5–15 people doing 3 meetings/day.

### Cost budget by component:

| Component | Provider | Target cost |
|---|---|---|
| Audio transcription | Groq Whisper (free tier) | ₹0 |
| Task/decision extraction | Claude Haiku 4.5 + prompt caching | ~₹5–50/mo |
| Embeddings | Ollama local (nomic-embed-text) | ₹0 |
| Memory chat | Ollama local (qwen2.5:7b) | ₹0 |
| Database | Self-hosted PostgreSQL + pgvector | ₹0 |
| Queue | Self-hosted Redis | ₹0 |
| Server | DigitalOcean Basic $6/mo droplet | ₹570/mo |

### How to achieve near-zero Claude API cost:

**Prompt caching is mandatory on every Claude call.**

The system prompt for extraction is ~400 tokens and identical on every call.
Cache it. Cost drops from $1.00 to $0.10 per million cached input tokens (90% off).

```python
# ALWAYS structure Claude calls like this — cache_control on the system prompt
messages_payload = [
    {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": EXTRACTION_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"}  # THIS IS MANDATORY
            },
            {
                "type": "text",
                "text": f"Transcript:\n{transcript}"
            }
        ]
    }
]
```

**Combine Hinglish cleaning + extraction into ONE Claude call.**
Never make two calls when one will do. The system prompt handles both jobs.

**Use Ollama for everything that does not need Claude-quality output:**
- Embeddings: always Ollama nomic-embed-text, never a paid API
- Memory chat synthesis: always Ollama qwen2.5:7b, never Claude
- Claude is ONLY used for extraction at meeting end (one call per meeting)

**Groq Whisper free tier limits:**
- 2,000 audio transcription requests per day
- At 5 users × 3 meetings × ceil(30min/10min chunks) = 45 requests/day
- You are at 2.25% of the free tier limit. Never pay for Whisper.

---

## API CREDENTIALS AND KEYS

Keys are stored in environment variables. Never hardcode. Never commit to git.

```
# .env (backend)
ANTHROPIC_API_KEY=sk-ant-...        # Claude Haiku 4.5
GROQ_API_KEY=gsk_...                # Whisper only
DATABASE_URL=postgresql+asyncpg://charcha:charchapass@localhost/charcha
REDIS_URL=redis://localhost:6379/0
OLLAMA_BASE_URL=http://localhost:11434
JWT_SECRET=<random 32-char string>
GOOGLE_CLIENT_ID=<from Google Cloud Console>
GOOGLE_CLIENT_SECRET=<from Google Cloud Console>
```

```
# .env.local (Chrome extension — NOT committed to git)
# Extension reads keys from chrome.storage.sync, set via popup UI
# Keys stored: groqApiKey, charchaApiToken (JWT from backend), spreadsheetId
```

---

## EXACT API SYNTAX — DO NOT DEVIATE FROM THESE

### 1. Claude Haiku 4.5 — extraction call (the only Claude call in the system)

Model string: `claude-haiku-4-5`
Endpoint: `https://api.anthropic.com/v1/messages`
Required header: `anthropic-beta: prompt-caching-2024-07-31`

```python
import anthropic

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

EXTRACTION_SYSTEM_PROMPT = """You are a meeting intelligence assistant for an Indian startup.
The transcript may contain Hinglish (mixed Hindi/English). Convert all Hinglish to clean English silently — do not mention the cleaning.
Extract structured data and respond ONLY with valid JSON — no markdown, no explanation, no code fences.

Required schema:
{
  "tasks": [
    {
      "task": "action item description in clean English",
      "assignedTo": "person's name or empty string",
      "dueDate": "due date if mentioned or empty string"
    }
  ],
  "decisions": [
    {
      "decision": "what was decided in clean English",
      "reason": "why this was decided",
      "alternatives": ["rejected option 1", "rejected option 2"],
      "participants": ["name1", "name2"]
    }
  ],
  "summary": "2-3 sentence plain English summary of the meeting"
}

Hinglish examples:
Input:  "Archit tum SIP AUM wala calculation check kar lena by Friday"
Output task: { "task": "Check the SIP AUM calculation", "assignedTo": "Archit", "dueDate": "Friday" }

Input:  "Hum PostgreSQL use karein because reporting ke liye SQL better hai"
Output decision: { "decision": "Use PostgreSQL", "reason": "Better for reporting with SQL queries", "alternatives": [], "participants": [] }"""


async def extract_from_transcript(transcript: str, meeting_title: str) -> dict:
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1500,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": EXTRACTION_SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"}
                    },
                    {
                        "type": "text",
                        "text": f"Meeting: {meeting_title}\n\nTranscript:\n{transcript}"
                    }
                ]
            }
        ]
    )

    content = response.content[0].text
    # response.usage.cache_creation_input_tokens — first call, charged at 1.25x
    # response.usage.cache_read_input_tokens    — subsequent calls, charged at 0.10x
    # Log these for cost tracking

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Claude occasionally wraps in ```json — strip it
        clean = content.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        parsed = json.loads(clean)

    return {
        "tasks": parsed.get("tasks", []),
        "decisions": parsed.get("decisions", []),
        "summary": parsed.get("summary", ""),
        "cache_tokens_read": response.usage.cache_read_input_tokens or 0,
        "cache_tokens_written": response.usage.cache_creation_input_tokens or 0,
        "output_tokens": response.usage.output_tokens,
    }
```

### 2. Groq Whisper — transcription (no SDK needed, plain httpx)

Endpoint: `POST https://api.groq.com/openai/v1/audio/transcriptions`
Model: `whisper-large-v3`
Auth: `Bearer {GROQ_API_KEY}`
CRITICAL: Do NOT set Content-Type header manually — httpx sets it for multipart automatically.

```python
import httpx

async def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/webm") -> str:
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            # DO NOT add "Content-Type" here — breaks multipart boundary
            files={"file": ("meeting.webm", audio_bytes, mime_type)},
            data={
                "model": "whisper-large-v3",
                "language": "en",           # set to "en" even for Hinglish — Whisper handles it
                "response_format": "json",  # returns {"text": "..."}
                "temperature": "0",
            }
        )

    if not response.is_success:
        raise Exception(f"Whisper error {response.status_code}: {response.text}")

    return response.json()["text"]
```

### 3. Ollama embeddings — nomic-embed-text (768 dimensions)

Endpoint: `POST http://localhost:11434/api/embeddings`
Pull model once: `ollama pull nomic-embed-text`

```python
async def generate_embedding(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.ollama_base_url}/api/embeddings",
            json={"model": "nomic-embed-text", "prompt": text}
        )

    if not response.is_success:
        raise Exception(f"Ollama embeddings error {response.status_code}")

    return response.json()["embedding"]  # list of 768 floats
```

### 4. Ollama chat — qwen2.5:7b (memory synthesis)

Endpoint: `POST http://localhost:11434/api/chat`
Pull model once: `ollama pull qwen2.5:7b`

```python
async def synthesize_answer(query: str, context: str) -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{settings.ollama_base_url}/api/chat",
            json={
                "model": "qwen2.5:7b",
                "stream": False,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a company memory assistant. "
                            "Answer using ONLY the context provided. "
                            "Always cite the meeting title and date. "
                            "If context is insufficient, say so clearly."
                        )
                    },
                    {
                        "role": "user",
                        "content": f"Context:\n{context}\n\nQuestion: {query}"
                    }
                ]
            }
        )

    return response.json()["message"]["content"]
```

### 5. Google Sheets API — append rows

Endpoint: `POST https://sheets.googleapis.com/v4/spreadsheets/{id}/values/{range}:append`
Query params: `?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS`
Auth: `Bearer {google_oauth_token}`

```python
async def append_rows_to_sheet(
    spreadsheet_id: str,
    sheet_name: str,
    rows: list[list[str]],
    token: str
) -> dict:
    range_encoded = f"{sheet_name}!A1".replace(" ", "%20")
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        f"/values/{range_encoded}:append"
        f"?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS"
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={"values": rows}
        )

    if response.status_code == 401:
        raise Exception("GOOGLE_TOKEN_EXPIRED")  # caller handles refresh

    if not response.is_success:
        raise Exception(f"Sheets API error {response.status_code}: {response.text}")

    return response.json()
```

### 6. Google Sheets API — auto-create tab if missing

Endpoint: `POST https://sheets.googleapis.com/v4/spreadsheets/{id}:batchUpdate`

```python
async def ensure_sheet_tab(spreadsheet_id: str, tab_name: str, token: str):
    # First check if tab exists
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
            f"?fields=sheets.properties.title",
            headers={"Authorization": f"Bearer {token}"}
        )
    existing = [s["properties"]["title"] for s in r.json().get("sheets", [])]
    if tab_name in existing:
        return  # already exists

    # Create it
    async with httpx.AsyncClient(timeout=15.0) as client:
        await client.post(
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}:batchUpdate",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
        )
```

### 7. pgvector — insert and search

```python
# INSERT (asyncpg — pass embedding as string "[0.1, 0.2, ...]")
await db.execute(
    """INSERT INTO memory (meeting_id, content, chunk_index, content_type, embedding)
       VALUES ($1, $2, $3, $4, $5::vector)""",
    meeting_id, content, chunk_index, content_type,
    "[" + ",".join(str(x) for x in embedding) + "]"
)

# SEARCH (cosine similarity — lower distance = more similar)
rows = await db.fetch(
    """SELECT m.content, m.meeting_id, mt.title, mt.date,
              m.embedding <=> $1::vector AS distance
       FROM memory m
       JOIN meetings mt ON m.meeting_id = mt.id
       WHERE mt.user_id = $2
       ORDER BY distance ASC
       LIMIT $3""",
    "[" + ",".join(str(x) for x in query_embedding) + "]",
    user_id, top_k
)
# <=> is pgvector COSINE distance operator (0 = identical, 2 = opposite)
```

### 8. Chrome extension — tabCapture + audio mix

```javascript
// background.js: get stream ID (must be called synchronously after user gesture or meeting-started)
const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });
// streamId expires in ~5 seconds — send to offscreen immediately

// offscreen.js: capture tab audio + user mic, mix, record
const tabStream = await navigator.mediaDevices.getUserMedia({
    audio: {
        mandatory: {
            chromeMediaSource: "tab",
            chromeMediaSourceId: streamId,  // from background.js
        }
    },
    video: false
});

const micStream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true },
    video: false
});

// CRITICAL: pipe tab audio back to speakers or user hears silence
const audioCtx = new AudioContext();
const tabSrc = audioCtx.createMediaStreamSource(tabStream);
tabSrc.connect(audioCtx.destination);  // plays audio back — DO NOT SKIP THIS

// Mix both into one stream
const micSrc = audioCtx.createMediaStreamSource(micStream);
const merger = audioCtx.createChannelMerger(2);
tabSrc.connect(merger, 0, 0);
micSrc.connect(merger, 0, 1);
const dest = audioCtx.createMediaStreamDestination();
merger.connect(dest);

// Record in 10-minute chunks (Whisper 25MB limit, webm/opus = ~5MB per 30min)
const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
    ? "audio/webm;codecs=opus"
    : "audio/webm";
const recorder = new MediaRecorder(dest.stream, { mimeType });
recorder.start(10 * 60 * 1000); // 10-minute chunks
```

---

## DATABASE SCHEMA — EXACT SQL

Run this once on first deploy. Use Alembic for subsequent migrations.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT UNIQUE NOT NULL,
    name        TEXT,
    google_sub  TEXT UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE meetings (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID REFERENCES users(id) ON DELETE CASCADE,
    title             TEXT NOT NULL,
    date              TIMESTAMPTZ NOT NULL,
    transcript        TEXT,
    summary           TEXT,
    duration_minutes  INTEGER DEFAULT 0,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tasks (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id       UUID REFERENCES meetings(id) ON DELETE CASCADE,
    owner            TEXT,
    description      TEXT NOT NULL,
    deadline         TEXT,
    status           TEXT DEFAULT 'pending',
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE decisions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id   UUID REFERENCES meetings(id) ON DELETE CASCADE,
    decision     TEXT NOT NULL,
    reason       TEXT,
    alternatives TEXT[],
    participants TEXT[],
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE memory (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id    UUID REFERENCES meetings(id) ON DELETE CASCADE,
    content       TEXT NOT NULL,
    chunk_index   INTEGER,
    content_type  TEXT,
    embedding     vector(768),
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE traces (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id               UUID REFERENCES users(id),
    meeting_id            UUID REFERENCES meetings(id),
    meeting_title         TEXT,
    duration_minutes      INTEGER,
    whisper_requests      INTEGER,
    claude_input_tokens   INTEGER,
    claude_output_tokens  INTEGER,
    claude_cache_hits     INTEGER,
    tasks_found           INTEGER,
    decisions_found       INTEGER,
    status                TEXT,
    created_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_meetings_user    ON meetings(user_id);
CREATE INDEX idx_tasks_meeting    ON tasks(meeting_id);
CREATE INDEX idx_decisions_meet   ON decisions(meeting_id);
CREATE INDEX idx_memory_meeting   ON memory(meeting_id);
CREATE INDEX idx_traces_user      ON traces(user_id);

-- pgvector HNSW index (no minimum row count, faster than ivfflat for small datasets)
CREATE INDEX idx_memory_vec ON memory USING hnsw (embedding vector_cosine_ops);
```

---

## FILE STRUCTURE — BUILD EXACTLY THIS

```
charcha/
├── CLAUDE.md                          ← this file
├── .env                               ← never commit
├── .gitignore
├── docker-compose.yml
│
├── extension/                         ← Chrome Extension (MV3)
│   ├── manifest.json
│   ├── icons/
│   │   ├── icon16.png
│   │   ├── icon48.png
│   │   └── icon128.png
│   └── src/
│       ├── background.js              ← orchestration, auth, API calls, Sheets writes
│       ├── offscreen.html             ← minimal HTML shell for MediaRecorder
│       ├── offscreen.js               ← audio capture + chunked recording
│       ├── content.js                 ← Meet DOM detection (start/end/title/PING)
│       ├── popup.html                 ← settings UI
│       └── popup.js                   ← toggle, login, history, settings
│
├── backend/
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── dependencies.py
│   │   ├── routes/
│   │   │   ├── auth.py
│   │   │   ├── meetings.py
│   │   │   ├── tasks.py
│   │   │   ├── decisions.py
│   │   │   ├── chat.py
│   │   │   └── admin.py
│   │   ├── services/
│   │   │   ├── ai_extractor.py        ← Claude Haiku 4.5 with prompt caching
│   │   │   ├── transcriber.py         ← Groq Whisper
│   │   │   ├── embedding_service.py   ← Ollama nomic-embed-text
│   │   │   ├── memory_retriever.py    ← pgvector search + Ollama synthesis
│   │   │   └── sheets_service.py      ← Google Sheets API writes
│   │   ├── workers/
│   │   │   └── meeting_worker.py      ← Celery task: embed + store chunks
│   │   └── database/
│   │       ├── models.py
│   │       ├── schemas.py
│   │       └── migrations/
│   └── scripts/
│       └── init_db.py                 ← run once to create tables
│
└── frontend/
    ├── package.json
    ├── next.config.ts
    ├── tailwind.config.ts
    └── app/
        ├── layout.tsx
        ├── login/page.tsx
        ├── dashboard/page.tsx
        ├── meetings/[id]/page.tsx
        ├── tasks/page.tsx
        ├── memory/page.tsx
        └── admin/page.tsx
```

---

## MANIFEST.JSON — EXACT REQUIRED CONTENT

```json
{
  "manifest_version": 3,
  "name": "Charcha",
  "version": "1.0.0",
  "description": "Captures Google Meet meetings into your company memory.",

  "permissions": [
    "tabCapture",
    "offscreen",
    "storage",
    "identity",
    "scripting",
    "tabs",
    "activeTab",
    "notifications"
  ],

  "host_permissions": [
    "https://meet.google.com/*",
    "https://sheets.googleapis.com/*",
    "https://www.googleapis.com/*"
  ],

  "oauth2": {
    "client_id": "YOUR_GOOGLE_OAUTH_CLIENT_ID.apps.googleusercontent.com",
    "scopes": [
      "https://www.googleapis.com/auth/spreadsheets",
      "https://www.googleapis.com/auth/userinfo.email",
      "https://www.googleapis.com/auth/userinfo.profile"
    ]
  },

  "background": { "service_worker": "src/background.js" },

  "content_scripts": [{
    "matches": ["https://meet.google.com/*"],
    "js": ["src/content.js"],
    "run_at": "document_idle"
  }],

  "action": {
    "default_popup": "src/popup.html",
    "default_icon": {
      "16": "icons/icon16.png",
      "48": "icons/icon48.png",
      "128": "icons/icon128.png"
    }
  }
}
```

---

## DOCKER COMPOSE — EXACT CONTENT

```yaml
version: "3.9"
services:

  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: charcha
      POSTGRES_USER: charcha
      POSTGRES_PASSWORD: charchapass
    ports: ["5432:5432"]
    volumes: [postgres_data:/var/lib/postgresql/data]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    volumes: [ollama_data:/root/.ollama]
    # After first start, run:
    # docker exec -it charcha-ollama-1 ollama pull nomic-embed-text
    # docker exec -it charcha-ollama-1 ollama pull qwen2.5:7b

volumes:
  postgres_data:
  ollama_data:
```

Backend and frontend run locally during development, not in Docker.
Deploy backend + celery to DigitalOcean Basic $6/mo droplet for production.
Ollama runs on the same machine or a separate server.

---

## REQUIREMENTS.TXT — EXACT PACKAGES

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
asyncpg==0.29.0
sqlalchemy[asyncio]==2.0.35
alembic==1.13.3
pydantic==2.9.2
pydantic-settings==2.5.2
httpx==0.27.2
anthropic==0.40.0
celery[redis]==5.4.0
PyJWT==2.9.0
python-multipart==0.0.12
```

Do not add unnecessary packages. Every dependency is justified above.

---

## BUILD ORDER — FOLLOW THIS SEQUENCE EXACTLY

Claude Code must build in this order. Do not skip steps or reorder.

```
PHASE 1 — Infrastructure (30 min)
  1. Create docker-compose.yml
  2. docker compose up -d
  3. Create backend/scripts/init_db.py and run it
  4. Verify: psql connects, pgvector extension exists, all tables created

PHASE 2 — Backend core (2 hours)
  5. app/main.py + config.py + dependencies.py
  6. app/routes/auth.py — Google token verify + JWT issue
  7. app/routes/meetings.py — POST /ingest endpoint only
  8. app/services/transcriber.py — Groq Whisper
  9. app/services/ai_extractor.py — Claude Haiku 4.5 with prompt caching
  10. Test end-to-end: POST a fake transcript to /ingest, verify DB rows created

PHASE 3 — Extension (2 hours)
  11. manifest.json + icons
  12. content.js — meeting detection + PING responder
  13. offscreen.html + offscreen.js — audio capture + chunked recording
  14. background.js — meeting lifecycle, Groq Whisper call, Claude call, Sheets write, backend POST
  15. popup.html + popup.js — toggle, login, settings, history
  16. Load unpacked in Chrome, join a Meet call, verify it records and processes

PHASE 4 — Memory layer (2 hours)
  17. app/services/embedding_service.py — Ollama
  18. workers/meeting_worker.py — Celery: chunk transcript, embed, store in pgvector
  19. app/services/memory_retriever.py — vector search + structured search + Ollama synthesis
  20. app/routes/chat.py
  21. Test: ask "what decisions did we make?" and verify answer with citations

PHASE 5 — Remaining routes + admin (1 hour)
  22. app/routes/tasks.py — list + status update
  23. app/routes/decisions.py — list + detail
  24. app/routes/admin.py — traces + usage summary

PHASE 6 — Frontend (3 hours)
  25. Next.js scaffold: npx create-next-app@latest frontend --typescript --tailwind --app
  26. Install shadcn: npx shadcn@latest init
  27. lib/api.ts — typed fetch wrappers
  28. login/page.tsx — Google OAuth button
  29. dashboard/page.tsx — meeting list
  30. meetings/[id]/page.tsx — tasks + decisions + transcript
  31. memory/page.tsx — chat interface
  32. admin/page.tsx — traces table (admin emails only)
```

---

## CRITICAL GOTCHAS — READ BEFORE WRITING ANY CODE

### Chrome Extension
- `chrome.tabCapture.getMediaStreamId` must be called from background.js, not offscreen.js
- streamId expires in ~5 seconds — send to offscreen immediately after getting it
- `tabSrc.connect(audioCtx.destination)` is MANDATORY — skip it and user hears silence
- Offscreen document can only exist once — check `chrome.runtime.getContexts` before creating
- `chrome.storage.sync` max 100KB — use `chrome.storage.local` for meeting history and backups
- `chrome.tabs.onRemoved` must trigger meeting end processing — user may close tab without leaving meeting

### Claude API
- `anthropic-beta: prompt-caching-2024-07-31` header is REQUIRED for caching to work
- `cache_control: {"type": "ephemeral"}` must be on the SYSTEM PROMPT content block
- Cache TTL: 5 minutes by default. For 1-hour TTL use `{"type": "ephemeral"}` with the 1h write at 2x cost
- `response.usage.cache_read_input_tokens` tells you if caching worked — log this
- If JSON parse fails, strip markdown fences before retrying — do not make a second API call

### Groq Whisper
- DO NOT set `Content-Type` header — httpx sets it automatically for multipart
- 25MB file size limit — 30min webm/opus is ~5-8MB, safe
- 10-second minimum billing unit — always send chunks of at least 10 seconds
- `language: "en"` improves accuracy even for Hinglish — Whisper handles code-switching

### pgvector
- Use HNSW index not ivfflat — HNSW works with zero rows, ivfflat needs data first
- asyncpg does not auto-cast Python lists to vector — always stringify: `"[" + ",".join(str(x) for x in embedding) + "]"`
- `<=>` is cosine distance, `<->` is L2 distance, `<#>` is inner product — use `<=>` for semantic search

### FastAPI
- Use `async def` for all route handlers — the db and http calls are async
- `BackgroundTasks.add_task()` does not support async functions directly — use `asyncio.create_task()` or Celery
- Return proper HTTP status codes: 201 for creation, 404 for not found, 403 for forbidden

### Google OAuth in extension
- `chrome.identity.getAuthToken` returns the token for the Google account signed into Chrome
- After getting the Google token, POST to `/api/auth/google` to get a Charcha JWT
- Store the Charcha JWT as `charchaApiToken` in `chrome.storage.sync`
- On 401 from backend: clear cached Google token, re-authenticate, get new Charcha JWT

---

## ADMIN CONFIGURATION

Admin emails are hardcoded. Update this list before deploying:

```python
# backend/app/routes/admin.py
ADMIN_EMAILS = ["your-email@company.com"]
```

```javascript
// extension/src/popup.js
const ADMIN_EMAILS = ["your-email@company.com"];
```

---

## ERROR HANDLING PATTERNS

Every external API call must:
1. Have a timeout
2. Check response status before parsing
3. Have a specific error message that tells you which service failed
4. Write a trace record even on failure — status field shows the error

```python
# Standard error pattern for all service calls
async def call_with_context(coro, service_name: str):
    try:
        return await coro
    except httpx.TimeoutException:
        raise Exception(f"{service_name}: request timed out")
    except httpx.HTTPStatusError as e:
        raise Exception(f"{service_name}: HTTP {e.response.status_code} — {e.response.text[:200]}")
    except Exception as e:
        raise Exception(f"{service_name}: {str(e)[:200]}")
```

---

## COST MONITORING

After every meeting is processed, write a trace row. This is non-negotiable.
The admin dashboard reads traces to show monthly API spend per user.

```python
# In meeting_worker.py, after processing completes
await db.execute(
    """INSERT INTO traces
       (user_id, meeting_id, meeting_title, duration_minutes,
        whisper_requests, claude_input_tokens, claude_output_tokens,
        claude_cache_hits, tasks_found, decisions_found, status)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
    user_id, meeting_id, title, duration,
    whisper_req_count,
    extraction_result["cache_tokens_written"] + extraction_result["cache_tokens_read"],
    extraction_result["output_tokens"],
    extraction_result["cache_tokens_read"],   # non-zero = caching worked
    len(tasks), len(decisions),
    "success"
)
```

---

## WHAT SUCCESS LOOKS LIKE

After a 30-minute meeting:
1. Extension detected meeting start automatically — no user action
2. Audio captured silently — user heard everything normally during the call
3. On meeting end: Groq Whisper transcribed in <15 seconds
4. Claude Haiku 4.5 extracted tasks, decisions, summary in <3 seconds
5. Google Sheets has new rows: tasks in "Tasks" tab, summary in "Meeting Notes" tab
6. Backend has the full record in PostgreSQL
7. Memory worker embedded the transcript into pgvector
8. User can open the memory chat and ask "what did we decide about X?" and get an answer with a citation to this meeting
9. Admin can open the admin page and see token usage for this meeting
10. Total API cost for this meeting: under ₹2

---

## REFERENCE DOCUMENTS

Three spec files exist in the project root. Read them when you need deeper
context on any component. This CLAUDE.md is the directive — the spec files
are the reference.

- AGENT_SPEC.md    — Chrome extension audio capture, Groq Whisper syntax, Sheets API syntax
- AGENT_SPEC_V2.md — On/off toggle, user login, admin traces, retry logic, local backup
- AGENT_SPEC_V3.md — Full merged architecture, backend routes, DB schema, Ollama endpoints, build order
