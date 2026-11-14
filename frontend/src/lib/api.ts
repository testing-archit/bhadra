const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
const TOKEN_KEY = "charchaToken";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

// Lets the extension's content script (src/auth-bridge.js) — which can't see
// same-tab localStorage writes via the "storage" event — know synchronously
// that this page's session just changed, so it can mirror the extension's
// own session immediately instead of only on next page load.
function notifyAuthBridge() {
  window.postMessage({ source: "charcha-webapp", type: "auth-changed" }, window.location.origin);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
  notifyAuthBridge();
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  notifyAuthBridge();
}

/**
 * Reads the `exp` claim out of a JWT without verifying the signature —
 * only used client-side to decide whether it's worth silently refreshing
 * the session. The server independently verifies every real request.
 */
export function getTokenExpiryMs(token: string): number | null {
  try {
    const payload = token.split(".")[1];
    const decoded = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    return typeof decoded.exp === "number" ? decoded.exp * 1000 : null;
  } catch {
    return null;
  }
}

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// A deploy restarts the backend for a few seconds (nginx answers 503 then).
// Reads are retried through that gap; writes are not, since one may have
// reached the server before it went down.
const RESTART_RETRY_DELAYS_MS = [1000, 2000, 4000, 8000];

async function fetchThroughRestarts(url: string, init: RequestInit): Promise<Response> {
  const idempotent = (init.method || "GET").toUpperCase() === "GET";
  for (let attempt = 0; ; attempt++) {
    const delay = RESTART_RETRY_DELAYS_MS[attempt];
    try {
      const response = await fetch(url, init);
      if (!idempotent || delay === undefined || ![502, 503, 504].includes(response.status)) return response;
    } catch (error) {
      if (!idempotent || delay === undefined) throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, delay));
  }
}

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  // FormData bodies must not get a manual Content-Type — the browser sets
  // its own multipart boundary, which we'd otherwise clobber.
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(options.body && !isFormData ? { "Content-Type": "application/json" } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...((options.headers as Record<string, string>) || {}),
  };

  const response = await fetchThroughRestarts(`${BACKEND_URL}${path}`, { ...options, headers });

  // Only a session that stopped working signs the person out. A 401 without
  // one is an answer to sign-in itself ("Invalid email or password"), which
  // the form shows — a redirect would reload the page and lose it.
  if (response.status === 401 && token) {
    clearToken();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new ApiError(401, "Unauthorized");
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.detail || `Request failed: ${response.status}`);
  }

  const data = await response.json();
  // An edit that fixed a misheard name ("Ras" → "Raj") was applied across the
  // whole meeting on the server; whatever page is open reloads its copy.
  if (typeof window !== "undefined" && Array.isArray(data?.learned_corrections) && data.learned_corrections.length) {
    window.dispatchEvent(new CustomEvent<LearnedCorrection[]>(LEARNED_CORRECTIONS_EVENT, { detail: data.learned_corrections }));
  }
  return data;
}

export const LEARNED_CORRECTIONS_EVENT = "charcha:learned-corrections";

export interface RecapResult {
  title: string;
  summary: string;
  action_items: { owner: string; task: string; due: string }[];
  amounts: string[];
  spoken_recap: string;
  transcript: string;
  language?: string | null;
  audio: string | null;
  meeting_id: string | null;
}

/** POSTs JSON and returns the binary response (audio). */
async function apiPostBlob(path: string, body: unknown): Promise<Blob> {
  const token = getToken();
  const response = await fetchThroughRestarts(`${BACKEND_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new ApiError(response.status, detail.detail || `Request failed: ${response.status}`);
  }
  return response.blob();
}

async function apiBlobFetch(path: string): Promise<Blob> {
  const token = getToken();
  const response = await fetchThroughRestarts(`${BACKEND_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.detail || `Request failed: ${response.status}`);
  }
  return response.blob();
}

// --- Types ---

export interface EmailPreferences {
  /** False while the server has no email provider configured. */
  enabled: boolean;
  address: string;
  categories: {
    key: string;
    label: string;
    description: string;
    can_disable: boolean;
    enabled: boolean;
    /** The individual emails in this group, each with its own switch. */
    emails: { key: string; label: string; description: string; enabled: boolean }[];
  }[];
  /** Weekdays are 0 (Monday) to 6 (Sunday); hour is local (IST). */
  schedule: EmailSchedule;
  send_hours: number[];
}

export interface EmailSchedule {
  reminder_days: number[];
  digest_day: number;
  hour: number;
}

export interface EmailPreferencesUpdate {
  categories?: Record<string, boolean>;
  kinds?: Record<string, boolean>;
  schedule?: Partial<EmailSchedule>;
}

export interface AuthResponse {
  token: string;
  email: string;
  name: string | null;
}

export interface VoiceProfileStatus {
  enrolled: boolean;
  available: boolean;
  confirmed_samples: number;
  updated_at: string | null;
}

export interface MeetingSummary {
  id: string;
  title: string;
  date: string;
  duration_minutes: number;
  summary: string | null;
  task_count: number;
  decision_count: number;
  projects: ProjectRef[];
  attendees: MeetingAttendee[];
  source?: MeetingSource | null;
  processing_state?: "ready" | "processing" | "attention";
}

export type MeetingSource = "extension" | "upload" | "paste" | "record" | "bot" | "capture";

/** A transcript quote backing an AI-extracted item. `verified` means the
 * quote was found in that transcript line — not that it proves the claim. */
export interface EvidenceRef {
  segment_id: string;
  seq: number;
  start_ms: number | null;
  end_ms: number | null;
  speaker: string;
  excerpt: string;
  verified: boolean;
}

export interface ProjectRef {
  id: string;
  name: string;
}

export interface MeetingTask {
  id: string;
  owner: string | null;
  description: string;
  deadline: string | null;
  due_date: string | null;
  priority: string | null;
  status: string;
  parent_task_id: string | null;
  project: string | null;
  project_id: string | null;
  verified_at: string | null;
  owner_user_id?: string | null;
  evidence?: EvidenceRef[];
  ai_flags?: string[];
  origin?: "ai" | "manual";
  jira_issue_key?: string | null;
  jira_status?: string | null;
  jira_error?: string | null;
  /** How the owner sees it: "meeting" (they were in it), "shared" (sent to
   * them, task only), "private" (kept from them), "held" (waiting for the
   * recorder or organizer to decide), null (no Charcha account). */
  owner_access?: OwnerAccess | null;
}

export type OwnerAccess = "meeting" | "shared" | "private" | "held";

export interface MeetingDecision {
  id: string;
  decision: string;
  reason: string | null;
  alternatives: string[];
  participants: string[];
  conflict_note: string | null;
  project: string | null;
  project_id: string | null;
  verified_at: string | null;
  evidence?: EvidenceRef[];
  ai_flags?: string[];
  origin?: "ai" | "manual";
}

export interface MeetingRisk {
  id: string;
  description: string;
  severity: string | null;
  project: string | null;
  project_id: string | null;
  verified_at: string | null;
  evidence?: EvidenceRef[];
  ai_flags?: string[];
  origin?: "ai" | "manual";
}

export interface DirectoryUser {
  id: string;
  name: string;
  email: string;
  department: string | null;
  job_title: string | null;
}

/** Someone who was in the meeting. `user_id` is set for a colleague with a
 * Charcha account — that is what grants them access to the meeting. External
 * guests have `user_id: null` and are recorded for the meeting record only. */
export interface MeetingAttendee {
  id: string;
  user_id: string | null;
  name: string;
  email: string | null;
  kind: "internal" | "external";
  source: "manual" | "meet" | "recorder" | "calendar" | "requested" | "shared" | "jira";
  /** granted — can read it; pending — was in the call but not on the invite,
   * waiting for the organizer or an admin to share it; none — external guest. */
  access: "granted" | "pending" | "none";
}

/** What the attendee pickers send up before a person has been resolved to an
 * account: either a picked directory user, or a typed-in external guest. */
export interface AttendeeInput {
  user_id?: string | null;
  name: string;
  email?: string | null;
  access?: "granted" | "pending";
}

/** An attendee as stored on a recording session. Distinct from
 * `MeetingAttendee`: this is a JSON blob on the recording, not a row, so it has
 * no id and no source — it only becomes a row once the recording is linked to a
 * meeting. */
export interface RecordingAttendee {
  user_id: string | null;
  name: string;
  email: string | null;
  kind: "internal" | "external";
}

