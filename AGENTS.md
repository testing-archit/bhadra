# Charcha — Codex System Prompt
# Place this file as AGENTS.md in the root of the project.
# Codex reads this automatically on every session.

---

## SHARED REPOSITORY WORKFLOW

Another engineer also pushes to this repository. Before every push, fetch the
destination branch and inspect the incoming commits and changed files. Bring
those commits into the local branch before pushing: use a fast-forward pull when
possible; if histories diverge, integrate them deliberately and resolve any
conflicts without discarding either person's work. Preserve uncommitted changes
while doing this. Run the relevant checks after integration, review the final
diff and status, then push. Never force-push over a collaborator's commits.

---

## ⚠️ ARCHITECTURE ADDENDUM (supersedes conflicting sections below)

The sections below this point describe the *original* design (self-hosted Postgres+pgvector,
Ollama, Redis/Celery, DigitalOcean). That design was revised before any code was written,
based on real constraints: no dedicated server to keep alive, and existing Codex + Groq +
Pinecone accounts already in hand. **The system actually being built uses this stack instead:**

| Component | Original plan | Actual |
|---|---|---|
| Relational DB | Self-hosted Postgres + pgvector | **Neon** (managed Postgres, free tier) — no pgvector needed |
| Vector search + embeddings | Ollama `nomic-embed-text` + self-hosted pgvector | **Pinecone** serverless index with **integrated inference** (`llama-text-embed-v2`) — Pinecone generates embeddings server-side on upsert/search, no separate embedding call |
| Memory-chat synthesis | Ollama `qwen2.5:7b` | **Codex Haiku 4.5** (same key as extraction, reused) |
| Background jobs | Redis + Celery | **None** — `/api/meetings/ingest` does transcribe → extract → store → embed → sheets-write inline in the request (volume is a few meetings/day, this is fine) |
| Backend hosting | DigitalOcean $6/mo droplet | Not yet decided — code is host-agnostic (plain FastAPI + Uvicorn); candidates are Cloud Run, Render, or Fly.io |
| Extension location | `extension/` subfolder in a fresh `charcha/` repo | Existing extension stays at the **project root** (`manifest.json`, `src/`) — this repo already had a working "Meet Notes to Sheets" extension before Charcha; `backend/` was added alongside it, not nested under a new top-level layout |

### Key implementation details that differ from the original snippets below

