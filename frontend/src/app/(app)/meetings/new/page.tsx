"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, ApiError, AssistantStatus } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { useShell } from "@/components/shell/shell-context";
import { newIdempotencyKey } from "@/lib/media-time";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  AlertTriangle,
  Bot,
  FileText,
  Loader2,
  Mic,
  Sparkles,
  Upload,
} from "lucide-react";

type Source = "upload" | "paste";
const SOURCES: Source[] = ["upload", "paste"];
const LANGUAGES: Record<string, string> = { hinglish: "Hinglish", en: "English", hi: "Hindi", auto: "Auto-detect" };
const ACCEPT = ".mp3,.wav,.m4a,.mp4,.webm,audio/mpeg,audio/wav,audio/x-wav,audio/mp4,audio/x-m4a,audio/webm,video/mp4,video/webm";

function SetupRequired({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/5 px-3 py-2 text-sm text-foreground">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div>{children}</div>
    </div>
  );
}

function TemplateSelect({ status, value, onChange, id }: { status: AssistantStatus | null; value: string; onChange: (value: string) => void; id: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>Notes template</Label>
      <select id={id} value={value} onChange={(event) => onChange(event.target.value)} className="h-9 rounded-md border bg-background px-3 text-sm">
        {(status?.templates ?? [{ id: "general", label: "General meeting" }]).map((template) => (
          <option key={template.id} value={template.id}>{template.label}</option>
        ))}
      </select>
    </div>
  );
}