export interface MeetingDetail {
  id: string;
  title: string;
  date: string;
  duration_minutes: number;
  summary: string | null;
  summary_verified_at: string | null;
  transcript: string | null;
  tasks: MeetingTask[];
  decisions: MeetingDecision[];
  risks: MeetingRisk[];
  insights: MeetingInsights | null;
  recording: MeetingRecording | null;
  projects: ProjectRef[];
  attendees: MeetingAttendee[];
  source: MeetingSource | null;
  template: string;
  transcript_revision: number;
  insights_revision: number | null;
  insights_stale: boolean;
  /** The recorder, the calendar organizer and Charcha admins decide who else may read it. */
  can_manage_access: boolean;
  /** True when the viewer can only see this because they're a Charcha admin. */
  viewing_as_admin: boolean;
  /** Only the people in it can open it — no admin exemption, Jira or public link. */
  confidential?: boolean;
  /** "ai" when the notes AI marked it, "manual" when a person decided. */
  confidential_source?: "ai" | "manual" | null;
  confidential_reason?: string | null;
  can_unmark_confidential?: boolean;
}

export interface SharedMeetingTask {
  description: string;
  owner: string | null;
  deadline: string | null;
  due_date: string | null;
  status: string;
}

export interface SharedMeetingDecision {
  decision: string;
  reason: string | null;
  alternatives: string[] | null;
}

export interface SharedMeetingRisk {
  description: string;
  severity: string | null;
}

export interface SharedMeeting {
  title: string;
  date: string;
  duration_minutes: number;
  /** The AI overview, else the older plain summary. */
  summary: string | null;
  /** Template output, e.g. a stand-up's Updates / Blockers / Plans. */
  template_sections: { heading: string; items: { text: string; person: string | null }[] }[];
  /** The discussion, in the order it happened. */
  sections: { title: string; summary: string }[];
  key_topics: string[];
  highlights: string[];
  next_steps: string[];
  open_questions: string[];
  tasks: SharedMeetingTask[];
  decisions: SharedMeetingDecision[];
  risks: SharedMeetingRisk[];
}

export interface SpeakerActivity {
  speaker: string;
  words: number;
  share: number;
  seconds?: number | null;
}

export interface GroundedItem {
  text?: string;
  /** Who said it (stand-up items). */
  person?: string;
  title?: string;
  summary?: string;
  evidence: EvidenceRef[];
  flags?: string[];
}

export interface MeetingInsights {
  key_topics: string[];
  open_questions: string[];
  highlights: string[];
  next_steps: string[];
  speaker_activity: SpeakerActivity[];
  overview?: string | null;
  sections?: GroundedItem[];
  template_sections?: { heading: string; items: GroundedItem[] }[];
  follow_up_draft?: string | null;
}

export interface MeetingRecording {
  id: string;
  meeting_type: "physical" | "online" | "upload";
  participants: string[];
  duration_seconds: number;
  total_bytes: number;
}

export interface DiarizationTurn {
  speaker: number;
  speaker_name: string;
  start: number;
  end: number;
  text: string;
  confidence: number;
  speaker_confidence: number;
  word_count: number;
}

export interface DiarizationData {
  transcript: string;
  turns: DiarizationTurn[];
  speaker_names: Record<string, string>;
  speaker_corrections: Record<string, number>;
  speaker_activity: Array<SpeakerActivity & { seconds: number }>;
  diagnostics: {
    quality: "good" | "review";
    detected_speakers: number;
    expected_speakers: number | null;
    average_speaker_confidence: number;
    low_confidence_share: number;
    turn_count: number;
  };
  metadata: { request_id: string | null; duration: number | null; diarizer: string };
}

export interface RecordingSession {
  id: string;
  meeting_id: string | null;
  title: string;
  meeting_type: "physical" | "online";
  language: string;
  participants: string[];
  attendees: RecordingAttendee[];
  status: "recording" | "recorded" | "processed";
  duration_seconds: number;
  chunk_count: number;
  total_bytes: number;
  started_at: string;
  ended_at: string | null;
}

export interface RelatedMeeting {
  meeting_id: string;
  meeting_title: string;
  meeting_date: string;
  score: number;
}

export interface TaskUpdateResponse {
  id: string;
  description: string;
  owner: string | null;
  deadline: string | null;
  due_date: string | null;
  priority: string | null;
  status: string;
  parent_task_id: string | null;
  updated_at: string;
  verified_at: string | null;
  jira_issue_key?: string | null;
  jira_status?: string | null;
  jira_error?: string | null;
}

export interface TaskListItem {
  id: string;
  meeting_id: string;
  meeting_title: string;
  meeting_date: string;
  owner: string | null;
  description: string;
  deadline: string | null;
  due_date: string | null;
  priority: string | null;
  status: string;
  parent_task_id: string | null;
  updated_at: string;
  project: string | null;
  project_id: string | null;
  verified_at: string | null;
  jira_issue_key?: string | null;
  jira_status?: string | null;
  jira_error?: string | null;
  created_at?: string | null;
  /** "ai" (from a meeting) or "manual". */
  origin?: string;
  /** You own it (by account, or your name/email as its owner). */
  mine?: boolean;
  /** From a meeting you recorded or organised (or you added it) and owned by
   * someone else: you're waiting on it. */
  delegated?: boolean;
  /** Sent to you from a meeting you weren't in: the task only — no link to the meeting. */
  meeting_hidden?: boolean;
  owner_access?: OwnerAccess | null;
}

export interface JiraStatus {
  connected: boolean;
  site_url: string | null;
}

export interface JiraSettings {
  connected: boolean;
  oauth_available: boolean;
  auth_type?: "oauth" | "token";
  site_url?: string;
  email?: string;
  account_name?: string | null;
  default_project_key?: string;
  project_map?: Record<string, string>;
  auto_send?: "off" | "mapped" | "all";
  last_synced_at?: string | null;
  last_error?: string | null;
}

export interface JiraPeople {
  jira_users: { account_id: string; name: string | null; email: string | null }[];
  people: {
    user_id: string;
    name: string;
    email: string;
    account_id: string | null;
    jira_name: string | null;
    matched_by: "email" | "name" | "manual" | null;
  }[];
}

export interface JiraActivity {
  linked: number;
  open_linked: number;
  problems: { task_id: string; description: string; issue_key: string | null; error: string; meeting_id: string }[];
  recent: {
    task_id: string;
    description: string;
    issue_key: string | null;
    meeting_id: string;
    field: string;
    old_value: string | null;
    new_value: string | null;
    changed_at: string;
  }[];
}

export interface JiraProjects {
  jira: { key: string; name: string }[];
  charcha: { id: string; name: string }[];
}

/** Link to a Jira issue, or null when there's nothing to link to. */
export function jiraIssueUrl(status: JiraStatus | null, key: string | null | undefined): string | null {
  return status?.site_url && key ? `${status.site_url}/browse/${key}` : null;
}

export interface TaskComment {
  id: string;
  body: string;
  author: string;
  /** "jira" when it was written in Jira and synced in. */
  source?: string | null;
  created_at: string;
}

export interface TaskHistoryEntry {
  id: string;
  field: string;
  old_value: string | null;
  new_value: string | null;
  changed_by: string;
  changed_at: string;
}

export interface TaskLinkItem {
  id: string;
  link_type: string;
  linked_task_id: string;
  linked_task_description: string;
  linked_task_status: string;
}

export interface NotificationItem {
  id: string;
  type: string;
  message: string;
  link: string | null;
  read: boolean;
  created_at: string;
}

export interface DecisionListItem {
  id: string;
  meeting_id: string;
  meeting_title: string;
  meeting_date: string;
  decision: string;
  reason: string | null;
  alternatives: string[];
  participants: string[];
  conflict_note: string | null;
  project: string | null;
  project_id: string | null;
  verified_at: string | null;
}

export interface DecisionUpdateResponse {
  id: string;
  decision: string;
  reason: string | null;
  alternatives: string[];
  participants: string[];
  verified_at: string;
}

export interface RiskUpdateResponse {
  id: string;
  description: string;
  severity: string | null;
  verified_at: string;
}

export type RecycleItemType = "meeting" | "project" | "task" | "decision" | "risk";

export interface RecycleBinItem {
  id: string;
  type: RecycleItemType;
  title: string;
  detail: string;
  deleted_at: string;
}

export interface VocabularyEntry {
  id: string;
  /** What transcription writes; null for a keyword. */
  heard_as: string | null;
  /** The right spelling. */
  term: string;
  kind: "keyword" | "correction";
  /** "learned" from someone's edit, "manual" from this page, "suggested"
   * (a Charcha suggestion confirmed or applied after enough meetings), or
   * "auto" (a keyword picked up from projects, Jira or meeting titles). */
  source: "learned" | "manual" | "suggested" | "auto";
  /** Where an auto/suggested entry came from. */
  note: string | null;
  enabled: boolean;
  times_confirmed: number;
  times_applied: number;
  created_by: string | null;
  created_by_id: string | null;
  source_meeting_id: string | null;
  source_meeting_title: string | null;
  created_at: string | null;
}