- **Codex model ID**: use the alias `Codex-haiku-4-5` (not date-suffixed). Confirmed current as of 2026-07.
- **Prompt caching**: the `anthropic-beta: prompt-caching-2024-07-31` header shown below is **obsolete** — caching is GA now. Just put `cache_control: {"type": "ephemeral"}` on the system block in `system=[...]`, no beta header, no `client.beta.*` namespace. See `backend/app/services/ai_extractor.py`.
- **No `memory` table in Postgres** — vectors and their metadata (`meeting_title`, `meeting_date`, `content_type`) live entirely in Pinecone; Postgres only holds `users`, `meetings`, `tasks`, `decisions`, `traces`.
- **Pinecone SDK specifics** (verified against the installed `pinecone` package, not guessed): `index.upsert_records(namespace=..., records=[...])` and `index.search(namespace=..., top_k=..., inputs={"text": ...}, fields=[...])` are **keyword-only** — the docs' positional-arg examples don't match the installed client. See `backend/app/services/pinecone_service.py`.
- **Neon connection**: SQLAlchemy async engine uses `postgresql+asyncpg://...` with `connect_args={"ssl": "require"}` — the `sslmode`/`channel_binding` query params from the raw Neon connection string are libpq-specific and don't apply to asyncpg; they're stripped from the URL and handled via `connect_args` instead. See `backend/app/database/db.py`.
- **Auth**: the extension gets a Google OAuth access token via `chrome.identity.getAuthToken`, POSTs it to `/api/auth/google`, which verifies it against `https://www.googleapis.com/oauth2/v3/userinfo` (not ID-token verification) and issues a Charcha-specific JWT (HS256, 30-day expiry) that the extension then sends as `Authorization: Bearer <jwt>` on every other call.
- **Meeting visibility is invite-based** — a meeting is readable by the account that recorded it and by colleagues on it in `meeting_attendees` with `access='granted'`: calendar invitees, colleagues who asked for the notetaker (capture subscribers), and anyone the organizer shared it with. People the notetaker heard in the call who weren't invited are stored with `access='pending'` until the recorder, the calendar organizer (`meetings.organizer_user_id`) or a Charcha admin shares it (`POST /api/meetings/{id}/attendees/{aid}/access`, `POST /api/meetings/{id}/share`; rule in `user_can_manage_meeting_access`). `meeting_visibility_clause` / `user_can_read_meeting` in `app/dependencies.py` are the single source of the rule. **Admins get no list exemption**: their Home/Meetings/Tasks/digest/memory chat show only their meetings; they see everyone's via `GET /api/admin/meetings` (Admin → All meetings) and can open any single meeting (`viewing_as_admin` flag). Exception kept: a task whose `owner` matches your name or email stays visible.
- **One recording per meeting** — every notetaker request (web, extension, linked calendars, invites to the bot's address via `POST /api/bot/invites`) goes through `capture_service.request_capture`. At most one active `capture_requests` row per Meet code (partial unique index); later requesters become `capture_subscribers`. Stop releases only the caller; the bot leaves when the last subscriber stops (admins stop outright). Requests wait in a queue while notetakers are busy (`capture_queue_timeout_minutes`) and time out fast only when the notetaker is offline.
- **Linked Google Calendars** (`app/services/calendar_service.py`, `app/routes/calendar.py`) — per-user OAuth (events.readonly), refresh tokens encrypted with `secret_box` (key derived from JWT_SECRET). A loop started in `app.main` lifespan (Postgres advisory lock, one process) syncs each calendar every `calendar_sync_interval_seconds` and queues the notetaker `calendar_join_lead_seconds` before each Meet event per the person's rule (`all` / `organized` / `manual`, per-event `record_override`). Needs `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `PUBLIC_API_URL`, `PUBLIC_APP_URL`, and `{PUBLIC_API_URL}/api/calendar/callback` registered as a redirect URI on that OAuth client.
- **AI cost ledger** (`app/services/usage_ledger.py`): every Gemini generation (`gemini_service.generate_text/structured`, pass `feature=`) and Deepgram transcription writes an `ai_usage_events` row with tokens/audio seconds, USD cost from the price table (override with `AI_PRICING_JSON`), the USD→INR rate fetched at that moment (`exchange_rate_service`: Tatum, then free daily sources, cached `FX_CACHE_SECONDS`), INR cost, and the user/meeting from request context (`usage_ledger.attribute`). Admin → AI spend reads `GET /api/admin/ai-costs`. New AI features must go through `gemini_service` so they're billed.
- **Calendar-invited notetaker bot** (`backend/bot/`, Fireflies-style): inviting `notetaker@example.com` to a calendar event makes the bot scheduler queue it via `POST /api/bot/invites` (same single queue as everything else); the `notetaker` container claims it, joins the Meet, records audio + captions, and POSTs to `/api/bot/ingest` (shared-secret auth, `BOT_API_SECRET`). Filed under the organizer, or the first invitee with a Charcha account. Setup lives in `backend/bot/README.md`.

- **Chrome extension v2 (no audio capture)**: the extension no longer records. `src/background.js` sends/stops the notetaker via `/api/capture/requests`, polls its status (toolbar badge, notifications), auto-invites when enabled (once per room per day), exports finished meetings to Google Sheets (the only path that still writes Sheets), and handles the `mem` omnibox keyword and "Ask Charcha" context menu. `src/content.js` is the in-Meet control; `src/popup.*` has Now / Tasks / Ask / Meetings tabs. `npm test` (`tools/validate-extension.mjs`) asserts no capture code or permissions return.
- **Web app information architecture**: left sidebar shell (`frontend/src/components/shell/`) with ⌘K command palette and light/dark theme (`frontend/src/lib/theme.tsx`; use theme tokens, never hard-coded hex colours). `/dashboard` is Home (my tasks, recent meetings, weekly digest); the meeting list lives at `/meetings`. Board is a view of `/tasks`, Digest is part of Home, Profile is part of `/settings` — the old routes only redirect.

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
| Task/decision extraction | Codex Haiku 4.5 + prompt caching | ~₹5–50/mo |
| Embeddings | Ollama local (nomic-embed-text) | ₹0 |
| Memory chat | Ollama local (qwen2.5:7b) | ₹0 |
| Database | Self-hosted PostgreSQL + pgvector | ₹0 |
| Queue | Self-hosted Redis | ₹0 |
| Server | DigitalOcean Basic $6/mo droplet | ₹570/mo |

### How to achieve near-zero Codex API cost:

**Prompt caching is mandatory on every Codex call.**

The system prompt for extraction is ~400 tokens and identical on every call.
Cache it. Cost drops from $1.00 to $0.10 per million cached input tokens (90% off).

```python
# ALWAYS structure Codex calls like this — cache_control on the system prompt
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

**Combine Hinglish cleaning + extraction into ONE Codex call.**
Never make two calls when one will do. The system prompt handles both jobs.

**Use Ollama for everything that does not need Codex-quality output:**
- Embeddings: always Ollama nomic-embed-text, never a paid API
- Memory chat synthesis: always Ollama qwen2.5:7b, never Codex
- Codex is ONLY used for extraction at meeting end (one call per meeting)

**Groq Whisper free tier limits:**
- 2,000 audio transcription requests per day
- At 5 users × 3 meetings × ceil(30min/10min chunks) = 45 requests/day
- You are at 2.25% of the free tier limit. Never pay for Whisper.

---

## API CREDENTIALS AND KEYS

Keys are stored in environment variables. Never hardcode. Never commit to git.

```
# .env (backend)
ANTHROPIC_API_KEY=sk-ant-...        # Codex Haiku 4.5
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

### 1. Codex Haiku 4.5 — extraction call (the only Codex call in the system)

Model string: `Codex-haiku-4-5`
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
        model="Codex-haiku-4-5",
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
        # Codex occasionally wraps in ```json — strip it
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
├── AGENTS.md                          ← this file
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
│   │   │   ├── ai_extractor.py        ← Codex Haiku 4.5 with prompt caching
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

Codex must build in this order. Do not skip steps or reorder.

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
  9. app/services/ai_extractor.py — Codex Haiku 4.5 with prompt caching
  10. Test end-to-end: POST a fake transcript to /ingest, verify DB rows created

PHASE 3 — Extension (2 hours)
  11. manifest.json + icons
  12. content.js — meeting detection + PING responder
  13. offscreen.html + offscreen.js — audio capture + chunked recording
  14. background.js — meeting lifecycle, Groq Whisper call, Codex call, Sheets write, backend POST
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

### Codex API
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
4. Codex Haiku 4.5 extracted tasks, decisions, summary in <3 seconds
5. Google Sheets has new rows: tasks in "Tasks" tab, summary in "Meeting Notes" tab
6. Backend has the full record in PostgreSQL
7. Memory worker embedded the transcript into pgvector
8. User can open the memory chat and ask "what did we decide about X?" and get an answer with a citation to this meeting
9. Admin can open the admin page and see token usage for this meeting
10. Total API cost for this meeting: under ₹2

---

## REFERENCE DOCUMENTS

Three spec files exist in the project root. Read them when you need deeper
context on any component. This AGENTS.md is the directive — the spec files
are the reference.

- AGENT_SPEC.md    — Chrome extension audio capture, Groq Whisper syntax, Sheets API syntax
- AGENT_SPEC_V2.md — On/off toggle, user login, admin traces, retry logic, local backup
- AGENT_SPEC_V3.md — Full merged architecture, backend routes, DB schema, Ollama endpoints, build order