export default function NewMeetingPage() {
  const router = useRouter();
  const { openNotetaker } = useShell();
  const [source, setSource] = useState<Source>("upload");
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // upload
  const [file, setFile] = useState<File | null>(null);
  const [uploadKey, setUploadKey] = useState(newIdempotencyKey);
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("hinglish");
  const [template, setTemplate] = useState("auto");
  const [uploadConsent, setUploadConsent] = useState(false);

  // paste
  const [transcript, setTranscript] = useState("");
  const [durationMinutes, setDurationMinutes] = useState("");

  useEffect(() => {
    api.getAssistantStatus().then(setStatus).catch(() => setStatus(null));
    const requested = new URLSearchParams(window.location.search).get("source") as Source | null;
    if (requested && SOURCES.includes(requested)) setSource(requested);
  }, []);

  const maxMb = status?.limits.max_upload_mb ?? 200;

  function chooseFile(next: File | null) {
    setError(null);
    if (next && next.size > maxMb * 1024 * 1024) {
      setFile(null);
      setError(`Recordings must be smaller than ${maxMb} MB`);
      return;
    }
    setFile(next);
    // A new file is a new upload; resubmitting the same file reuses the key.
    setUploadKey(newIdempotencyKey());
  }

  async function submitUpload() {
    if (!file || !uploadConsent) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.uploadMeetingRecording({
        file,
        title: title.trim(),
        language,
        template,
        consentAcknowledged: uploadConsent,
        idempotencyKey: uploadKey,
      });
      router.push(`/meetings/${result.meeting_id}`);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Upload failed");
      setSubmitting(false);
    }
  }

  async function submitPaste() {
    if (!transcript.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.ingestMeeting({
        meetingTitle: title.trim(),
        durationMinutes: Number(durationMinutes) || 0,
        transcript: transcript.trim(),
        template,
        source: "paste",
      });
      router.push(`/meetings/${result.meeting_id}`);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The transcript could not be processed");
      setSubmitting(false);
    }
  }

  const transcriptionReady = status ? status.transcription.configured && status.media_tools : true;

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <PageHeader
        title="Add a meeting"
        description="Bring in a recording or a transcript you already have. It gets the same searchable transcript, cited notes and action items as a live capture."
      />
      {status?.fixture_mode && (
        <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
          Development fixture mode is on: missing transcription or AI keys are replaced by clearly labelled placeholder output.
        </p>
      )}

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => openNotetaker()}
          className="flex items-start gap-3 rounded-xl border bg-card p-4 text-left transition-colors hover:border-primary/40 hover:bg-primary/5"
        >
          <Bot className="mt-0.5 size-5 shrink-0 text-primary" />
          <span>
            <span className="block text-sm font-medium">Meeting happening now?</span>
            <span className="block text-sm text-muted-foreground">Send the notetaker into the Google Meet or Teams call instead.</span>
          </span>
        </button>
        <Link href="/record" className="flex items-start gap-3 rounded-xl border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-primary/5">
          <Mic className="mt-0.5 size-5 shrink-0 text-primary" />
          <span>
            <span className="block text-sm font-medium">Meeting in the room?</span>
            <span className="block text-sm text-muted-foreground">Record it with this device&apos;s microphone.</span>
          </span>
        </Link>
      </div>

      <Card>
        <CardContent className="pt-6">
          <Tabs value={source} onValueChange={(value) => { setSource(value as Source); setError(null); }}>
            <TabsList aria-label="How to add the meeting" className="h-auto! w-full flex-wrap">
              <TabsTrigger value="upload"><Upload /> Upload</TabsTrigger>
              <TabsTrigger value="paste"><FileText /> Paste transcript</TabsTrigger>
            </TabsList>

            <TabsContent value="upload" className="flex flex-col gap-4 pt-4">
              {status && !status.transcription.configured && (
                <SetupRequired>Setup required: transcription is not configured on this server ({status.transcription.missing}). Uploads are disabled until it is.</SetupRequired>
              )}
              {status && status.transcription.configured && !status.media_tools && (
                <SetupRequired>Setup required: this server can&apos;t inspect media files (ffmpeg/ffprobe missing).</SetupRequired>
              )}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="upload-file">Recording</Label>
                <label
                  htmlFor="upload-file"
                  className="flex min-h-28 cursor-pointer flex-col items-center justify-center gap-2 rounded-md border border-dashed bg-muted/30 px-4 text-center hover:bg-muted/60 focus-within:ring-2 focus-within:ring-ring"
                >
                  <Upload className="h-5 w-5 text-muted-foreground" />
                  <span className="text-sm font-medium">{file ? file.name : "Choose an audio or video recording"}</span>
                  <span className="text-xs text-muted-foreground">
                    MP3, WAV, M4A, MP4 or WebM · up to {maxMb} MB and {status?.limits.max_upload_minutes ?? 240} minutes · checked on the server, not by file name
                  </span>
                </label>
                {/* A plain input: the styled Input adds w-full, which beats sr-only and widens the page. */}
                <input id="upload-file" type="file" accept={ACCEPT} className="sr-only" onChange={(event) => chooseFile(event.target.files?.[0] ?? null)} />
              </div>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="upload-title">Title</Label>
                  <Input id="upload-title" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Optional — generated from the content" />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="upload-language">Spoken language</Label>
                  <select id="upload-language" value={language} onChange={(event) => setLanguage(event.target.value)} className="h-9 rounded-md border bg-background px-3 text-sm">
                    {Object.entries(LANGUAGES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </div>
              </div>
              <TemplateSelect status={status} value={template} onChange={setTemplate} id="upload-template" />
              <label className="flex items-start gap-2 text-sm">
                <Checkbox checked={uploadConsent} onCheckedChange={(value) => setUploadConsent(value === true)} className="mt-0.5" />
                <span>
                  I have permission from the people in this recording to store and process it.
                  <span className="block text-xs text-muted-foreground">Recording laws differ by place; this confirmation alone may not satisfy all of them.</span>
                </span>
              </label>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button onClick={() => void submitUpload()} disabled={!file || !uploadConsent || submitting || !transcriptionReady} className="self-start">
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                {submitting ? "Uploading…" : "Upload and process"}
              </Button>
              <p className="text-xs text-muted-foreground">You&apos;ll go straight to the meeting page and can watch transcription and notes progress there.</p>
            </TabsContent>

            <TabsContent value="paste" className="flex flex-col gap-4 pt-4">
              {status && !status.ai.configured && (
                <SetupRequired>AI notes are not configured on this server ({status.ai.missing}). The transcript will still be stored and searchable.</SetupRequired>
              )}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="paste-title">Title</Label>
                  <Input id="paste-title" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Optional" />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="paste-duration">Duration (minutes)</Label>
                  <Input id="paste-duration" type="number" min="0" value={durationMinutes} onChange={(event) => setDurationMinutes(event.target.value)} placeholder="Optional" />
                </div>
              </div>
              <TemplateSelect status={status} value={template} onChange={setTemplate} id="paste-template" />
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="paste-transcript">Transcript</Label>
                <Textarea
                  id="paste-transcript"
                  value={transcript}
                  onChange={(event) => setTranscript(event.target.value)}
                  placeholder={"Asha: Budget stays at 5 lakh.\nRavi: I'll send the deck by Friday."}
                  rows={12}
                />
                <p className="text-xs text-muted-foreground">
                  Accepts plain text, “Name: text” lines, lines starting with a timestamp like [00:01:23], WebVTT, SRT, or a JSON
                  segment list. Timestamps and speaker names are kept only when the text includes them.
                </p>
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button onClick={() => void submitPaste()} disabled={!transcript.trim() || submitting} className="self-start">
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                {submitting ? "Processing…" : "Extract notes"}
              </Button>
            </TabsContent>

          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}