/** Someone whose name is listened for (Vocabulary → Teammates). */
export interface VocabularyPerson {
  /** Account or added-guest id, or "roster:…"/"guest:…" for derived rows. */
  id: string;
  name: string;
  email: string | null;
  kind: "account" | "added" | "roster" | "guest";
  note: string | null;
  /** For a regular guest: how many of your meetings they were in. */
  meetings: number | null;
  can_delete: boolean;
  heard_as: { id: string; heard_as: string; enabled: boolean; source: string }[];
}

/** A mishearing Charcha noticed by itself, waiting for someone to decide. */
export interface VocabularySuggestion {
  id: string;
  heard_as: string;
  term: string;
  /** "captions": Meet's captions had the real name at the same moment. */
  reason: "attendee" | "captions";
  status: string;
  occurrences: number;
  meetings: number;
  /** Applied without waiting once heard in this many meetings; null = never. */
  auto_apply_at: number | null;
  meeting_id: string | null;
  meeting_title: string | null;
}

/** A misheard term someone's edit fixed; already applied across the meeting. */
export interface LearnedCorrection {
  wrong: string;
  right: string;
}

export interface ProjectSummary {
  id: string;
  name: string;
  department: string | null;
  task_count: number;
  decision_count: number;
  risk_count: number;
  meeting_count: number;
}

export interface ProjectMeetingItem {
  id: string;
  title: string;
  date: string;
  duration_minutes: number;
  summary: string | null;
}

export interface ProjectTaskItem {
  id: string;
  meeting_id: string;
  meeting_title: string;
  meeting_date: string;
  meeting_summary: string | null;
  owner: string | null;
  description: string;
  deadline: string | null;
  priority: string | null;
  status: string;
}

export interface ProjectDecisionItem {
  id: string;
  meeting_id: string;
  meeting_title: string;
  meeting_date: string;
  meeting_summary: string | null;
  decision: string;
  reason: string | null;
  alternatives: string[];
  participants: string[];
  conflict_note: string | null;
}

export interface ProjectRiskItem {
  id: string;
  meeting_id: string;
  meeting_title: string;
  meeting_date: string;
  meeting_summary: string | null;
  description: string;
  severity: string | null;
}

export interface ProjectDetail {
  id: string;
  name: string;
  department: string | null;
  meetings: ProjectMeetingItem[];
  tasks: ProjectTaskItem[];
  decisions: ProjectDecisionItem[];
  risks: ProjectRiskItem[];
}

export interface ChatSegmentRef {
  ref: string;
  seq: number;
  segment_id: string | null;
  start_ms: number | null;
  speaker: string;
  excerpt: string;
}

export interface ChatSource {
  meeting_id?: string | null;
  meeting_title: string;
  meeting_date: string;
  content_type?: string | null;
  tag?: string;
  segments?: ChatSegmentRef[];
}

export interface ChatHistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResponse {
  conversation_id: string;
  answer: string;
  sources: ChatSource[];
}

export interface MemoryConversationSummary {
  id: string;
  title: string;
  meeting_id: string | null;
  updated_at: string;
}

export interface MemoryConversationMessage extends ChatHistoryMessage {
  sources: ChatSource[] | null;
  created_at: string;
}

export interface MemoryConversationDetail {
  id: string;
  title: string;
  meeting_id: string | null;
  scope_meeting_ids?: string[];
  messages: MemoryConversationMessage[];
}

export interface Me {
  id: string;
  email: string;
  name: string | null;
  department: string | null;
  is_admin: boolean;
  role: string;
  status: string;
  team_id: string | null;
  team_name: string | null;
  job_title: string | null;
  auth_method: string;
  /** False for Google accounts that never set a Charcha password. */
  has_password?: boolean;
  created_at: string;
}

export interface AdminOverview {
  total_users: number;
  active_users: number;
  suspended_users: number;
  teams: number;
  meetings: number;
  failed_operations: number;
  last_activity_at: string | null;
  services: { name: string; status: string }[];
}

export interface AdminTeam {
  id: string;
  name: string;
  description: string | null;
  member_count: number;
  created_at: string;
}

export interface AdminAccount {
  id: string;
  email: string;
  name: string | null;
  role: string;
  status: string;
  job_title: string | null;
  team_id: string | null;
  team_name: string | null;
  department: string | null;
  auth_method: string;
  created_at: string;
  last_activity_at: string | null;
}

