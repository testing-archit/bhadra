"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api, LEARNED_CORRECTIONS_EVENT, LearnedCorrection, MeetingDetail, RelatedMeeting, ApiError, DiarizationData, ProjectSummary, EvidenceRef, AssistantStatus } from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ProcessingPanel } from "@/components/meeting/processing-panel";
import { TranscriptWorkspace, TranscriptFocus } from "@/components/meeting/transcript-workspace";
import { EvidenceChips } from "@/components/meeting/evidence-chips";
import { GuidedReview } from "@/components/meeting/guided-review";
import { AskAiPanel } from "@/components/meeting/ask-ai-panel";
import { AnalyticsPanel } from "@/components/meeting/analytics-panel";
import { ResolvedCitation } from "@/components/cited-markdown";
import { formatClock } from "@/lib/media-time";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { MeetingAttendees } from "@/components/meeting-attendees";
import { SeriesPanel } from "@/components/meeting/series-panel";
import { FollowUpDraft } from "@/components/meeting/follow-up-draft";
import { ConfidentialNotice, MarkConfidentialButton } from "@/components/meeting/confidential-banner";
import { TaskOwnerAccess } from "@/components/meeting/task-owner-access";
import { StandupDigestPanel } from "@/components/meeting/standup-digest";
import { TaskEditDialog, EditableTask } from "@/components/task-edit-dialog";
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog";
import { DecisionReviewDialog, RiskReviewDialog, SummaryReviewDialog } from "@/components/record-review-dialogs";
import { VerificationBadge } from "@/components/verification-badge";
import { JiraTaskButton, useJiraStatus } from "@/components/jira-task-button";
import { FormattedSummary } from "@/components/formatted-summary";
import { SpeakButton } from "@/components/speak-button";
import { ProjectNameEditor } from "@/components/project-name-editor";
import {
  ArrowLeft,
  CalendarDays,
  Clock,
  ListChecks,
  Scale,
  FileText,
  NotebookText,
  Pencil,
  Plus,
  AlertTriangle,
  Link2,
  ShieldAlert,
  FolderKanban,
  Download,
  AudioLines,
  CircleHelp,
  Lightbulb,
  Tags,
  TrendingUp,
  RefreshCw,
  Save,
  Users,
  Trash2,
  Share2,
  Check,
  MessagesSquare,
  Sparkles,
  BarChart3,
  ShieldCheck,
  Send,
} from "lucide-react";
import { SOURCE_LABELS } from "@/lib/labels";

import { STATUS_LABELS } from "@/lib/labels";
type TabId = "summary" | "transcript" | "actions" | "ask" | "insights";
const TAB_IDS: TabId[] = ["summary", "transcript", "actions", "ask", "insights"];
type DeleteTarget = {
  type: "meeting" | "task" | "decision" | "risk";
  id: string;
  label: string;
};

function ProjectBadge({ project, projectId }: { project: string | null; projectId: string | null }) {
  if (!project) return null;
  const badge = (
    <Badge variant="outline" className="gap-1 hover:bg-accent">
      <FolderKanban className="h-3 w-3" />
      {project}
    </Badge>
  );
  return projectId ? <Link href={`/projects/${projectId}`}>{badge}</Link> : badge;
}

