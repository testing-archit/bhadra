from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    database_ssl: bool = True
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    embedding_model: str = "intfloat/multilingual-e5-large"
    embedding_cache_dir: str = ".fastembed_cache"
    # Set in production: embeddings come from Pinecone Inference (same
    # multilingual-e5-large) instead of a 2.2 GB local model. See embedding_service.
    pinecone_api_key: str = ""
    # "qdrant" (self-hosted, default) or "pinecone" (serverless index
    # PINECONE_INDEX; copy existing vectors first with
    # scripts/migrate_qdrant_to_pinecone.py).
    vector_store: str = "qdrant"
    pinecone_index: str = "charcha"
    recordings_dir: str = "recordings"

    # Empty-string defaults so the app can boot (and serve everything that
    # doesn't call out to Gemini/Prisma — auth, tasks, decisions, projects,
    # digest) with zero configuration. Only ingest/chat/policy-chat routes
    # actually need these to be real; they fail at request time, not at
    # startup, if left blank.
    # Bound live command admission and execution across API processes.
    meeting_agent_workers: int = Field(default=2, ge=1, le=16)
    meeting_agent_queue_per_capture: int = Field(default=8, ge=1, le=32)
    meeting_agent_queue_global: int = Field(default=64, ge=1, le=1000)
    meeting_agent_timeout_seconds: int = Field(default=45, ge=1, le=180)
    meeting_agent_lease_seconds: int = Field(default=15, ge=1, le=60)
    meeting_agent_provider_seconds: int = Field(default=15, ge=1, le=60)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    # Small, frequent jobs (meeting-type detection, conflict checks).
    gemini_fast_model: str = "gemini-3.5-flash-lite"
    groq_api_key: str = ""
    # Gnani Prisma v3.0 handles Indian-language and code-mixed meeting audio.
    # Keep the URL configurable: the programme console may issue a dedicated
    # regional endpoint without requiring a code change.
    gnani_api_key: str = ""
    gnani_stt_url: str = "https://api.vachana.ai/stt/v3"
    gnani_stt_model: str = "prisma-v3.0"
    gnani_stt_mode: str = "codemix"
    # Local, CPU speaker embedding model. Used only for enrolled employees.
    speaker_embedding_model_path: str = "models/wespeaker_en_voxceleb_resnet34.onnx"
    speaker_match_threshold: float = 0.72
    speaker_match_margin: float = 0.12
    # Gnani Timbre text-to-speech: Charcha reads answers and summaries aloud
    # with the same Gnani key. v2.5 answers in ~1 s; "hi-en" speaks Hinglish
    # (Roman-script Hindi mixed with English) naturally.
    gnani_tts_url: str = "https://api.vachana.ai/api/v1/tts/inference"
    gnani_tts_model: str = "timbre-v2.5"
    gnani_tts_voice: str = "Nalini"
    gnani_tts_english_voice: str = "Shlok"
    gnani_tts_language: str = "hi-en"
    # Other Indian languages (Tamil, Marathi, Bengali, ...): Timbre v3.0
    # voices speak all ten.
    gnani_tts_multilingual_model: str = "timbre-v3.0"
    gnani_tts_multilingual_voice: str = "Shivani"
    # How long one USD→INR quote is reused when pricing AI calls. Each AI
    # call stores the rate it was priced at; the free sources publish daily
    # reference rates, so asking more often than hourly gains nothing.
    fx_cache_seconds: int = 3600
    # Transactional email through Brevo. Without a key nothing is sent (the
    # outbox still records what would have gone out).
    brevo_api_key: str = ""
    email_from: str = "charcha@example.com"
    email_from_name: str = "Charcha"
    email_reply_to: str = "connect@example.com"
    # Brevo's free plan sends 300 a day; stay under it and keep room for
    # password resets, which are never held back.
    email_daily_limit: int = 280
    email_security_reserve: int = 20
    # Optional JSON overriding the AI price table in usage_ledger.py.
    ai_pricing_json: str = ""

    jwt_secret: str = "dev-insecure-secret-do-not-use-in-production"
    # "Connect with Jira": an OAuth 2.0 (3LO) app registered at
    # developer.atlassian.com/console/myapps, callback
    # {PUBLIC_API_URL}/api/jira/oauth/callback. Without these, admins can still
    # connect Jira with an API token.
    atlassian_client_id: str = ""
    atlassian_client_secret: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""

    admin_emails: str = ""

    # Shared secret between this API and the calendar-invited notetaker bot
    # (backend/bot). Empty disables /api/bot/* entirely.
    bot_api_secret: str = ""
    # The Google account people invite to their calendar events, Fireflies
    # style. Never treated as a meeting owner or attendee.
    notetaker_email: str = "notetaker@example.com"

    # Comma-separated team member first names. Fed into Prisma keyterm
    # prompting to improve recognition of names
    # instead of mangling them into phonetically-similar English words
    # (e.g. "Vaibhav" -> "wherever") — this is what actually fixes
    # Hinglish transcription accuracy, not a different STT provider.
    team_roster: str = ""
    # Comma-separated email domains allowed to create an account (password
    # sign-up or a first Google sign-in), e.g. "example.com". Empty: anyone.
    # Existing accounts and admin invites are never blocked by it.
    allowed_signup_domains: str = ""
    # Comma-separated email domains whose people get a meeting's emails (notes
    # ready, tasks from it, "added to a meeting") just for being on it. Anyone
    # else — e.g. a client with an account who was on the calendar invite —
    # only gets them once the recorder, organizer or an admin shares the
    # meeting with them in Charcha. Empty: everyone with access.
    internal_email_domains: str = "example.com"
    # A vocabulary suggestion (a word that sounds like an invitee's name) is
    # applied without waiting for anyone once heard in this many meetings —
    # one fewer when Meet's captions back it up. 0: only ever by hand.
    vocabulary_auto_apply_meetings: int = 3

    # Comma-separated frontend origins allowed to call the API. The Chrome
    # extension is unaffected by this — Manifest V3 host_permissions already
    # exempts its fetch() calls from CORS enforcement.
    allowed_origins: str = "http://localhost:3000"

    # "production" refuses development fixture mode outright.
    app_env: str = "development"
    # Development-only stand-ins for Prisma and Gemini so the Meeting
    # Assistant can be previewed and tested without paid keys. Every fixture
    # output is labelled as such; it never simulates a bot joining a call.
    fixture_mode: bool = False

    # Meeting Assistant uploads. Validated against the decoded file, not the
    # extension or the browser-supplied content type.
    max_upload_bytes: int = 200 * 1024 * 1024
    max_upload_duration_minutes: int = 240
    # Background processing pipelines allowed to run at once per API process.
    max_concurrent_processing: int = 2
    # Above this many transcript characters, extraction runs per chunk and a
    # synthesis pass merges the results.
    extraction_chunk_chars: int = 120_000
    # A capture request nobody has claimed after this long is timed out
    # rather than left "requested" forever.
    capture_claim_timeout_minutes: int = 10
    # While the notetaker is online but busy in other calls, a request waits
    # this long for a free one before it is given up on.
    capture_queue_timeout_minutes: int = 45
    # The notetaker counts as offline once it hasn't checked in for this long.
    notetaker_offline_after_seconds: int = 90
    # Linked calendars: with a live Google push channel a calendar is re-read
    # the moment it changes, plus this safety-net interval; without one it
    # is polled every calendar_poll_seconds.
    calendar_sync_interval_seconds: int = 600
    calendar_poll_seconds: int = 60
    # How early before the start time the notetaker is queued (it then takes
    # ~20 s to knock).
    calendar_join_lead_seconds: int = 60
    # How long before a linked-calendar meeting its pre-meeting brief is
    # written and the person notified.
    pre_meeting_brief_lead_minutes: int = 10
    # Public URL of this API, for the Google OAuth redirect. Defaults to the
    # first allowed origin's host for local development.
    public_api_url: str = ""
    # Where the browser returns after linking a calendar.
    public_app_url: str = ""
    # Rates used only for the *estimated* cost shown per meeting; set them to
    # your contract's prices. Zero shows usage without a cost estimate.
    transcription_usd_per_minute: float = 0.0
    ai_usd_per_million_input_tokens: float = 0.0
    ai_usd_per_million_output_tokens: float = 0.0

    @property
    def fixture_mode_active(self) -> bool:
        return self.fixture_mode and self.app_env.lower() != "production"

    @property
    def allowed_signup_domain_list(self) -> list[str]:
        return [d.strip().lower().lstrip("@") for d in self.allowed_signup_domains.split(",") if d.strip()]

    @property
    def internal_email_domain_list(self) -> list[str]:
        return [d.strip().lower().lstrip("@") for d in self.internal_email_domains.split(",") if d.strip()]

    @property
    def admin_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]

    @property
    def team_roster_list(self) -> list[str]:
        return [n.strip() for n in self.team_roster.split(",") if n.strip()]

    @property
    def allowed_origin_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