export interface AdminAuditEvent {
  id: string;
  actor_email: string;
  action: string;
  target_type: string;
  target_id: string;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface GoogleSheetsSettings {
  spreadsheet_id: string | null;
  tasks_tab: string;
  notes_tab: string;
}

export interface Trace {
  id: string;
  meeting_title: string;
  duration_minutes: number;
  transcription_requests: number;
  ai_input_tokens: number;
  ai_output_tokens: number;
  ai_cache_hits: number;
  tasks_found: number;
  decisions_found: number;
  status: string;
  created_at: string;
}

export interface DepartmentUsage {
  department: string;
  meetings_processed: number;
  ai_input_tokens: number;
  ai_output_tokens: number;
  ai_cache_hits: number;
  transcription_requests: number;
  duration_minutes: number;
}

export interface UsageSummary {
  meetings_processed: number;
  ai_input_tokens: number;
  ai_output_tokens: number;
  ai_cache_hits: number;
  transcription_requests: number;
  duration_minutes: number;
  exchange_rate: {
    usd_to_inr: number;
    source: string;
    quoted_at: string | null;
    live: boolean;
    cached: boolean;
  };
  by_department: DepartmentUsage[];
}

export interface ExtractedTask {
  task: string;
  assignedTo: string;
  dueDate: string;
  priority: string;
  project: string;
}

export interface ExtractedDecision {
  decision: string;
  reason: string;
  alternatives: string[];
  participants: string[];
  project: string;
}

export interface ExtractedRisk {
  risk: string;
  severity: string;
  project: string;
}

export interface AIUsage {
  transcription_requests: number;
  duration_minutes: number;
  input_tokens: number;
  output_tokens: number;
  cache_tokens_read: number;
  cache_tokens_written: number;
}

export interface IngestResponse {
  meeting_id: string;
  title: string;
  summary: string;
  tasks: ExtractedTask[];
  decisions: ExtractedDecision[];
  risks: ExtractedRisk[];
  indexing_status: "indexed" | "pending";
  usage: AIUsage;
}

export interface DepartmentChurn {
  department: string;
  total_decisions: number;
  conflicted_decisions: number;
  churn_rate: number;
}

export interface MonthChurn {
  month: string;
  total_decisions: number;
  conflicted_decisions: number;
  churn_rate: number;
}

export interface DecisionChurn {
  total_decisions: number;
  conflicted_decisions: number;
  churn_rate: number;
  by_department: DepartmentChurn[];
  by_month: MonthChurn[];
}

export interface DigestMeeting {
  id: string;
  title: string;
  date: string;
  summary: string | null;
  task_count: number;
  decision_count: number;
}

export interface DigestDecision {
  id: string;
  decision: string;
  meeting_id: string;
  meeting_title: string;
  meeting_date: string;
  conflict_note: string | null;
}

export interface Digest {
  week_start: string;
  week_end: string;
  meetings_count: number;
  tasks_completed: number;
  decisions_made: number;
  contradictions_found: number;
  meetings: DigestMeeting[];
  decisions: DigestDecision[];
}

export interface PolicySource {
  document: string;
  section: string;
  text: string;
  score: number;
}

export interface PolicyAskResponse {
  conversation_id: string;
  answer: string;
  sources: PolicySource[];
}

export interface PolicyConversationSummary {
  id: string;
  title: string;
  updated_at: string;
}

export interface PolicyMessage {
  role: "user" | "assistant";
  content: string;
  sources: PolicySource[] | null;
  created_at: string;
}

export interface PolicyConversationDetail {
  id: string;
  title: string;
  messages: PolicyMessage[];
}

// --- API calls ---

// --- Meeting Assistant ---

export interface AssistantStatus {
  transcription: { configured: boolean; provider: string | null; missing: string | null };
  ai: { configured: boolean; model: string | null; missing: string | null };
  capture: CaptureServiceStatus;
  media_tools: boolean;
  fixture_mode: boolean;
  limits: { max_upload_mb: number; max_upload_minutes: number };
  templates: { id: string; label: string }[];
}

export interface CaptureServiceStatus {
  configured: boolean;
  online: boolean;
  last_seen_at: string | null;
  platforms: string[];
  bot_name: string;
}

export type StageName = "transcription" | "extraction" | "indexing" | "audio" | "diarization";
export type StageStatus = "pending" | "running" | "succeeded" | "failed" | "skipped";

export interface ProcessingStage {
  stage: StageName;
  label: string;
  status: StageStatus;
  attempts: number;
  last_error: string | null;
  detail: Record<string, unknown>;
  started_at: string | null;
  finished_at: string | null;
}

export interface ProcessingStatus {
  meeting_id: string;
  stages: ProcessingStage[];
  active: boolean;
  transcript_revision: number;
  insights_revision: number | null;
  insights_stale: boolean;
  has_transcript: boolean;
}

export interface TranscriptSegment {
  id: string;
  seq: number;
  speaker_key: string;
  speaker: string;
  speaker_named: boolean;
  text: string;
  original_text: string | null;
  start_ms: number | null;
  end_ms: number | null;
  confidence: number | null;
  /** [start_ms, end_ms] per word of the original speech-to-text, when known. */
  word_times?: [number, number][] | null;
  edited: boolean;
  edited_at: string | null;
}

export interface TranscriptSpeaker {
  key: string;
  label: string;
  generic: string;
  named: boolean;
  segment_count: number;
}

export interface TranscriptPage {
  meeting_id: string;
  transcript_revision: number;
  insights_revision: number | null;
  insights_stale: boolean;
  has_timestamps: boolean;
  has_recording: boolean;
  recording_id: string | null;
  can_use_recording_transcript: boolean;
  total: number;
  matched: number;
  offset: number;
  limit: number;
  speakers: TranscriptSpeaker[];
  segments: TranscriptSegment[];
}

export interface SegmentEditResponse extends TranscriptSegment {
  transcript_revision: number;
  insights_stale: boolean;
}

export interface TranscriptEditEntry {
  id: string;
  field: "text" | "speaker" | "source";
  segment_id: string | null;
  seq: number | null;
  old_value: string | null;
  new_value: string | null;
  transcript_revision: number;
  edited_by: string | null;
  created_at: string;
}

export interface MeetingCommentItem {
  id: string;
  body: string;
  segment_id: string | null;
  start_ms: number | null;
  quote: string | null;
  author: string;
  mine: boolean;
  created_at: string;
}

export interface MeetingBookmarkItem {
  id: string;
  label: string;
  segment_id: string | null;
  start_ms: number | null;
  end_ms: number | null;
  author: string;
  mine: boolean;
  created_at: string;
}

export interface RegenerateInsightsResult {
  status: string;
  template: string;
  tasks_added: number;
  decisions_added: number;
  risks_added: number;
  preserved_items: number;
  evidence_checked: number;
  evidence_rejected: number;
}

export interface InsightRunItem {
  id: string;
  status: string;
  template: string;
  model: string;
  prompt_version: string;
  transcript_revision: number;
  chunk_count: number;
  input_tokens: number;
  output_tokens: number;
  evidence_checked: number;
  evidence_rejected: number;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface MeetingAnalytics {
  talk_time: {
    timed: boolean;
    basis: "speaking_seconds" | "words";
    speakers: { speaker_key: string; speaker: string; seconds: number | null; words: number; turns: number; share: number }[];
    total_speaking_seconds: number | null;
    transcript_span_seconds: number | null;
    segment_count: number;
  };
  tasks: { total: number; by_status: Record<string, number> };
  decisions: number;
  risks: number;
  topics: { title: string; start_ms: number | null; segment_count: number }[];
  usage: {
    transcription_requests: number;
    ai_input_tokens: number;
    ai_output_tokens: number;
    insight_runs: number;
    estimated_cost_usd: number | null;
  };
  stage_seconds: Record<string, number | null>;
  notes: string[];
}

export type CaptureStatus =
  | "requested" | "joining" | "waiting_for_admission" | "capturing"
  | "stopped" | "completed" | "denied" | "timed_out" | "failed" | "cancelled";

export interface CaptureRequestItem {
  id: string;
  platform: string;
  meeting_url: string;
  meeting_code: string;
  title: string | null;
  template: string;
  status: CaptureStatus;
  status_label: string;
  status_detail: string | null;
  active: boolean;
  stop_requested: boolean;
  meeting_id: string | null;
  created_at: string | null;
  updated_at: string | null;
  deduplicated?: boolean;
  requested_by_you?: boolean;
  /** Who asked for it, when that wasn't you. */
  requested_by?: string | null;
  /** Whether you get this visit's notes. */
  subscribed?: boolean;
  subscriber_count?: number;
  /** Requests ahead of this one while every notetaker is busy. */
  queue_position?: number;
  /** Set on create: a colleague already had the notetaker on its way. */
  joined_existing?: boolean;
  /** Set on stop: colleagues still want the notes, so it stays. */
  kept_for_others?: boolean;
}

export interface CalendarConnectionInfo {
  google_email: string;
  auto_join: "all" | "organized" | "manual";
  status: "active" | "error";
  last_error: string | null;
  last_synced_at: string | null;
  /** Google pushes changes the moment they happen (else polled every minute). */
  live_updates?: boolean;
  live_updates_error?: string | null;
}

export interface CalendarState {
  configured: boolean;
  connection: CalendarConnectionInfo | null;
}

export interface CalendarEventItem {
  id: string;
  title: string;
  start_at: string;
  end_at: string;
  meeting_url: string | null;
  unsupported_platform: string | null;
  is_organizer: boolean;
  invitee_count: number;
  record_override: boolean | null;
  will_record: boolean;
  /** Other colleagues whose calendars hold the same meeting. */
  colleagues_on_it: number;
  capture: CaptureRequestItem | null;
  /** Written ~10 minutes before the meeting from earlier meetings you can read. */
  brief: PreMeetingBrief | null;
}

export interface ScheduleEvent {
  id: string;
  title: string;
  start_at: string;
  end_at: string;
  when: "past" | "live" | "upcoming";
  meeting_url: string | null;
  /** "Google Meet", "Microsoft Teams", "Webex", "Zoom" — null when unknown. */
  platform: string | null;
  unsupported_platform: string | null;
  is_organizer: boolean;
  organizer_email: string | null;
  recurring: boolean;
  invitee_count: number;
  invitee_names: string[];
  will_record: boolean;
  record_override: boolean | null;
  capture: CaptureRequestItem | null;
  /** The Charcha notes for this meeting, when it was recorded and you can open them. */
  notes: { id: string; title: string } | null;
  brief_ready: boolean;
}

export interface CalendarSchedule {
  connection: CalendarConnectionInfo | null;
  events: ScheduleEvent[];
}

export interface PreMeetingBrief {
  status: "ready" | "failed";
  text: string | null;
  error: string | null;
  meetings: (MeetingPrep["meetings"][number] & { previous_occurrence?: boolean })[];
  open_tasks: MeetingPrep["open_tasks"];
  decisions: MeetingPrep["decisions"];
}

export interface SeriesReviewItem {
  task_id: string;
  description: string;
  owner: string | null;
  status: "done" | "in_progress" | "blocked" | "not_mentioned";
  note: string;
  excerpt: string;
  current_status: string;
}

export interface MeetingSeries {
  series_key: string | null;
  occurrences: { id: string; title: string; date: string; current: boolean }[];
  review: {
    previous_meeting_id: string;
    previous_title: string;
    previous_date: string;
    reviewed_at: string;
    items: SeriesReviewItem[];
  } | null;
}

export interface StandupDigest {
  occurrences: { id: string; title: string; date: string; current: boolean }[];
  people: {
    name: string;
    blocker_count: number;
    occurrences: { meeting_id: string; date: string; updates: string[]; blockers: string[]; plans: string[] }[];
  }[];
  repeated_blockers: { person: string; text: string; times: number; first_date: string; last_date: string; meeting_ids: string[] }[];
}

export interface AiCostGroup {
  key: string | null;
  label?: string;
  calls: number;
  usd: number;
  inr: number;
}

export interface NotetakerVisit {
  id: string;
  title: string;
  meeting_code: string;
  status: string;
  status_label: string;
  status_detail: string | null;
  source: "link" | "calendar" | "invite";
  requested_by: string;
  subscribers: number;
  created_at: string | null;
  claimed_at: string | null;
  scheduled_start: string | null;
  scheduled_end: string | null;
}

export interface NotetakerInstance {
  name: string;
  last_seen_at: string | null;
  online: boolean;
  /** Null for notetakers too old to report it. */
  max_concurrent: number | null;
  active: number | null;
  free: number | null;
  signed_in: boolean | null;
}

export interface NotetakerOverview {
  online: boolean;
  last_heartbeat_at: string | null;
  instances: NotetakerInstance[];
  capacity: { total: number; active: number; free: number; known: boolean };
  live: NotetakerVisit[];
  queued: NotetakerVisit[];
  queue_length: number;
  failures: {
    days: number;
    total: number;
    visits: number;
    groups: { reason: string; label: string; count: number; last_at: string | null; example: string | null }[];
    recent: { id: string; title: string; status: string; reason: string; detail: string | null; at: string | null }[];
  };
}

export interface AiCostReport {
  days: number;
  totals: { calls: number; usd: number; inr: number; input_tokens: number; output_tokens: number; cached_tokens: number; audio_minutes: number };
  by_feature: AiCostGroup[];
  by_model: AiCostGroup[];
  by_user: AiCostGroup[];
  by_day: { day: string; calls: number; usd: number; inr: number }[];
  recent: {
    occurred_at: string;
    feature: string;
    model: string;
    input_tokens: number;
    output_tokens: number;
    audio_seconds: number;
    usd_to_inr: number;
    rate_source: string | null;
    usd: number;
    inr: number;
  }[];
  rate_now: { usd_to_inr: number; source: string; quoted_at: string | null; live: boolean };
  prices: { model_in_use: string; overridden: string[]; source?: string };
}

export interface AdminMeetingRow {
  id: string;
  title: string;
  date: string;
  duration_minutes: number;
  source: string | null;
  owner: string | null;
  with_access: number;
  pending_access: number;
  confidential?: boolean;
  /** False for a confidential meeting the admin wasn't in. */
  can_open?: boolean;
}

export interface MeetingPrep {
  meetings: { tag: string; id: string; title: string; date: string; shared_attendees: number }[];
  open_tasks: {
    id: string; description: string; owner: string | null; status: string;
    due_date: string | null; deadline: string | null; meeting_id: string; meeting_tag: string | null;
  }[];
  decisions: { id: string; decision: string; meeting_id: string; meeting_tag: string | null }[];
  brief: string | null;
  brief_error: string | null;
}

export type TranscriptExportFormat = "txt" | "md" | "json" | "srt" | "vtt";

export const api = {
  getVoiceProfile: () => apiFetch<VoiceProfileStatus>("/api/voice/profile"),
  enrollVoice: (audio: Blob) => {
    const form = new FormData();
    form.append("audio", audio, "voice.webm");
    form.append("consent", "true");
    return apiFetch<{ enrolled: boolean; confirmed_samples: number }>("/api/voice/profile", { method: "POST", body: form });
  },
  deleteVoiceProfile: () => apiFetch<{ enrolled: boolean }>("/api/voice/profile", { method: "DELETE" }),
  confirmVoiceSpeaker: (meetingId: string, speakerKey: string) =>
    apiFetch<{ confirmed: boolean; confirmed_samples: number }>(`/api/voice/confirm/${meetingId}/${encodeURIComponent(speakerKey)}`, { method: "POST" }),
  /** A 90-day token for connecting Claude or another MCP client. */
  createConnectorToken: () =>
    apiFetch<{ token: string; url: string; expires_at: string }>("/api/auth/connector-token", { method: "POST" }),
  /** One spoken turn of Charcha Live: Prisma hears, Gemini answers, Timbre speaks. */
  liveTurn: (audio: Blob, history: { role: string; content: string }[]) => {
    const form = new FormData();
    form.append("audio", audio, audio.type.includes("mp4") ? "turn.m4a" : "turn.webm");
    form.append("history", JSON.stringify(history));
    return apiFetch<{ transcript: string; reply: string | null; audio: string | null; language?: string | null }>(
      "/api/live/turn", { method: "POST", body: form },
    );
  },
  /** Recap of a phone call or WhatsApp voice note, in the language it was spoken in. */
  recapAudio: (file: File, kind: "voice_note" | "call") => {
    const form = new FormData();
    form.append("audio", file, file.name);
    form.append("kind", kind);
    return apiFetch<RecapResult>("/api/recap", { method: "POST", body: form });
  },
  /** Text read aloud by Gnani Timbre, as MP3. */
  speak: (text: string, language?: string) => apiPostBlob("/api/tts", { text, language }),
  /** A short spoken clip (a question) transcribed by Gnani Prisma. */
  transcribeClip: (audio: Blob, language = "hinglish") => {
    const form = new FormData();
    form.append("audio", audio, audio.type.includes("ogg") ? "question.ogg" : audio.type.includes("mp4") ? "question.m4a" : "question.webm");
    form.append("meeting_language", language);
    return apiFetch<{ text: string }>("/api/transcribe", { method: "POST", body: form });
  },
  loginWithGoogle: (googleAccessToken: string) =>
    apiFetch<AuthResponse>("/api/auth/google", {
      method: "POST",
      body: JSON.stringify({ google_access_token: googleAccessToken }),
    }),

  register: (email: string, password: string, name?: string) =>
    apiFetch<AuthResponse>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, name: name || undefined }),
    }),

  loginWithPassword: (email: string, password: string) =>
    apiFetch<AuthResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  refreshToken: () => apiFetch<AuthResponse>("/api/auth/refresh", { method: "POST" }),

  forgotPassword: (email: string) =>
    apiFetch<{ ok: boolean; message: string }>("/api/auth/password/forgot", { method: "POST", body: JSON.stringify({ email }) }),
  resetPassword: (token: string, password: string) =>
    apiFetch<AuthResponse>("/api/auth/password/reset", { method: "POST", body: JSON.stringify({ token, password }) }),
  changePassword: (currentPassword: string | null, newPassword: string) =>
    apiFetch<AuthResponse>("/api/auth/password/change", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),

  getEmailPreferences: () => apiFetch<EmailPreferences>("/api/email/preferences"),
  updateEmailPreferences: (update: EmailPreferencesUpdate) =>
    apiFetch<EmailPreferences>("/api/email/preferences", { method: "PUT", body: JSON.stringify(update) }),
  unsubscribe: (token: string) =>
    apiFetch<{ ok: boolean; category: string; label: string; email: string }>("/api/email/unsubscribe", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),

  getGoogleSheetsSettings: () =>
    apiFetch<GoogleSheetsSettings>("/api/auth/integrations/google-sheets"),

  updateGoogleSheetsSettings: (settings: GoogleSheetsSettings) =>
    apiFetch<GoogleSheetsSettings>("/api/auth/integrations/google-sheets", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),

  listMeetings: (
    q?: string,
    projectId?: string,
    attendeeId?: string,
    filters: { source?: string; dateFrom?: string; dateTo?: string } = {},
  ) => {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (projectId) params.set("project_id", projectId);
    if (attendeeId) params.set("attendee_id", attendeeId);
    if (filters.source) params.set("source", filters.source);
    if (filters.dateFrom) params.set("date_from", filters.dateFrom);
    if (filters.dateTo) params.set("date_to", filters.dateTo);
    const query = params.toString();
    return apiFetch<MeetingSummary[]>(`/api/meetings${query ? `?${query}` : ""}`);
  },

  getMeeting: (id: string) => apiFetch<MeetingDetail>(`/api/meetings/${id}`),

  deleteMeeting: (id: string) =>
    apiFetch<{ ok: boolean }>(`/api/meetings/${id}`, { method: "DELETE" }),

  deleteMeetingRisk: (meetingId: string, riskId: string) =>
    apiFetch<{ ok: boolean }>(`/api/meetings/${meetingId}/risks/${riskId}`, { method: "DELETE" }),

  updateMeetingRisk: (meetingId: string, riskId: string, fields: { description: string; severity?: string }) =>
    apiFetch<RiskUpdateResponse>(`/api/meetings/${meetingId}/risks/${riskId}`, {
      method: "PATCH",
      body: JSON.stringify(fields),
    }),

  getMeetingPdf: (id: string) => apiBlobFetch(`/api/meetings/${id}/export.pdf`),

  copyMeetingShareLink: (id: string) =>
    apiFetch<{ share_token: string }>(`/api/meetings/${id}/share-link`, { method: "POST" }),

  setMeetingConfidential: (id: string, confidential: boolean) =>
    apiFetch<{ confidential: boolean; confidential_source: string | null }>(`/api/meetings/${id}/confidential`, {
      method: "POST",
      body: JSON.stringify({ confidential }),
    }),

  setTaskOwnerAccess: (id: string, action: "send" | "keep_private") =>
    apiFetch<{ id: string; owner_access: OwnerAccess }>(`/api/tasks/${id}/owner-access`, {
      method: "POST",
      body: JSON.stringify({ action }),
    }),

  revokeMeetingShareLink: (id: string) =>
    apiFetch<{ ok: boolean }>(`/api/meetings/${id}/share-link`, { method: "DELETE" }),

  getSharedMeeting: (token: string) => apiFetch<SharedMeeting>(`/api/meetings/shared/${token}`),

  updateMeetingProjects: (id: string, projectIds: string[]) =>
    apiFetch<{ projects: ProjectRef[] }>(`/api/meetings/${id}/projects`, {
      method: "PATCH",
      body: JSON.stringify({ project_ids: projectIds }),
    }),

  updateMeetingTitle: (id: string, title: string) =>
    apiFetch<{ title: string }>(`/api/meetings/${id}/title`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),

  updateMeetingSummary: (id: string, summary: string) =>
    apiFetch<{ summary: string; summary_verified_at: string }>(`/api/meetings/${id}/summary`, {
      method: "PATCH",
      body: JSON.stringify({ summary }),
    }),

  regenerateMeetingSummary: (id: string) =>
    apiFetch<{ summary: string }>(`/api/meetings/${id}/summary/regenerate`, {
      method: "POST",
    }),

  getRelatedMeetings: (id: string) => apiFetch<RelatedMeeting[]>(`/api/meetings/${id}/related`),

  getDirectory: () => apiFetch<DirectoryUser[]>("/api/auth/directory"),

  getMeetingAttendees: (meetingId: string) =>
    apiFetch<MeetingAttendee[]>(`/api/meetings/${meetingId}/attendees`),

  getMeetingSeries: (meetingId: string) => apiFetch<MeetingSeries>(`/api/meetings/${meetingId}/series`),
  getStandupDigest: (meetingId: string) => apiFetch<StandupDigest>(`/api/meetings/${meetingId}/series/standup`),

  setAttendeeAccess: (meetingId: string, attendeeId: string, access: "granted" | "pending") =>
    apiFetch<MeetingAttendee[]>(`/api/meetings/${meetingId}/attendees/${attendeeId}/access`, {
      method: "POST",
      body: JSON.stringify({ access }),
    }),

  shareMeeting: (meetingId: string, userId: string) =>
    apiFetch<MeetingAttendee[]>(`/api/meetings/${meetingId}/share`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    }),

  getCalendar: () => apiFetch<CalendarState>("/api/calendar"),
  connectCalendar: () => apiFetch<{ url: string }>("/api/calendar/connect", { method: "POST" }),
  updateCalendar: (autoJoin: CalendarConnectionInfo["auto_join"]) =>
    apiFetch<CalendarConnectionInfo>("/api/calendar", { method: "PATCH", body: JSON.stringify({ auto_join: autoJoin }) }),
  syncCalendar: () => apiFetch<CalendarConnectionInfo>("/api/calendar/sync", { method: "POST" }),
  disconnectCalendar: () => apiFetch<{ ok: boolean }>("/api/calendar", { method: "DELETE" }),
  listCalendarEvents: (days = 2) => apiFetch<CalendarEventItem[]>(`/api/calendar/events?days=${days}`),
  getCalendarSchedule: (pastDays = 14, futureDays = 7) =>
    apiFetch<CalendarSchedule>(`/api/calendar/schedule?past_days=${pastDays}&future_days=${futureDays}`),
  updateCalendarEvent: (id: string, record: boolean | null) =>
    apiFetch<{ id: string; record_override: boolean | null; will_record: boolean }>(`/api/calendar/events/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ record }),
    }),

  adminAiCosts: (days = 30) => apiFetch<AiCostReport>(`/api/admin/ai-costs?days=${days}`),
  adminNotetaker: () => apiFetch<NotetakerOverview>("/api/admin/notetaker"),

  adminMeetings: (q = "", offset = 0) =>
    apiFetch<{ total: number; meetings: AdminMeetingRow[] }>(
      `/api/admin/meetings?limit=100&offset=${offset}${q ? `&q=${encodeURIComponent(q)}` : ""}`,
    ),

  setMeetingAttendees: (meetingId: string, attendees: AttendeeInput[]) =>
    apiFetch<MeetingAttendee[]>(`/api/meetings/${meetingId}/attendees`, {
      method: "PUT",
      body: JSON.stringify({ attendees }),
    }),

  createRecording: (fields: {
    title: string;
    meetingType: "physical" | "online";
    language: string;
    attendees: AttendeeInput[];
  }) =>
    apiFetch<RecordingSession>("/api/recordings", {
      method: "POST",
      body: JSON.stringify({
        title: fields.title,
        meeting_type: fields.meetingType,
        language: fields.language,
        attendees: fields.attendees,
      }),
    }),

  listActiveRecordings: () => apiFetch<RecordingSession[]>("/api/recordings/active"),

  uploadRecordingChunk: (recordingId: string, chunkIndex: number, chunk: Blob) => {
    const formData = new FormData();
    formData.append("chunk_index", String(chunkIndex));
    formData.append("chunk", chunk, `${String(chunkIndex).padStart(6, "0")}.webm`);
    return apiFetch<{ chunk_index: number; transcript: string }>(
      `/api/recordings/${recordingId}/chunks`,
      { method: "POST", body: formData }
    );
  },

  finalizeRecording: (recordingId: string, durationSeconds: number) =>
    apiFetch<{ recording: RecordingSession; transcript: string }>(
      `/api/recordings/${recordingId}/finalize`,
      { method: "POST", body: JSON.stringify({ duration_seconds: durationSeconds }) }
    ),

  linkRecording: (recordingId: string, meetingId: string) =>
    apiFetch<{ ok: boolean }>(`/api/recordings/${recordingId}/link`, {
      method: "POST",
      body: JSON.stringify({ meeting_id: meetingId }),
    }),

  getRecordingAudio: (recordingId: string) =>
    apiBlobFetch(`/api/recordings/${recordingId}/audio`),

  getRecordingDiarization: (recordingId: string) =>
    apiFetch<DiarizationData>(`/api/recordings/${recordingId}/diarization`),

  rediarizeRecording: (recordingId: string) =>
    apiFetch<DiarizationData>(`/api/recordings/${recordingId}/rediarize`, { method: "POST" }),

  updateSpeakerNames: (recordingId: string, names: Record<string, string>) =>
    apiFetch<DiarizationData>(`/api/recordings/${recordingId}/speakers`, {
      method: "PATCH",
      body: JSON.stringify({ names }),
    }),

  updateSpeakerCorrections: (recordingId: string, corrections: Record<string, number>) =>
    apiFetch<DiarizationData>(`/api/recordings/${recordingId}/speaker-corrections`, {
      method: "PATCH",
      body: JSON.stringify({ corrections }),
    }),

  listTasks: () => apiFetch<TaskListItem[]>("/api/tasks"),

  jiraStatus: () => apiFetch<JiraStatus>("/api/jira/status"),
  sendTaskToJira: (id: string) =>
    apiFetch<{ id: string; jira_issue_key: string; jira_status: string | null }>(`/api/tasks/${id}/jira`, { method: "POST" }),
  sendMeetingTasksToJira: (meetingId: string) =>
    apiFetch<{ created: Record<string, string>; failed: Record<string, string> }>(`/api/meetings/${meetingId}/jira`, { method: "POST" }),
  sendTasksToJira: (taskIds: string[]) =>
    apiFetch<{ created: Record<string, string>; failed: Record<string, string> }>("/api/tasks/jira/bulk", {
      method: "POST",
      body: JSON.stringify({ task_ids: taskIds }),
    }),
  unlinkTaskFromJira: (id: string) => apiFetch<{ id: string; jira_issue_key: null }>(`/api/tasks/${id}/jira`, { method: "DELETE" }),
  adminJiraPeople: () => apiFetch<JiraPeople>("/api/admin/jira/people"),
  setJiraPerson: (userId: string, accountId: string | null) =>
    apiFetch<JiraPeople>(`/api/admin/jira/people/${userId}`, { method: "PUT", body: JSON.stringify({ account_id: accountId }) }),
  resetJiraPerson: (userId: string) => apiFetch<JiraPeople>(`/api/admin/jira/people/${userId}`, { method: "DELETE" }),
  adminJiraActivity: () => apiFetch<JiraActivity>("/api/admin/jira/activity"),
  adminJira: () => apiFetch<JiraSettings>("/api/admin/jira"),
  saveAdminJira: (body: { site_url: string; email: string; api_token?: string; default_project_key: string; project_map: Record<string, string> }) =>
    apiFetch<JiraSettings>("/api/admin/jira", { method: "PUT", body: JSON.stringify(body) }),
  saveAdminJiraProjects: (body: { default_project_key: string; project_map: Record<string, string>; auto_send?: "off" | "mapped" | "all" }) =>
    apiFetch<JiraSettings>("/api/admin/jira/projects", { method: "PUT", body: JSON.stringify(body) }),
  startJiraOAuth: () => apiFetch<{ url: string }>("/api/admin/jira/oauth/start"),
  disconnectAdminJira: () => apiFetch<JiraSettings>("/api/admin/jira", { method: "DELETE" }),
  adminJiraProjects: () => apiFetch<JiraProjects>("/api/admin/jira/projects"),
  syncAdminJira: () => apiFetch<JiraSettings & { changed: number }>("/api/admin/jira/sync", { method: "POST" }),

  createTask: (fields: { description: string; owner?: string; deadline?: string; due_date?: string; priority?: string; parent_task_id?: string }) =>
    apiFetch<TaskListItem>("/api/tasks", {
      method: "POST",
      body: JSON.stringify(fields),
    }),

  deleteTask: (id: string) => apiFetch<{ ok: boolean }>(`/api/tasks/${id}`, { method: "DELETE" }),

  deleteTasks: (ids: string[]) =>
    apiFetch<{ deleted: string[]; failed: Record<string, string> }>("/api/tasks/delete", { method: "POST", body: JSON.stringify({ ids }) }),

  updateTaskStatus: (id: string, status: string) =>
    apiFetch<TaskUpdateResponse>(`/api/tasks/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),

  updateTask: (
    id: string,
    fields: Partial<Pick<TaskListItem, "description" | "owner" | "deadline" | "priority" | "status" | "due_date">> & {
      clear_due_date?: boolean;
    }
  ) =>
    apiFetch<TaskUpdateResponse>(`/api/tasks/${id}`, {
      method: "PATCH",
      body: JSON.stringify(fields),
    }),

  listTaskComments: (taskId: string) => apiFetch<TaskComment[]>(`/api/tasks/${taskId}/comments`),

  addTaskComment: (taskId: string, body: string) =>
    apiFetch<TaskComment>(`/api/tasks/${taskId}/comments`, {
      method: "POST",
      body: JSON.stringify({ body }),
    }),

  getTaskHistory: (taskId: string) => apiFetch<TaskHistoryEntry[]>(`/api/tasks/${taskId}/history`),

  listTaskLinks: (taskId: string) => apiFetch<TaskLinkItem[]>(`/api/tasks/${taskId}/links`),

  createTaskLink: (taskId: string, linkedTaskId: string, linkType: string) =>
    apiFetch<{ ok: boolean }>(`/api/tasks/${taskId}/links`, {
      method: "POST",
      body: JSON.stringify({ linked_task_id: linkedTaskId, link_type: linkType }),
    }),

  deleteTaskLink: (taskId: string, linkId: string) =>
    apiFetch<{ ok: boolean }>(`/api/tasks/${taskId}/links/${linkId}`, { method: "DELETE" }),

  listNotifications: () => apiFetch<NotificationItem[]>("/api/notifications"),

  unreadNotificationCount: () => apiFetch<{ count: number }>("/api/notifications/unread-count"),

  markNotificationRead: (id: string) =>
    apiFetch<NotificationItem>(`/api/notifications/${id}`, { method: "PATCH" }),

  markAllNotificationsRead: () => apiFetch<{ ok: boolean }>("/api/notifications/read-all", { method: "POST" }),

  listDecisions: () => apiFetch<DecisionListItem[]>("/api/decisions"),

  deleteDecision: (id: string) =>
    apiFetch<{ ok: boolean }>(`/api/decisions/${id}`, { method: "DELETE" }),

  updateDecision: (id: string, fields: { decision: string; reason: string; alternatives: string[]; participants: string[] }) =>
    apiFetch<DecisionUpdateResponse>(`/api/decisions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(fields),
    }),

  listVocabulary: () => apiFetch<VocabularyEntry[]>("/api/vocabulary"),

  addVocabulary: (body: { term: string; heard_as?: string[]; fix_past?: boolean }) =>
    apiFetch<VocabularyEntry[]>("/api/vocabulary", { method: "POST", body: JSON.stringify(body) }),

  updateVocabulary: (id: string, body: { enabled?: boolean; term?: string }) =>
    apiFetch<VocabularyEntry>(`/api/vocabulary/${id}`, { method: "PATCH", body: JSON.stringify(body) }),

  deleteVocabulary: (id: string) =>
    apiFetch<{ ok: boolean }>(`/api/vocabulary/${id}`, { method: "DELETE" }),

  listVocabularyPeople: () => apiFetch<VocabularyPerson[]>("/api/vocabulary/people"),

  addVocabularyPerson: (body: { name: string; email?: string; note?: string }) =>
    apiFetch<VocabularyPerson>("/api/vocabulary/people", { method: "POST", body: JSON.stringify(body) }),

  deleteVocabularyPerson: (id: string) =>
    apiFetch<{ ok: boolean }>(`/api/vocabulary/people/${id}`, { method: "DELETE" }),

  listVocabularySuggestions: () => apiFetch<VocabularySuggestion[]>("/api/vocabulary/suggestions"),

  acceptVocabularySuggestion: (id: string, fixPast = true) =>
    apiFetch<VocabularyEntry>(`/api/vocabulary/suggestions/${id}/accept`, { method: "POST", body: JSON.stringify({ fix_past: fixPast }) }),

  dismissVocabularySuggestion: (id: string) =>
    apiFetch<{ ok: boolean }>(`/api/vocabulary/suggestions/${id}/dismiss`, { method: "POST" }),

  listProjects: () => apiFetch<ProjectSummary[]>("/api/projects"),

  createProject: (name: string) =>
    apiFetch<ProjectSummary>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  renameProject: (id: string, name: string) =>
    apiFetch<ProjectRef & { department: string | null }>(`/api/projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),

  deleteProject: (id: string) =>
    apiFetch<{ ok: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),

  getProject: (id: string) => apiFetch<ProjectDetail>(`/api/projects/${id}`),

  listRecycleBin: () => apiFetch<RecycleBinItem[]>("/api/recycle-bin"),

  restoreRecycleItem: (type: RecycleItemType, id: string) =>
    apiFetch<{ ok: boolean }>(`/api/recycle-bin/${type}/${id}/restore`, { method: "POST" }),

  permanentlyDeleteRecycleItem: (type: RecycleItemType, id: string) =>
    apiFetch<{ ok: boolean }>(`/api/recycle-bin/${type}/${id}`, { method: "DELETE" }),

  getDigest: (weekOffset: number = 0) =>
    apiFetch<Digest>(`/api/digest${weekOffset ? `?week_offset=${weekOffset}` : ""}`),

  ingestMeeting: (fields: {
    meetingTitle: string;
    durationMinutes: number;
    transcript: string;
    attendees?: AttendeeInput[];
    template?: string;
    source?: MeetingSource;
  }) => {
    const formData = new FormData();
    formData.append("meeting_title", fields.meetingTitle);
    formData.append("duration_minutes", String(fields.durationMinutes));
    formData.append("transcript", fields.transcript);
    if (fields.attendees?.length) formData.append("attendees", JSON.stringify(fields.attendees));
    if (fields.template) formData.append("template", fields.template);
    if (fields.source) formData.append("source", fields.source);
    return apiFetch<IngestResponse>("/api/meetings/ingest", {
      method: "POST",
      body: formData,
    });
  },

  ingestMeetingAudio: (fields: {
    meetingTitle: string;
    durationMinutes: number;
    audioBlob: Blob;
    fileName?: string;
    meetingLanguage?: string;
  }) => {
    const formData = new FormData();
    formData.append("meeting_title", fields.meetingTitle);
    formData.append("duration_minutes", String(fields.durationMinutes));
    formData.append("meeting_language", fields.meetingLanguage || "hinglish");
    formData.append("audio", fields.audioBlob, fields.fileName || "recording.webm");
    return apiFetch<IngestResponse>("/api/meetings/ingest", {
      method: "POST",
      body: formData,
    });
  },

  chat: (
    query: string,
    meetingId?: string,
    conversationId?: string,
    history: ChatHistoryMessage[] = [],
    meetingIds: string[] = [],
  ) =>
    apiFetch<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        query,
        meeting_id: meetingId ?? null,
        meeting_ids: meetingIds,
        conversation_id: conversationId ?? null,
        history: history.slice(-6),
      }),
    }),

  // --- Meeting Assistant ---

  getAssistantStatus: () => apiFetch<AssistantStatus>("/api/meetings/assistant/status"),

  uploadMeetingRecording: (fields: {
    file: File;
    title: string;
    language: string;
    template: string;
    consentAcknowledged: boolean;
    idempotencyKey: string;
    attendees?: AttendeeInput[];
  }) => {
    const formData = new FormData();
    formData.append("file", fields.file, fields.file.name);
    formData.append("title", fields.title);
    formData.append("language", fields.language);
    formData.append("template", fields.template);
    formData.append("consent_acknowledged", String(fields.consentAcknowledged));
    formData.append("idempotency_key", fields.idempotencyKey);
    if (fields.attendees?.length) formData.append("attendees", JSON.stringify(fields.attendees));
    return apiFetch<{ meeting_id: string; status: string; deduplicated: boolean }>("/api/meetings/upload", {
      method: "POST",
      body: formData,
    });
  },

  getProcessing: (meetingId: string) => apiFetch<ProcessingStatus>(`/api/meetings/${meetingId}/processing`),

  retryStage: (meetingId: string, stage: StageName) =>
    apiFetch<{ ok: boolean }>(`/api/meetings/${meetingId}/processing/${stage}/retry`, { method: "POST" }),

  getTranscript: (meetingId: string, params: { q?: string; speaker?: string; offset?: number; limit?: number } = {}) => {
    const search = new URLSearchParams();
    if (params.q) search.set("q", params.q);
    if (params.speaker !== undefined) search.set("speaker", params.speaker);
    if (params.offset) search.set("offset", String(params.offset));
    if (params.limit) search.set("limit", String(params.limit));
    const query = search.toString();
    return apiFetch<TranscriptPage>(`/api/meetings/${meetingId}/transcript${query ? `?${query}` : ""}`);
  },

  editTranscriptSegment: (meetingId: string, segmentId: string, text: string) =>
    apiFetch<SegmentEditResponse>(`/api/meetings/${meetingId}/transcript/segments/${segmentId}`, {
      method: "PATCH",
      body: JSON.stringify({ text }),
    }),

  revertTranscriptSegment: (meetingId: string, segmentId: string) =>
    apiFetch<SegmentEditResponse>(`/api/meetings/${meetingId}/transcript/segments/${segmentId}/revert`, { method: "POST" }),

  renameTranscriptSpeakers: (meetingId: string, names: Record<string, string>) =>
    apiFetch<{ changed: number; transcript_revision: number; insights_stale?: boolean }>(
      `/api/meetings/${meetingId}/transcript/speakers`,
      { method: "PUT", body: JSON.stringify({ names }) },
    ),

  getTranscriptHistory: (meetingId: string) =>
    apiFetch<TranscriptEditEntry[]>(`/api/meetings/${meetingId}/transcript/history`),

  useRecordingTranscript: (meetingId: string) =>
    apiFetch<{ segments: number; transcript_revision: number }>(`/api/meetings/${meetingId}/transcript/use-recording`, {
      method: "POST",
    }),

  exportTranscript: (meetingId: string, format: TranscriptExportFormat) =>
    apiBlobFetch(`/api/meetings/${meetingId}/transcript/export?format=${format}`),

  regenerateInsights: (meetingId: string, template?: string) =>
    apiFetch<RegenerateInsightsResult>(`/api/meetings/${meetingId}/insights/regenerate`, {
      method: "POST",
      body: JSON.stringify({ template: template ?? null }),
    }),

  listInsightRuns: (meetingId: string) => apiFetch<InsightRunItem[]>(`/api/meetings/${meetingId}/insights/runs`),

  getMeetingAnalytics: (meetingId: string) => apiFetch<MeetingAnalytics>(`/api/meetings/${meetingId}/analytics`),

  listMeetingComments: (meetingId: string) => apiFetch<MeetingCommentItem[]>(`/api/meetings/${meetingId}/comments`),

  addMeetingComment: (meetingId: string, body: string, segmentId?: string | null) =>
    apiFetch<MeetingCommentItem>(`/api/meetings/${meetingId}/comments`, {
      method: "POST",
      body: JSON.stringify({ body, segment_id: segmentId ?? null }),
    }),

  deleteMeetingComment: (meetingId: string, commentId: string) =>
    apiFetch<{ ok: boolean }>(`/api/meetings/${meetingId}/comments/${commentId}`, { method: "DELETE" }),

  listMeetingBookmarks: (meetingId: string) => apiFetch<MeetingBookmarkItem[]>(`/api/meetings/${meetingId}/bookmarks`),

  addMeetingBookmark: (
    meetingId: string,
    fields: { label: string; segment_id?: string | null; start_ms?: number | null; end_ms?: number | null },
  ) =>
    apiFetch<MeetingBookmarkItem>(`/api/meetings/${meetingId}/bookmarks`, {
      method: "POST",
      body: JSON.stringify(fields),
    }),

  deleteMeetingBookmark: (meetingId: string, bookmarkId: string) =>
    apiFetch<{ ok: boolean }>(`/api/meetings/${meetingId}/bookmarks/${bookmarkId}`, { method: "DELETE" }),

  meetingPrep: (attendeeUserIds: string[], agenda: string) =>
    apiFetch<MeetingPrep>("/api/meetings/prep", {
      method: "POST",
      body: JSON.stringify({ attendee_user_ids: attendeeUserIds, agenda, include_brief: true }),
    }),

  getCaptureStatus: () => apiFetch<CaptureServiceStatus>("/api/capture/status"),

  createCaptureRequest: (fields: {
    meetingUrl: string;
    title: string;
    template: string;
    consentAcknowledged: boolean;
    idempotencyKey: string;
  }) =>
    apiFetch<CaptureRequestItem>("/api/capture/requests", {
      method: "POST",
      body: JSON.stringify({
        meeting_url: fields.meetingUrl,
        title: fields.title,
        template: fields.template,
        consent_acknowledged: fields.consentAcknowledged,
        idempotency_key: fields.idempotencyKey,
      }),
    }),

  listCaptureRequests: () => apiFetch<CaptureRequestItem[]>("/api/capture/requests"),

  stopCaptureRequest: (id: string) =>
    apiFetch<CaptureRequestItem>(`/api/capture/requests/${id}/stop`, { method: "POST" }),

  listMemoryConversations: () =>
    apiFetch<MemoryConversationSummary[]>("/api/chat/conversations"),

  getMemoryConversation: (id: string) =>
    apiFetch<MemoryConversationDetail>(`/api/chat/conversations/${id}`),

  deleteMemoryConversation: (id: string) =>
    apiFetch<{ ok: boolean }>(`/api/chat/conversations/${id}`, { method: "DELETE" }),

  getMe: () => apiFetch<Me>("/api/auth/me"),

  updateDepartment: (department: string) =>
    apiFetch<Me>("/api/auth/me", {
      method: "PATCH",
      body: JSON.stringify({ department }),
    }),

  adminTraces: () => apiFetch<Trace[]>("/api/admin/traces"),

  adminUsageSummary: () => apiFetch<UsageSummary>("/api/admin/usage-summary"),

  adminDecisionChurn: () => apiFetch<DecisionChurn>("/api/admin/decision-churn"),

  adminOverview: () => apiFetch<AdminOverview>("/api/admin/overview"),
  adminAccounts: () => apiFetch<AdminAccount[]>("/api/admin/accounts"),
  adminCreateAccount: (body: Record<string, unknown>) =>
    apiFetch<AdminAccount>("/api/admin/accounts", { method: "POST", body: JSON.stringify(body) }),
  adminUpdateAccount: (id: string, body: Record<string, unknown>) =>
    apiFetch<AdminAccount>(`/api/admin/accounts/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  adminTeams: () => apiFetch<AdminTeam[]>("/api/admin/teams"),
  adminCreateTeam: (body: { name: string; description?: string }) =>
    apiFetch<AdminTeam>("/api/admin/teams", { method: "POST", body: JSON.stringify(body) }),
  adminUpdateTeam: (id: string, body: { name: string; description?: string }) =>
    apiFetch<AdminTeam>(`/api/admin/teams/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  adminDeleteTeam: (id: string) =>
    apiFetch<{ ok: boolean }>(`/api/admin/teams/${id}`, { method: "DELETE" }),
  adminAuditEvents: () => apiFetch<AdminAuditEvent[]>("/api/admin/audit-events"),

  askPolicy: (query: string, conversationId?: string) =>
    apiFetch<PolicyAskResponse>("/api/policy-chat/ask", {
      method: "POST",
      body: JSON.stringify({ query, conversation_id: conversationId ?? null }),
    }),

  listPolicyConversations: () =>
    apiFetch<PolicyConversationSummary[]>("/api/policy-chat/conversations"),

  getPolicyConversation: (id: string) =>
    apiFetch<PolicyConversationDetail>(`/api/policy-chat/conversations/${id}`),

  deletePolicyConversation: (id: string) =>
    apiFetch<{ ok: boolean }>(`/api/policy-chat/conversations/${id}`, { method: "DELETE" }),
};

export { ApiError };