export default function MeetingDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [meeting, setMeeting] = useState<MeetingDetail | null>(null);
  const [related, setRelated] = useState<RelatedMeeting[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editingTask, setEditingTask] = useState<EditableTask | null>(null);
  const jira = useJiraStatus();
  const [jiraBusy, setJiraBusy] = useState(false);
  const [jiraError, setJiraError] = useState<string | null>(null);
  const [editingDecision, setEditingDecision] = useState<MeetingDetail["decisions"][number] | null>(null);
  const [editingRisk, setEditingRisk] = useState<MeetingDetail["risks"][number] | null>(null);
  const [summaryEditing, setSummaryEditing] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [diarization, setDiarization] = useState<DiarizationData | null>(null);
  const [speakerNames, setSpeakerNames] = useState<Record<string, string>>({});
  const [speakerCorrections, setSpeakerCorrections] = useState<Record<string, number>>({});
  const [diarizationBusy, setDiarizationBusy] = useState(false);
  const [diarizationError, setDiarizationError] = useState<string | null>(null);
  const [allProjects, setAllProjects] = useState<ProjectSummary[]>([]);
  const [selectedProjects, setSelectedProjects] = useState<string[]>([]);
  const [projectsSaving, setProjectsSaving] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [projectCreating, setProjectCreating] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [titleEditing, setTitleEditing] = useState(false);
  const [titleSaving, setTitleSaving] = useState(false);
  const [summaryBusy, setSummaryBusy] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [shareBusy, setShareBusy] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);
  const [shareError, setShareError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [deleting, setDeleting] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [tab, setTab] = useState<TabId>("summary");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [currentMs, setCurrentMs] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  // Stable, so the transcript's per-frame word highlighting isn't restarted
  // every time the player reports its position.
  const getPlaybackMs = useCallback(() => (audioRef.current ? audioRef.current.currentTime * 1000 : null), []);
  const [focus, setFocus] = useState<TranscriptFocus | null>(null);
  const [assistantStatus, setAssistantStatus] = useState<AssistantStatus | null>(null);
  const [templateChoice, setTemplateChoice] = useState<string>("");
  const [insightsBusy, setInsightsBusy] = useState(false);
  const [insightsMessage, setInsightsMessage] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [transcriptKey, setTranscriptKey] = useState(0);
  const [learnedNotice, setLearnedNotice] = useState<string | null>(null);
  const stopAtMs = useRef<number | null>(null);
  const pendingSeekMs = useRef<number | null>(null);

  const reloadMeeting = useCallback(() => {
    return api
      .getMeeting(id)
      .then((result) => {
        setMeeting(result);
        setTitleDraft(result.title);
        setSelectedProjects(result.projects.map((project) => project.id));
        setTemplateChoice((current) => current || result.template);
        setRefreshKey((key) => key + 1);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load meeting"));
  }, [id]);

  useEffect(() => {
    void reloadMeeting();
  }, [reloadMeeting]);

  useEffect(() => {
    api.getAssistantStatus().then(setAssistantStatus).catch(() => setAssistantStatus(null));
  }, []);

  // Deep links from citations elsewhere: ?tab=transcript&segment=<id>&t=<ms>
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requested = params.get("tab") as TabId | null;
    if (requested && TAB_IDS.includes(requested)) { setTab(requested); setDetailsOpen(true); }
    const segment = params.get("segment");
    if (segment) {
      setDetailsOpen(true);
      setTab("transcript");
      setFocus({ segmentId: segment, nonce: Date.now() });
    }
    const t = Number(params.get("t"));
    if (params.get("t") !== null && Number.isFinite(t)) pendingSeekMs.current = t;
  }, []);

  function seekTo(ms: number, play = true) {
    const audio = audioRef.current;
    if (!audio) return;
    stopAtMs.current = null;
    audio.currentTime = ms / 1000;
    setCurrentMs(ms);
    if (play) void audio.play();
  }

  function playRange(startMs: number, endMs: number | null) {
    seekTo(startMs);
    stopAtMs.current = endMs !== null && endMs > startMs ? endMs : null;
  }

  function openEvidence(ref: EvidenceRef) {
    setDetailsOpen(true);
    setTab("transcript");
    setFocus({ segmentId: ref.segment_id, nonce: Date.now() });
    if (ref.start_ms !== null && audioUrl) seekTo(ref.start_ms);
  }

  function openCitation(citation: ResolvedCitation) {
    setDetailsOpen(true);
    const segment = citation.segment;
    if (!segment?.segment_id) {
      setTab("summary");
      return;
    }
    setTab("transcript");
    setFocus({ segmentId: segment.segment_id, nonce: Date.now() });
    if (segment.start_ms !== null && audioUrl) seekTo(segment.start_ms);
  }

  async function regenerateInsights() {
    if (!meeting) return;
    setInsightsBusy(true);
    setInsightsMessage(null);
    try {
      const result = await api.regenerateInsights(id, templateChoice || meeting.template);
      setInsightsMessage(
        `Notes regenerated: ${result.tasks_added} new task${result.tasks_added === 1 ? "" : "s"}, ${result.decisions_added} decision${result.decisions_added === 1 ? "" : "s"}.` +
          (result.preserved_items ? ` ${result.preserved_items} reviewed item${result.preserved_items === 1 ? " was" : "s were"} kept as is.` : ""),
      );
      await reloadMeeting();
    } catch (cause) {
      setInsightsMessage(cause instanceof ApiError ? cause.message : "Notes could not be regenerated");
    } finally {
      setInsightsBusy(false);
    }
  }

  useEffect(() => {
    api.listProjects().then(setAllProjects).catch(() => setAllProjects([]));
  }, []);

  // Fixing a misheard name in any item fixes it across the meeting (and
  // teaches Wilco for next time): show everything with the fix applied.
  useEffect(() => {
    function onLearned(event: Event) {
      const fixes = (event as CustomEvent<LearnedCorrection[]>).detail;
      setLearnedNotice(`Also fixed ${fixes.map((fix) => `“${fix.wrong}” → “${fix.right}”`).join(", ")} everywhere in this meeting. Wilco will get it right in future meetings too.`);
      setTranscriptKey((key) => key + 1);
      void reloadMeeting();
    }
    window.addEventListener(LEARNED_CORRECTIONS_EVENT, onLearned);
    return () => window.removeEventListener(LEARNED_CORRECTIONS_EVENT, onLearned);
  }, [reloadMeeting]);

  async function saveMeetingProjects() {
    setProjectsSaving(true);
    try {
      const result = await api.updateMeetingProjects(id, selectedProjects);
      setMeeting((current) => current ? { ...current, projects: result.projects } : current);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Project assignment failed");
    } finally {
      setProjectsSaving(false);
    }
  }

  // A new project is created and assigned to this meeting in one step.
  async function createAndAssignProject() {
    const name = newProjectName.trim();
    if (!name) return;
    setProjectCreating(true);
    try {
      const project = await api.createProject(name);
      setAllProjects((current) => [...current, project].sort((a, b) => a.name.localeCompare(b.name)));
      const next = [...new Set([...selectedProjects, project.id])];
      setSelectedProjects(next);
      const result = await api.updateMeetingProjects(id, next);
      setMeeting((current) => current ? { ...current, projects: result.projects } : current);
      setNewProjectName("");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Project could not be created");
    } finally {
      setProjectCreating(false);
    }
  }

  // The name is shown on this meeting's projects and on every tagged item.
  function projectRenamed(projectId: string, name: string) {
    setAllProjects((current) => current.map((project) => project.id === projectId ? { ...project, name } : project).sort((a, b) => a.name.localeCompare(b.name)));
    setMeeting((current) => current ? {
      ...current,
      projects: current.projects.map((project) => project.id === projectId ? { ...project, name } : project),
      tasks: current.tasks.map((item) => item.project_id === projectId ? { ...item, project: name } : item),
      decisions: current.decisions.map((item) => item.project_id === projectId ? { ...item, project: name } : item),
      risks: current.risks.map((item) => item.project_id === projectId ? { ...item, project: name } : item),
    } : current);
  }

  async function saveMeetingTitle() {
    const nextTitle = titleDraft.trim();
    if (!nextTitle || !meeting) return;
    setTitleSaving(true);
    setError(null);
    try {
      const result = await api.updateMeetingTitle(id, nextTitle);
      setMeeting({ ...meeting, title: result.title });
      setTitleDraft(result.title);
      setTitleEditing(false);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Meeting title could not be saved");
    } finally {
      setTitleSaving(false);
    }
  }

  async function regenerateSummary() {
    if (!meeting) return;
    setSummaryBusy(true);
    setSummaryError(null);
    try {
      const result = await api.regenerateMeetingSummary(id);
      setMeeting({ ...meeting, summary: result.summary, summary_verified_at: null });
    } catch (cause) {
      setSummaryError(cause instanceof ApiError ? cause.message : "Detailed summary could not be generated");
    } finally {
      setSummaryBusy(false);
    }
  }

  // Keyed on the recording's id, not the object: the meeting reloads after
  // every edit, and refetching would re-download the audio and restart the
  // player mid-listen.
  const recordingId = meeting?.recording?.id ?? null;

  useEffect(() => {
    if (!recordingId) return;
    let url: string | null = null;
    let cancelled = false;
    api.getRecordingAudio(recordingId).then((blob) => {
      if (cancelled) return;
      url = URL.createObjectURL(blob);
      setAudioUrl(url);
    }).catch(() => !cancelled && setAudioUrl(null));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [recordingId]);

  useEffect(() => {
    if (!recordingId) return;
    let cancelled = false;
    api.getRecordingDiarization(recordingId).then((result) => {
      if (cancelled) return;
      setDiarization(result);
      setSpeakerNames(result.speaker_names);
      setSpeakerCorrections(result.speaker_corrections);
    }).catch(() => !cancelled && setDiarization(null));
    return () => {
      cancelled = true;
    };
  }, [recordingId]);

  async function reanalyzeSpeakers() {
    if (!meeting?.recording) return;
    setDiarizationBusy(true);
    setDiarizationError(null);
    try {
      const result = await api.rediarizeRecording(meeting.recording.id);
      setDiarization(result);
      setSpeakerNames(result.speaker_names);
      setSpeakerCorrections(result.speaker_corrections);
      setMeeting(await api.getMeeting(id));
    } catch (cause) {
      setDiarizationError(cause instanceof ApiError ? cause.message : "Speaker re-analysis failed.");
    } finally {
      setDiarizationBusy(false);
    }
  }

  async function saveSpeakerNames() {
    if (!meeting?.recording) return;
    setDiarizationBusy(true);
    setDiarizationError(null);
    try {
      const result = await api.updateSpeakerNames(meeting.recording.id, speakerNames);
      setDiarization(result);
      setSpeakerNames(result.speaker_names);
      setSpeakerCorrections(result.speaker_corrections);
      setMeeting(await api.getMeeting(id));
    } catch (cause) {
      setDiarizationError(cause instanceof ApiError ? cause.message : "Speaker names could not be saved.");
    } finally {
      setDiarizationBusy(false);
    }
  }

  async function saveSpeakerCorrections() {
    if (!meeting?.recording) return;
    setDiarizationBusy(true);
    setDiarizationError(null);
    try {
      const result = await api.updateSpeakerCorrections(meeting.recording.id, speakerCorrections);
      setDiarization(result);
      setSpeakerCorrections(result.speaker_corrections);
      setMeeting(await api.getMeeting(id));
    } catch (cause) {
      setDiarizationError(cause instanceof ApiError ? cause.message : "Turn corrections could not be saved.");
    } finally {
      setDiarizationBusy(false);
    }
  }

  // Fetched separately from the main meeting load — this hits Qdrant and
  // shouldn't hold up the rest of the page rendering. Guarded against races
  // if `id` changes again before the previous fetch resolves.
  useEffect(() => {
    let cancelled = false;
    api
      .getRelatedMeetings(id)
      .then((r) => {
        if (!cancelled) setRelated(r);
      })
      .catch(() => {
        if (!cancelled) setRelated([]);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  function patchMeetingTask(taskId: string, fields: Partial<MeetingDetail["tasks"][number]>) {
    setMeeting((prev) => (prev ? { ...prev, tasks: prev.tasks.map((t) => (t.id === taskId ? { ...t, ...fields } : t)) } : prev));
  }

  const unsentTasks = meeting ? meeting.tasks.filter((t) => !t.jira_issue_key && t.status !== "done").length : 0;

  async function sendAllToJira() {
    setJiraBusy(true);
    setJiraError(null);
    try {
      const { created, failed } = await api.sendMeetingTasksToJira(id);
      setMeeting((prev) =>
        prev ? { ...prev, tasks: prev.tasks.map((t) => (created[t.id] ? { ...t, jira_issue_key: created[t.id], jira_error: null } : t)) } : prev
      );
      const failures = Object.values(failed ?? {});
      if (failures.length) setJiraError(`${failures.length} task${failures.length === 1 ? "" : "s"} couldn't be sent: ${failures[0]}`);
    } catch (cause) {
      setJiraError(cause instanceof ApiError ? cause.message : "Couldn't send the tasks to Jira");
      // Some may have been created before the error: show them.
      api.getMeeting(id).then(setMeeting).catch(() => undefined);
    } finally {
      setJiraBusy(false);
    }
  }

  async function saveTaskEdits(fields: {
    description: string;
    owner: string;
    deadline: string;
    due_date: string;
    priority: string;
    status: string;
  }) {
    if (!editingTask) return;
    const { due_date, ...rest } = fields;
    const updated = await api.updateTask(editingTask.id, {
      ...rest,
      ...(due_date ? { due_date } : { clear_due_date: true }),
    });
    setMeeting((prev) =>
      prev
        ? {
            ...prev,
            tasks: prev.tasks.map((t) =>
              t.id === updated.id
                ? {
                    ...t,
                    description: updated.description,
                    owner: updated.owner,
                    deadline: updated.deadline,
                    due_date: updated.due_date,
                    priority: updated.priority,
                  status: updated.status,
                  verified_at: updated.verified_at,
                  }
                : t
            ),
          }
        : prev
    );
  }

  async function saveDecisionEdits(fields: { decision: string; reason: string; alternatives: string[]; participants: string[] }) {
    if (!editingDecision) return;
    const updated = await api.updateDecision(editingDecision.id, fields);
    setMeeting((current) => current ? { ...current, decisions: current.decisions.map((item) => item.id === updated.id ? { ...item, ...updated } : item) } : current);
  }

  async function saveRiskEdits(fields: { description: string; severity: string }) {
    if (!editingRisk) return;
    const updated = await api.updateMeetingRisk(id, editingRisk.id, fields);
    setMeeting((current) => current ? { ...current, risks: current.risks.map((item) => item.id === updated.id ? { ...item, ...updated } : item) } : current);
  }

  async function saveSummary(summary: string) {
    const updated = await api.updateMeetingSummary(id, summary);
    setMeeting((current) => current ? { ...current, ...updated } : current);
  }

  async function exportMeeting() {
    if (!meeting) return;
    setExportBusy(true);
    setExportError(null);
    try {
      const blob = await api.getMeetingPdf(id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${meeting.title.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase() || "meeting"}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
    } catch (cause) {
      setExportError(cause instanceof ApiError ? cause.message : "PDF export failed");
    } finally {
      setExportBusy(false);
    }
  }

  async function copyShareLink() {
    setShareBusy(true);
    setShareError(null);
    try {
      const { share_token } = await api.copyMeetingShareLink(id);
      const url = `${window.location.origin}/shared/${share_token}`;
      await navigator.clipboard.writeText(url);
      setShareCopied(true);
      window.setTimeout(() => setShareCopied(false), 2_000);
    } catch (cause) {
      setShareError(cause instanceof ApiError ? cause.message : "Could not create the share link");
    } finally {
      setShareBusy(false);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget || !meeting) return;
    setDeleting(true);
    setError(null);
    try {
      if (deleteTarget.type === "meeting") {
        await api.deleteMeeting(id);
        router.push("/meetings");
        router.refresh();
        return;
      }
      if (deleteTarget.type === "task") {
        await api.deleteTask(deleteTarget.id);
        setMeeting({ ...meeting, tasks: meeting.tasks.filter((item) => item.id !== deleteTarget.id) });
      } else if (deleteTarget.type === "decision") {
        await api.deleteDecision(deleteTarget.id);
        setMeeting({ ...meeting, decisions: meeting.decisions.filter((item) => item.id !== deleteTarget.id) });
      } else {
        await api.deleteMeetingRisk(id, deleteTarget.id);
        setMeeting({ ...meeting, risks: meeting.risks.filter((item) => item.id !== deleteTarget.id) });
      }
      setDeleteTarget(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The record could not be deleted");
    } finally {
      setDeleting(false);
    }
  }

  const deleteDescription = deleteTarget?.type === "meeting"
    ? "This meeting and its Company Memory search data will move to the Recycle Bin. You can restore it from Settings until it is permanently deleted."
    : `“${deleteTarget?.label ?? ""}” will move to the Recycle Bin and disappear from Company Memory search. The meeting and transcript will remain.`;

  if (error) return <p className="text-sm text-destructive">{error}</p>;

  if (!meeting) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const insights = meeting.insights;
  const templates = assistantStatus?.templates ?? [];

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <Link
            href="/meetings"
            className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground hover:underline"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to meetings
          </Link>
          {meeting.viewing_as_admin && (
            <p className="mt-3 flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-sm">
              <ShieldCheck className="size-4 shrink-0 text-primary" />
              You weren&apos;t in this meeting. You can see it because you&apos;re a Wilco admin.
            </p>
          )}
          <ConfidentialNotice meeting={meeting} onChanged={() => void reloadMeeting()} />
          {titleEditing ? (
            <div className="mt-2 flex max-w-xl items-center gap-2">
              <Input value={titleDraft} onChange={(event) => setTitleDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void saveMeetingTitle(); if (event.key === "Escape") { setTitleDraft(meeting.title); setTitleEditing(false); } }} maxLength={160} autoFocus aria-label="Meeting title" />
              <Button size="icon" onClick={() => void saveMeetingTitle()} disabled={titleSaving || !titleDraft.trim()} title="Save meeting title"><Save className="h-4 w-4" /></Button>
            </div>
          ) : (
            <div className="mt-2 flex items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight">{meeting.title}</h1>
              <Button variant="ghost" size="icon" onClick={() => setTitleEditing(true)} title="Edit meeting title"><Pencil className="h-4 w-4" /></Button>
            </div>
          )}
          <p className="mt-1 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
            <span className="flex items-center gap-1">
              <CalendarDays className="h-3.5 w-3.5" />
              {new Date(meeting.date).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" })}
            </span>
            <span className="flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" />
              {meeting.duration_minutes} min
            </span>
            {meeting.source && <span>{SOURCE_LABELS[meeting.source] ?? meeting.source}</span>}
            {meeting.attendees.length > 0 && (
              <span className="flex items-center gap-1">
                <Users className="h-3.5 w-3.5" />
                {meeting.attendees.length} attendee{meeting.attendees.length === 1 ? "" : "s"}
              </span>
            )}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <MarkConfidentialButton meeting={meeting} onChanged={() => void reloadMeeting()} />
          {meeting.can_manage_access && !meeting.confidential && (
            <Button variant="outline" size="sm" onClick={() => void copyShareLink()} disabled={shareBusy} title="Copy an external, no-login link to this meeting's summary">
              {shareCopied ? <Check className="h-4 w-4" /> : <Share2 className="h-4 w-4" />}
              {shareCopied ? "Link copied" : shareBusy ? "Creating link" : "Copy share link"}
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => void exportMeeting()} disabled={exportBusy} title="Export branded meeting PDF">
            <Download className="h-4 w-4" />
            {exportBusy ? "Preparing PDF" : "Export PDF"}
          </Button>
          {meeting.can_manage_access && (
            <Button variant="outline" size="sm" className="text-destructive hover:text-destructive" onClick={() => setDeleteTarget({ type: "meeting", id, label: meeting.title })}>
              <Trash2 className="h-4 w-4" /> Delete meeting
            </Button>
          )}
        </div>
      </div>
      {exportError && <p className="text-sm text-destructive">{exportError}</p>}
      {shareError && <p className="text-sm text-destructive">{shareError}</p>}


      <ProcessingPanel meetingId={id} onSettled={() => void reloadMeeting()} />

      {meeting.recording && (
        <div className="sticky top-3 z-30 -mx-1 rounded-lg border bg-background/95 px-3 py-2 shadow-sm backdrop-blur">
          {audioUrl ? (
            <div className="flex flex-wrap items-center gap-3">
              <AudioLines className="h-4 w-4 shrink-0 text-primary" />
              <audio
                ref={audioRef}
                controls
                preload="metadata"
                src={audioUrl}
                className="h-9 min-w-0 flex-1"
                onTimeUpdate={(event) => {
                  const ms = event.currentTarget.currentTime * 1000;
                  setCurrentMs(ms);
                  if (stopAtMs.current !== null && ms >= stopAtMs.current) {
                    event.currentTarget.pause();
                    stopAtMs.current = null;
                  }
                }}
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
                onEnded={() => setPlaying(false)}
                onLoadedMetadata={() => {
                  if (pendingSeekMs.current !== null) {
                    seekTo(pendingSeekMs.current, false);
                    pendingSeekMs.current = null;
                  }
                }}
              />
              <span className="font-mono text-xs text-muted-foreground tabular-nums">{formatClock(currentMs ?? 0)}</span>
              <a href={audioUrl} download={`${meeting.title}.webm`} className="inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium hover:bg-accent">
                <Download className="h-3.5 w-3.5" /> Audio
              </a>
            </div>
          ) : (
            <Skeleton className="h-9 w-full" />
          )}
        </div>
      )}

      <GuidedReview
        meeting={meeting}
        onChanged={reloadMeeting}
        onEvidence={openEvidence}
        onShare={() => void copyShareLink()}
        shareBusy={shareBusy}
        shareCopied={shareCopied}
        onOpenFullMeeting={() => setDetailsOpen(true)}
      />

      <details className="meeting-details" open={detailsOpen} onToggle={(event) => setDetailsOpen(event.currentTarget.open)}>
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-xl border px-5 py-4 text-sm font-medium focus-visible:outline-2 focus-visible:outline-ring">
          Full meeting <span className="text-xs font-normal text-muted-foreground">{detailsOpen ? "Close details −" : "Transcript, notes & insights +"}</span>
        </summary>
      <Tabs className="pt-5" value={tab} onValueChange={(value) => setTab(value as TabId)}>
        <TabsList className="h-auto! w-full flex-wrap justify-start sm:w-fit">
          <TabsTrigger value="summary"><NotebookText /> Summary</TabsTrigger>
          <TabsTrigger value="transcript"><FileText /> Transcript</TabsTrigger>
          <TabsTrigger value="actions"><ListChecks /> Action items ({meeting.tasks.length + meeting.decisions.length + meeting.risks.length})</TabsTrigger>
          <TabsTrigger value="ask"><MessagesSquare /> Ask Wilco</TabsTrigger>
          <TabsTrigger value="insights"><BarChart3 /> Insights</TabsTrigger>
        </TabsList>

        {learnedNotice && (
          <p className="mt-3 flex items-start gap-2 rounded-lg border border-primary/30 bg-accent/40 px-3 py-2 text-sm">
            <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <span className="flex-1">{learnedNotice} <Link href="/vocabulary" className="underline underline-offset-2">Vocabulary</Link></span>
            <button type="button" className="text-muted-foreground hover:text-foreground" onClick={() => setLearnedNotice(null)} aria-label="Dismiss">×</button>
          </p>
        )}

        <TabsContent value="summary" className="flex flex-col gap-4 pt-3">
          <div className="flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2">
            {meeting.insights_stale ? (
              <p className="flex items-center gap-1.5 text-sm text-foreground">
                <AlertTriangle className="h-4 w-4" /> The transcript was corrected after these notes were generated.
              </p>
            ) : (
              <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                <Sparkles className="h-4 w-4 text-primary" /> AI notes from transcript revision {meeting.insights_revision ?? meeting.transcript_revision}
              </p>
            )}
            <div className="ml-auto flex items-center gap-2">
              {templates.length > 0 && (
                <select
                  aria-label="Notes template"
                  value={templateChoice || meeting.template}
                  onChange={(event) => setTemplateChoice(event.target.value)}
                  className="h-8 rounded-md border bg-background px-2 text-sm"
                >
                  {templates.map((template) => <option key={template.id} value={template.id}>{template.label}</option>)}
                </select>
              )}
              <Button size="sm" variant={meeting.insights_stale ? "default" : "outline"} onClick={() => void regenerateInsights()} disabled={insightsBusy || !meeting.transcript || assistantStatus?.ai.configured === false} title={assistantStatus?.ai.configured === false ? "AI notes are not set up on this server" : "Regenerate notes from the current transcript. Items you reviewed or edited are kept."}>
                <RefreshCw className={`h-3.5 w-3.5 ${insightsBusy ? "animate-spin" : ""}`} />
                {insightsBusy ? "Generating" : "Regenerate notes"}
              </Button>
            </div>
            {insightsMessage && <p className="w-full text-xs text-muted-foreground">{insightsMessage}</p>}
          </div>

          {insights?.overview && (
            <p className="rounded-lg bg-muted/40 px-4 py-3 text-sm leading-relaxed">{insights.overview}</p>
          )}

          <Card>
              <CardHeader className="flex-row items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2"><CardTitle className="flex items-center gap-2 text-base"><NotebookText className="h-4 w-4 text-primary" /> Detailed summary</CardTitle><VerificationBadge verifiedAt={meeting.summary_verified_at} /></div>
                <div className="flex gap-2">{meeting.summary && <SpeakButton text={meeting.summary} />}<Button size="sm" variant="outline" onClick={() => setSummaryEditing(true)}><Pencil className="h-3.5 w-3.5" /> Review</Button><Button size="sm" variant="outline" onClick={() => void regenerateSummary()} disabled={summaryBusy} title="Generate detailed summary again"><RefreshCw className={`h-3.5 w-3.5 ${summaryBusy ? "animate-spin" : ""}`} /> {summaryBusy ? "Generating" : "Regenerate"}</Button></div>
              </CardHeader>
              <CardContent>
                {meeting.summary ? <FormattedSummary summary={meeting.summary} /> : <p className="text-sm text-muted-foreground">No summary is available yet.</p>}
                {summaryError && <p className="mt-3 text-sm text-destructive">{summaryError}</p>}
              </CardContent>
            </Card>

          <Card>
            <CardHeader className="flex-row items-center justify-between gap-3">
              <CardTitle className="flex items-center gap-2 text-base"><ListChecks className="h-4 w-4 text-primary" /> Tasks ({meeting.tasks.length})</CardTitle>
              {meeting.tasks.length > 0 && (
                <Button size="sm" variant="outline" onClick={() => setTab("actions")}>All action items</Button>
              )}
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {meeting.tasks.length === 0 && <p className="text-sm text-muted-foreground">No tasks extracted from this meeting.</p>}
              {meeting.tasks.map((task, i) => (
                <div key={task.id}>
                  {i > 0 && <Separator className="mb-3" />}
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm">{task.description}</p>
                      <p className="text-xs text-muted-foreground">
                        {task.owner || "Owner not stated"}
                        {task.deadline && ` · due ${task.deadline}`}
                        {` · ${(STATUS_LABELS[task.status] ?? task.status)}`}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <ProjectBadge project={task.project} projectId={task.project_id} />
                      {task.priority && <Badge variant={task.priority === "High" ? "destructive" : task.priority === "Medium" ? "default" : "secondary"}>{task.priority}</Badge>}
                      <Button variant="ghost" size="icon-sm" onClick={() => setEditingTask(task)} aria-label="Edit task"><Pencil className="h-3.5 w-3.5" /></Button>
                    </div>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>


          {insights?.sections && insights.sections.length > 0 && (
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Clock className="h-4 w-4 text-primary" /> Discussion, in order</CardTitle></CardHeader>
              <CardContent className="flex flex-col gap-3">
                {insights.sections.map((section, index) => (
                  <div key={`${section.title}-${index}`}>
                    <p className="text-sm font-medium">{section.title}</p>
                    {section.summary && <p className="text-sm text-muted-foreground">{section.summary}</p>}
                    <EvidenceChips evidence={section.evidence} flags={section.flags} onOpen={openEvidence} />
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {insights?.template_sections && insights.template_sections.length > 0 && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {insights.template_sections.map((block) => (
                <Card key={block.heading}>
                  <CardHeader><CardTitle className="text-base">{block.heading}</CardTitle></CardHeader>
                  <CardContent className="flex flex-col gap-2.5">
                    {block.items.map((item, index) => (
                      <div key={index}>
                        <p className="text-sm">{item.person && <span className="font-medium">{item.person}: </span>}{item.text}</p>
                        <EvidenceChips evidence={item.evidence} flags={item.flags} onOpen={openEvidence} />
                      </div>
                    ))}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {meeting.insights && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <Card>
                <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Tags className="h-4 w-4 text-primary" /> Key topics</CardTitle></CardHeader>
                <CardContent className="flex flex-wrap gap-2">
                  {meeting.insights.key_topics.length ? meeting.insights.key_topics.map((topic) => <Badge key={topic} variant="secondary">{topic}</Badge>) : <p className="text-sm text-muted-foreground">No topics identified.</p>}
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Lightbulb className="h-4 w-4 text-primary" /> Highlights</CardTitle></CardHeader>
                <CardContent className="flex flex-col gap-2">
                  {meeting.insights.highlights.length ? meeting.insights.highlights.map((item) => <p key={item} className="text-sm">• {item}</p>) : <p className="text-sm text-muted-foreground">No highlights identified.</p>}
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className="flex items-center gap-2 text-base"><CircleHelp className="h-4 w-4 text-primary" /> Open questions</CardTitle></CardHeader>
                <CardContent className="flex flex-col gap-2">
                  {meeting.insights.open_questions.length ? meeting.insights.open_questions.map((item) => <p key={item} className="text-sm">• {item}</p>) : <p className="text-sm text-muted-foreground">No open questions.</p>}
                </CardContent>
              </Card>
              {/* The AI's next steps restate the tasks as text that edits never
                  reach; once there are tasks, the Tasks card above is the list. */}
              {meeting.tasks.length === 0 && <Card>
                <CardHeader><CardTitle className="flex items-center gap-2 text-base"><TrendingUp className="h-4 w-4 text-primary" /> Next steps</CardTitle></CardHeader>
                <CardContent className="flex flex-col gap-2">
                  {meeting.insights.next_steps.length ? meeting.insights.next_steps.map((item, index) => <p key={item} className="text-sm"><span className="mr-2 text-muted-foreground">{index + 1}.</span>{item}</p>) : <p className="text-sm text-muted-foreground">No next steps identified.</p>}
                </CardContent>
              </Card>}
            </div>
          )}


          {insights?.follow_up_draft && (
            <FollowUpDraft draft={insights.follow_up_draft} title={meeting.title} attendees={meeting.attendees ?? []} tasks={meeting.tasks} decisions={meeting.decisions} />
          )}

          <SeriesPanel meetingId={meeting.id} />

          {meeting.template === "standup" && <StandupDigestPanel meetingId={meeting.id} />}

          <MeetingAttendees
            meetingId={meeting.id}
            attendees={meeting.attendees ?? []}
            canManage={meeting.can_manage_access}
            onChange={(attendees) => setMeeting((current) => (current ? { ...current, attendees } : current))}
          />


          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <CardTitle className="flex items-center gap-2 text-base"><FolderKanban className="h-4 w-4 text-primary" /> Projects</CardTitle>
                  <p className="mt-1 text-sm text-muted-foreground">Tick the projects this meeting belongs to, or rename one with the pencil. A project can contain many meetings.</p>
                </div>
                <Button size="sm" onClick={saveMeetingProjects} disabled={projectsSaving}>{projectsSaving ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />} Save projects</Button>
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {allProjects.length === 0 ? <p className="text-sm text-muted-foreground">No projects exist yet. Create one below, or they appear when named initiatives are extracted from meeting outcomes.</p> : (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {allProjects.map((project) => (
                    <div key={project.id} className="flex min-w-0 items-center gap-2 rounded-md border px-3 py-2 text-sm">
                      <Checkbox aria-label={`Assign ${project.name}`} checked={selectedProjects.includes(project.id)} onCheckedChange={(checked) => setSelectedProjects((current) => checked === true ? [...new Set([...current, project.id])] : current.filter((id) => id !== project.id))} />
                      <ProjectNameEditor projectId={project.id} name={project.name} onRenamed={(name) => projectRenamed(project.id, name)} className="flex-1" />
                    </div>
                  ))}
                </div>
              )}
              <div className="flex max-w-md items-center gap-2">
                <Input value={newProjectName} onChange={(event) => setNewProjectName(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void createAndAssignProject(); }} placeholder="New project name" aria-label="New project name" maxLength={120} className="h-8" />
                <Button size="sm" variant="outline" onClick={() => void createAndAssignProject()} disabled={projectCreating || !newProjectName.trim()}><Plus className="h-3.5 w-3.5" /> Add to meeting</Button>
              </div>
            </CardContent>
          </Card>

        </TabsContent>

        <TabsContent value="transcript" className="pt-3">
          {meeting.transcript || meeting.recording ? (
            <TranscriptWorkspace
              key={transcriptKey}
              meetingId={id}
              attendees={meeting.attendees}
              currentMs={audioUrl ? currentMs : null}
              playing={!!audioUrl && playing}
              getPlaybackMs={getPlaybackMs}
              canPlay={!!audioUrl}
              focus={focus}
              onSeek={(ms) => seekTo(ms)}
              onPlayRange={playRange}
              onTranscriptChanged={() => void reloadMeeting()}
            />
          ) : (
            <p className="text-sm text-muted-foreground">This meeting has no transcript yet.</p>
          )}
        </TabsContent>

        <TabsContent value="actions" className="flex flex-col gap-4 pt-3">
          <p className="text-xs text-muted-foreground">
            Extracted items start as AI suggestions. Editing or reviewing one marks it human-verified, and regenerating notes never overwrites it. Owners and deadlines appear only when someone actually stated them.
          </p>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <ListChecks className="h-4 w-4 text-primary" />
                Tasks ({meeting.tasks.length})
                {jira?.connected && unsentTasks > 0 && !meeting.confidential && (
                  <Button variant="outline" size="xs" className="ml-auto" disabled={jiraBusy} onClick={() => void sendAllToJira()}>
                    <Send />
                    {jiraBusy ? "Sending…" : `Send ${unsentTasks} open task${unsentTasks === 1 ? "" : "s"} to Jira`}
                  </Button>
                )}
              </CardTitle>
              {jiraError && <p className="text-xs text-destructive">{jiraError}</p>}
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {meeting.tasks.length === 0 && (
                <p className="text-sm text-muted-foreground">No tasks extracted from this meeting.</p>
              )}
              {meeting.tasks.map((task, i) => (
                <div key={task.id}>
                  {i > 0 && <Separator className="mb-3" />}
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm">{task.description}</p>
                        <VerificationBadge verifiedAt={task.verified_at} />
                        {!meeting.confidential && (
                          <JiraTaskButton
                            taskId={task.id}
                            issueKey={task.jira_issue_key}
                            issueStatus={task.jira_status}
                            issueError={task.jira_error}
                            jira={jira}
                            onSent={(key, status) => patchMeetingTask(task.id, { jira_issue_key: key, jira_status: status })}
                          />
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {task.owner || "Owner not stated"}
                        {task.deadline && ` · due ${task.deadline}`}
                        {` · ${(STATUS_LABELS[task.status] ?? task.status)}`}
                        {task.owner && !task.owner_user_id && meeting.attendees.some((person) => person.user_id) && " · not matched to an attendee"}
                      </p>
                      <TaskOwnerAccess
                        task={task}
                        canManage={meeting.can_manage_access}
                        onChanged={(access) => patchMeetingTask(task.id, { owner_access: access })}
                      />
                      <EvidenceChips evidence={task.evidence} flags={task.ai_flags} onOpen={openEvidence} />
                    </div>
                    <div className="flex items-center gap-2">
                      <ProjectBadge project={task.project} projectId={task.project_id} />
                      {task.priority && (
                        <Badge
                          variant={
                            task.priority === "High"
                              ? "destructive"
                              : task.priority === "Medium"
                              ? "default"
                              : "secondary"
                          }
                        >
                          {task.priority}
                        </Badge>
                      )}
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => setEditingTask(task)}
                        aria-label="Edit task"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon-sm" className="text-muted-foreground hover:text-destructive" onClick={() => setDeleteTarget({ type: "task", id: task.id, label: task.description })} aria-label="Delete task">
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>


          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Scale className="h-4 w-4 text-primary" />
                Decisions ({meeting.decisions.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {meeting.decisions.length === 0 && (
                <p className="text-sm text-muted-foreground">No decisions captured from this meeting.</p>
              )}
              {meeting.decisions.map((decision, i) => (
                <div key={decision.id}>
                  {i > 0 && <Separator className="mb-3" />}
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-2"><p className="text-sm font-medium">{decision.decision}</p><VerificationBadge verifiedAt={decision.verified_at} /></div>
                    <div className="flex items-center gap-2">
                      <ProjectBadge project={decision.project} projectId={decision.project_id} />
                      <Button variant="ghost" size="icon-sm" onClick={() => setEditingDecision(decision)} aria-label="Review decision"><Pencil className="h-3.5 w-3.5" /></Button>
                      <Button variant="ghost" size="icon-sm" className="text-muted-foreground hover:text-destructive" onClick={() => setDeleteTarget({ type: "decision", id: decision.id, label: decision.decision })} aria-label="Delete decision">
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                  {decision.reason && (
                    <p className="text-sm text-muted-foreground">{decision.reason}</p>
                  )}
                  <EvidenceChips evidence={decision.evidence} flags={decision.ai_flags} onOpen={openEvidence} />
                  {(decision.alternatives ?? []).length > 0 && (
                    <p className="text-xs text-muted-foreground">
                      Rejected: {(decision.alternatives ?? []).join(", ")}
                    </p>
                  )}
                  {decision.conflict_note && (
                    <div className="mt-2 flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
                      <p className="text-xs text-foreground">
                        {decision.conflict_note}
                      </p>
                    </div>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>


          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <ShieldAlert className="h-4 w-4 text-primary" />
                Risks ({meeting.risks.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {meeting.risks.length === 0 && (
                <p className="text-sm text-muted-foreground">No risks flagged in this meeting.</p>
              )}
              {meeting.risks.map((risk, i) => (
                <div key={risk.id}>
                  {i > 0 && <Separator className="mb-3" />}
                  <div className="flex items-start justify-between gap-3">
                    <div><div className="flex flex-wrap items-center gap-2"><p className="text-sm">{risk.description}</p><VerificationBadge verifiedAt={risk.verified_at} /></div><EvidenceChips evidence={risk.evidence} flags={risk.ai_flags} onOpen={openEvidence} /></div>
                    <div className="flex shrink-0 items-center gap-2">
                      <ProjectBadge project={risk.project} projectId={risk.project_id} />
                      {risk.severity && (
                        <Badge
                          variant={
                            risk.severity === "High"
                              ? "destructive"
                              : risk.severity === "Medium"
                              ? "default"
                              : "secondary"
                          }
                        >
                          {risk.severity}
                        </Badge>
                      )}
                      <Button variant="ghost" size="icon-sm" onClick={() => setEditingRisk(risk)} aria-label="Review risk"><Pencil className="h-3.5 w-3.5" /></Button>
                      <Button variant="ghost" size="icon-sm" className="text-muted-foreground hover:text-destructive" onClick={() => setDeleteTarget({ type: "risk", id: risk.id, label: risk.description })} aria-label="Delete risk">
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

        </TabsContent>

        <TabsContent value="ask" className="pt-3">
          {assistantStatus?.ai.configured === false ? (
            <p className="text-sm text-muted-foreground">Setup required: AI answers are not configured on this server ({assistantStatus.ai.missing}).</p>
          ) : (
            <AskAiPanel meetingId={id} onCite={openCitation} />
          )}
        </TabsContent>

        <TabsContent value="insights" className="flex flex-col gap-4 pt-3">
          <AnalyticsPanel meetingId={id} refreshKey={refreshKey} onSeek={(ms) => seekTo(ms)} />
          {diarization && meeting.recording && (
            <Card>
              <CardHeader>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <CardTitle className="flex items-center gap-2 text-base"><Users className="h-4 w-4 text-primary" /> Speaker diarization</CardTitle>
                  <div className="flex gap-2">
                    <Button size="sm" variant="outline" onClick={reanalyzeSpeakers} disabled={diarizationBusy}>
                      <RefreshCw className={`h-3.5 w-3.5 ${diarizationBusy ? "animate-spin" : ""}`} /> Re-analyze
                    </Button>
                    <Button size="sm" onClick={saveSpeakerNames} disabled={diarizationBusy}>
                      <Save className="h-3.5 w-3.5" /> Save names
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-5">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
                  <div><p className="text-xs text-muted-foreground">Quality</p><Badge className="mt-1" variant={diarization.diagnostics.quality === "good" ? "secondary" : "destructive"}>{diarization.diagnostics.quality === "good" ? "Good" : "Needs review"}</Badge></div>
                  <div><p className="text-xs text-muted-foreground">Detected</p><p className="mt-1 text-sm font-medium">{diarization.diagnostics.detected_speakers} speakers</p></div>
                  <div><p className="text-xs text-muted-foreground">Expected</p><p className="mt-1 text-sm font-medium">{diarization.diagnostics.expected_speakers ?? "Not set"}</p></div>
                  <div><p className="text-xs text-muted-foreground">Confidence</p><p className="mt-1 text-sm font-medium">{Math.round(diarization.diagnostics.average_speaker_confidence * 100)}%</p></div>
                </div>
                <Separator />
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {Array.from(new Set(diarization.turns.map((turn) => turn.speaker))).map((speakerId) => {
                    const turns = diarization.turns.filter((turn) => turn.speaker === speakerId);
                    const confidence = turns.reduce((sum, turn) => sum + turn.speaker_confidence * turn.word_count, 0) / Math.max(1, turns.reduce((sum, turn) => sum + turn.word_count, 0));
                    const speakingSeconds = turns.reduce((sum, turn) => sum + Math.max(0, turn.end - turn.start), 0);
                    return (
                      <div key={speakerId} className="rounded-md border p-3">
                        <div className="flex items-center justify-between gap-2">
                          <label htmlFor={`speaker-${speakerId}`} className="text-xs font-medium text-muted-foreground">Speaker {speakerId + 1}</label>
                          <span className="text-xs text-muted-foreground">{Math.round(confidence * 100)}% · {Math.round(speakingSeconds)}s</span>
                        </div>
                        <select id={`speaker-${speakerId}`} className="mt-2 h-9 w-full rounded-md border bg-background px-3 text-sm" value={speakerNames[String(speakerId)] || ""} onChange={(event) => setSpeakerNames((current) => ({ ...current, [String(speakerId)]: event.target.value }))}>
                          <option value="">Select teammate</option>
                          {(meeting.attendees ?? []).map((person) => <option key={person.id} value={person.name}>{person.name}</option>)}
                        </select>
                      </div>
                    );
                  })}
                </div>
                {diarization.diagnostics.low_confidence_share > 0.2 && <p className="text-xs text-foreground">{Math.round(diarization.diagnostics.low_confidence_share * 100)}% of words have low speaker confidence. Review the highlighted turns before relying on speaker attribution.</p>}
                {diarizationError && <p className="text-sm text-destructive">{diarizationError}</p>}
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-medium">Turn-by-turn review</p>
                  <Button size="sm" variant="outline" onClick={saveSpeakerCorrections} disabled={diarizationBusy}><Save className="h-3.5 w-3.5" /> Save turn fixes</Button>
                </div>
                <details>
                  <summary className="cursor-pointer text-sm font-medium">Review timestamped turns ({diarization.turns.length})</summary>
                  <div className="mt-3 max-h-80 space-y-2 overflow-y-auto pr-2">
                    {diarization.turns.map((turn, index) => (
                      <div key={`${turn.start}-${index}`} className={`rounded-md border p-3 ${turn.speaker_confidence < 0.62 ? "border-warning/40 bg-warning/5" : ""}`}>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <button type="button" onClick={() => seekTo(turn.start * 1000)} className="text-xs font-medium hover:underline">{Math.floor(turn.start / 60)}:{String(Math.floor(turn.start % 60)).padStart(2, "0")} · {Math.round(turn.speaker_confidence * 100)}% · Play</button>
                          <select value={speakerCorrections[String(index)] ?? turn.speaker} onChange={(event) => setSpeakerCorrections((current) => ({ ...current, [String(index)]: Number(event.target.value) }))} className="h-8 rounded-md border bg-background px-2 text-xs">
                            {Array.from(new Set([
                              ...diarization.turns.map((item) => item.speaker),
                              ...Object.keys(speakerNames).map(Number),
                            ])).sort((a, b) => a - b).map((speakerId) => <option key={speakerId} value={speakerId}>{speakerNames[String(speakerId)] || `Speaker ${speakerId + 1}`}</option>)}
                          </select>
                        </div>
                        <p className="mt-1 text-sm text-muted-foreground">{turn.text}</p>
                      </div>
                    ))}
                  </div>
                </details>
              </CardContent>
            </Card>
          )}


          {related && related.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Link2 className="h-4 w-4 text-primary" />
                  Related past discussions
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {related.map((r) => (
                  <Link
                    key={r.meeting_id}
                    href={`/meetings/${r.meeting_id}`}
                    className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-sm hover:bg-accent"
                  >
                    <span>{r.meeting_title}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {new Date(r.meeting_date).toLocaleDateString()}
                    </span>
                  </Link>
                ))}
              </CardContent>
            </Card>
          )}

        </TabsContent>
      </Tabs>
      </details>

      {editingTask && (
        <TaskEditDialog
          task={editingTask}
          open={!!editingTask}
          onOpenChange={(open) => !open && setEditingTask(null)}
          onSave={saveTaskEdits}
          onJiraChange={(fields) => patchMeetingTask(editingTask.id, fields)}
        />
      )}
      {editingDecision && <DecisionReviewDialog open={!!editingDecision} value={editingDecision} onOpenChange={(open) => !open && setEditingDecision(null)} onSave={saveDecisionEdits} />}
      {editingRisk && <RiskReviewDialog open={!!editingRisk} value={editingRisk} onOpenChange={(open) => !open && setEditingRisk(null)} onSave={saveRiskEdits} />}
      {summaryEditing && <SummaryReviewDialog open={summaryEditing} summary={meeting.summary || ""} onOpenChange={setSummaryEditing} onSave={saveSummary} />}
      <DeleteConfirmationDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && !deleting && setDeleteTarget(null)}
        title={deleteTarget?.type === "meeting" ? `Delete “${meeting.title}”?` : `Delete this ${deleteTarget?.type ?? "record"}?`}
        description={deleteDescription}
        confirmLabel="Move to Recycle Bin"
        busy={deleting}
        onConfirm={confirmDelete}
      />
    </div>
  );
}
