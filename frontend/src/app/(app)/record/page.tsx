"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  Bookmark,
  Building2,
  Check,
  Loader2,
  Mic,
  MonitorUp,
  Pause,
  Play,
  RotateCcw,
  Square,
  UploadCloud,
  UserPlus,
  X,
} from "lucide-react";
import { api, ApiError, AttendeeInput, DirectoryUser, RecordingSession } from "@/lib/api";
import {
  deleteRecordingChunk,
  listRecordingChunks,
  saveRecordingChunk,
} from "@/lib/recording-store";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Phase = "setup" | "recording" | "paused" | "processing" | "error";
type MeetingType = "physical" | "online";

/** A guest with no Wilco account. Named on the meeting record, but never
 * granted access to it — only colleagues picked from the directory are. */
type ExternalMember = { name: string; email: string };

const SEGMENT_MS = 5 * 60 * 1000;
const PROCESSING_STEPS = [
  { title: "Secure recording", detail: "Uploading the final audio segment" },
  { title: "Identify speakers", detail: "Building the full transcript and diarization" },
  { title: "Analyze meeting", detail: "Generating the title, detailed summary, tasks, and decisions" },
  { title: "Save meeting", detail: "Linking the recording and opening the meeting" },
];

function formatDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return [hours, minutes, seconds].map((value) => String(value).padStart(2, "0")).join(":");
}

function preferredMimeType(): string | undefined {
  return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((type) =>
    MediaRecorder.isTypeSupported(type)
  );
}

export default function RecordMeetingPage() {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("setup");
  const [meetingType, setMeetingType] = useState<MeetingType>("physical");
  const [language, setLanguage] = useState("hinglish");
  const [directory, setDirectory] = useState<DirectoryUser[]>([]);
  const [directoryError, setDirectoryError] = useState(false);
  const [memberIds, setMemberIds] = useState<string[]>([]);
  const [memberQuery, setMemberQuery] = useState("");
  const [externals, setExternals] = useState<ExternalMember[]>([]);
  const [externalName, setExternalName] = useState("");
  const [externalEmail, setExternalEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [session, setSession] = useState<RecordingSession | null>(null);
  const [recoverable, setRecoverable] = useState<RecordingSession[]>([]);
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  const [uploadedChunks, setUploadedChunks] = useState(0);
  const [pendingChunks, setPendingChunks] = useState(0);
  const [bookmarks, setBookmarks] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [processingStep, setProcessingStep] = useState(0);
  const [processingSeconds, setProcessingSeconds] = useState(0);

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const segmentTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const animationRef = useRef<number | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const nextChunkRef = useRef(0);
  const activeRef = useRef(false);
  const pausedRef = useRef(false);
  const writePromisesRef = useRef<Promise<void>[]>([]);
  const stopResolveRef = useRef<(() => void) | null>(null);
  const syncPromiseRef = useRef<Promise<void> | null>(null);

  const refreshPendingCount = useCallback(async (recordingId: string) => {
    const chunks = await listRecordingChunks(recordingId);
    setPendingChunks(chunks.length);
    return chunks;
  }, []);

  const syncPending = useCallback(
    async (recordingId: string) => {
      // One upload pass at a time. A pass already running listed its chunks
      // before newer ones were saved (the final segment, on finish), so wait
      // for it and then run a pass of our own rather than reusing it.
      while (syncPromiseRef.current) await syncPromiseRef.current.catch(() => undefined);
      const operation = (async () => {
        const chunks = await refreshPendingCount(recordingId);
        for (const item of chunks) {
          await api.uploadRecordingChunk(recordingId, item.index, item.blob);
          await deleteRecordingChunk(recordingId, item.index);
          setUploadedChunks((count) => Math.max(count, item.index + 1));
          setPendingChunks((count) => Math.max(0, count - 1));
        }
      })().finally(() => {
        syncPromiseRef.current = null;
      });
      syncPromiseRef.current = operation;
      return operation;
    },
    [refreshPendingCount]
  );

  useEffect(() => {
    api.listActiveRecordings().then(setRecoverable).catch(() => setRecoverable([]));
  }, []);

  useEffect(() => {
    api
      .getDirectory()
      .then((people) => {
        setDirectory(people);
        setDirectoryError(false);
      })
      .catch(() => setDirectoryError(true));
  }, []);

  const attendees: AttendeeInput[] = [
    ...memberIds.map((id) => {
      const person = directory.find((item) => item.id === id);
      return { user_id: id, name: person?.name ?? "", email: person?.email ?? null };
    }),
    ...externals.map((guest) => ({ user_id: null, name: guest.name, email: guest.email || null })),
  ];

  function addExternal() {
    const name = externalName.trim();
    const email = externalEmail.trim();
    if (!name && !email) return;
    const label = name || email;
    if (externals.some((guest) => guest.name.toLowerCase() === label.toLowerCase())) return;
    setExternals((current) => [...current, { name: label, email }]);
    setExternalName("");
    setExternalEmail("");
  }

  useEffect(() => {
    if (phase !== "processing") return;
    setProcessingSeconds(0);
    const timer = setInterval(() => setProcessingSeconds((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, [phase]);

  useEffect(() => {
    return () => {
      activeRef.current = false;
      if (segmentTimerRef.current) clearTimeout(segmentTimerRef.current);
      if (tickRef.current) clearInterval(tickRef.current);
      if (animationRef.current) cancelAnimationFrame(animationRef.current);
      recorderRef.current?.stop();
      streamRef.current?.getTracks().forEach((track) => track.stop());
      void audioContextRef.current?.close();
    };
  }, []);

  function monitorAudio(stream: MediaStream) {
    const context = new AudioContext();
    const analyser = context.createAnalyser();
    analyser.fftSize = 256;
    context.createMediaStreamSource(stream).connect(analyser);
    const values = new Uint8Array(analyser.frequencyBinCount);
    const update = () => {
      analyser.getByteFrequencyData(values);
      const average = values.reduce((sum, value) => sum + value, 0) / values.length;
      setLevel(Math.min(100, Math.round(average * 1.7)));
      animationRef.current = requestAnimationFrame(update);
    };
    audioContextRef.current = context;
    update();
  }

  const stopSegment = useCallback(async () => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    await new Promise<void>((resolve) => {
      stopResolveRef.current = resolve;
      recorder.stop();
    });
  }, []);

  const startSegment = useCallback(
    (recordingId: string) => {
      if (!streamRef.current || !activeRef.current) return;
      const mimeType = preferredMimeType();
      const recorder = new MediaRecorder(streamRef.current, mimeType ? { mimeType } : undefined);
      recorderRef.current = recorder;
      writePromisesRef.current = [];
      recorder.ondataavailable = (event) => {
        if (!event.data.size) return;
        const index = nextChunkRef.current++;
        const write = saveRecordingChunk(recordingId, index, event.data).then(() => {
          setPendingChunks((count) => count + 1);
        });
        writePromisesRef.current.push(write);
      };
      recorder.onstop = async () => {
        await Promise.all(writePromisesRef.current);
        stopResolveRef.current?.();
        stopResolveRef.current = null;
        void syncPending(recordingId).catch(() => undefined);
      };
      recorder.start();
      segmentTimerRef.current = setTimeout(async () => {
        await stopSegment();
        if (activeRef.current && !pausedRef.current) startSegment(recordingId);
      }, SEGMENT_MS);
    },
    [stopSegment, syncPending]
  );

  async function beginMicrophone(recording: RecordingSession, elapsed = 0) {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const localChunks = await listRecordingChunks(recording.id);
    nextChunkRef.current = Math.max(
      recording.chunk_count,
      ...localChunks.map((item) => item.index + 1),
      0
    );
    streamRef.current = stream;
    activeRef.current = true;
    pausedRef.current = false;
    setSession(recording);
    setMeetingType(recording.meeting_type);
    setLanguage(recording.language);
    setMemberIds(
      (recording.attendees ?? []).filter((item) => item.user_id).map((item) => item.user_id as string)
    );
    setExternals(
      (recording.attendees ?? [])
        .filter((item) => !item.user_id)
        .map((item) => ({ name: item.name, email: item.email ?? "" }))
    );
    setSeconds(elapsed);
    setUploadedChunks(recording.chunk_count);
    setPendingChunks(localChunks.length);
    setPhase("recording");
    setError(null);
    monitorAudio(stream);
    startSegment(recording.id);
    tickRef.current = setInterval(() => setSeconds((value) => value + 1), 1000);
    void syncPending(recording.id).catch(() => undefined);
  }

  async function startNewRecording() {
    if (!consent) return;
    try {
      const recording = await api.createRecording({
        title: "",
        meetingType,
        language,
        attendees,
      });
      await beginMicrophone(recording);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Microphone access was denied or unavailable.");
      setPhase("error");
    }
  }

  async function resumeRecording(recording: RecordingSession) {
    try {
      const elapsed = Math.max(0, Math.floor((Date.now() - new Date(recording.started_at).getTime()) / 1000));
      await beginMicrophone(recording, elapsed);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Unable to resume this recording.");
      setPhase("error");
    }
  }

  function pauseRecording() {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state !== "recording") return;
    recorder.pause();
    pausedRef.current = true;
    if (segmentTimerRef.current) clearTimeout(segmentTimerRef.current);
    if (tickRef.current) clearInterval(tickRef.current);
    setPhase("paused");
  }

  function resumePausedRecording() {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state !== "paused") return;
    recorder.resume();
    pausedRef.current = false;
    segmentTimerRef.current = setTimeout(async () => {
      await stopSegment();
      if (session && activeRef.current) startSegment(session.id);
    }, SEGMENT_MS);
    tickRef.current = setInterval(() => setSeconds((value) => value + 1), 1000);
    setPhase("recording");
  }

  async function finishRecording(recording = session) {
    if (!recording) return;
    setPhase("processing");
    setProcessingStep(0);
    setError(null);
    activeRef.current = false;
    if (segmentTimerRef.current) clearTimeout(segmentTimerRef.current);
    if (tickRef.current) clearInterval(tickRef.current);
    try {
      await stopSegment();
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      if (animationRef.current) cancelAnimationFrame(animationRef.current);
      setLevel(0);
      await syncPending(recording.id);
      setProcessingStep(1);
      const finalized = await api.finalizeRecording(recording.id, Math.max(seconds, recording.duration_seconds));
      setProcessingStep(2);
      const result = await api.ingestMeeting({
        meetingTitle: "",
        durationMinutes: Math.max(1, Math.ceil(Math.max(seconds, recording.duration_seconds) / 60)),
        transcript: finalized.transcript,
        source: "record",
        // Sent here as well as on linkRecording below, so the right people can
        // read the meeting even if the link step fails.
        attendees: (recording.attendees ?? []).map((item) => ({
          user_id: item.user_id,
          name: item.name,
          email: item.email,
        })),
      });
      setProcessingStep(3);
      await api.linkRecording(recording.id, result.meeting_id);
      // "Mark moment" presses become real bookmarks on the meeting, playable
      // from its transcript. Best effort: the meeting is already saved.
      await Promise.allSettled(
        bookmarks.map((at) =>
          api.addMeetingBookmark(result.meeting_id, { label: `Marked while recording at ${formatDuration(at)}`, start_ms: at * 1000 }),
        ),
      );
      router.push(`/meetings/${result.meeting_id}`);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The recording is safe locally, but processing failed.");
      setPhase("error");
      setRecoverable(await api.listActiveRecordings().catch(() => [recording]));
    }
  }

  const isLive = phase === "recording" || phase === "paused";

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Record meeting</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Capture an in-room or online conversation and turn it into searchable meeting memory.
          </p>
        </div>
        {session && isLive && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <UploadCloud className="h-4 w-4" />
            {pendingChunks ? `${pendingChunks} saved locally` : `${uploadedChunks} segments secured`}
          </div>
        )}
      </div>

      {!isLive && phase !== "processing" && (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_320px]">
          <Card>
            <CardHeader><CardTitle className="text-base">Meeting setup</CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-5">
              <div className="grid grid-cols-2 gap-2 rounded-md bg-muted p-1">
                <button type="button" onClick={() => setMeetingType("physical")} className={`flex h-10 items-center justify-center gap-2 rounded-sm text-sm font-medium ${meetingType === "physical" ? "bg-background shadow-sm" : "text-muted-foreground"}`}>
                  <Building2 className="h-4 w-4" /> Physical
                </button>
                <button type="button" onClick={() => setMeetingType("online")} className={`flex h-10 items-center justify-center gap-2 rounded-sm text-sm font-medium ${meetingType === "online" ? "bg-background shadow-sm" : "text-muted-foreground"}`}>
                  <MonitorUp className="h-4 w-4" /> Online
                </button>
              </div>
              <div className="grid gap-2">
                <Label htmlFor="language">Language</Label>
                <select id="language" value={language} onChange={(event) => setLanguage(event.target.value)} className="h-9 rounded-md border bg-background px-3 text-sm">
                  <option value="hinglish">Hinglish</option><option value="en">English</option><option value="hi">Hindi</option><option value="auto">Auto detect</option>
                </select>
              </div>
              <div className="grid gap-3">
                <div className="flex items-baseline justify-between gap-3">
                  <Label>Who was in this meeting</Label>
                  <span className="text-xs text-muted-foreground">
                    {attendees.length} selected
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  Only the colleagues you pick here can open this meeting afterwards. External
                  guests are recorded on the meeting but never get access to it.
                </p>

                {directoryError ? (
                  <p className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                    Could not load your team directory. You can still record — add everyone as an
                    external guest below, or set the attendees on the meeting page afterwards.
                  </p>
                ) : (
                  <>
                    {directory.length > 6 && (
                      <Input
                        value={memberQuery}
                        onChange={(event) => setMemberQuery(event.target.value)}
                        placeholder="Search your team"
                        className="h-9"
                      />
                    )}
                    <div className="grid max-h-56 grid-cols-1 gap-2 overflow-y-auto sm:grid-cols-2">
                      {directory
                        .filter((person) => {
                          const needle = memberQuery.trim().toLowerCase();
                          if (!needle) return true;
                          return (
                            person.name.toLowerCase().includes(needle) ||
                            person.email.toLowerCase().includes(needle)
                          );
                        })
                        .map((person) => (
                          <label
                            key={person.id}
                            className="flex min-h-10 items-center gap-2 rounded-md border px-3 py-2 text-sm"
                          >
                            <Checkbox
                              checked={memberIds.includes(person.id)}
                              onCheckedChange={(checked) =>
                                setMemberIds((current) =>
                                  checked === true
                                    ? [...current, person.id]
                                    : current.filter((item) => item !== person.id)
                                )
                              }
                            />
                            <span className="min-w-0">
                              <span className="block truncate">{person.name}</span>
                              <span className="block truncate text-xs text-muted-foreground">
                                {person.email}
                              </span>
                            </span>
                          </label>
                        ))}
                      {directory.length === 0 && (
                        <p className="text-sm text-muted-foreground">
                          No other Wilco accounts yet.
                        </p>
                      )}
                    </div>
                  </>
                )}

                <div className="grid gap-2 rounded-md border border-dashed p-3">
                  <Label className="text-sm">External members</Label>
                  <p className="text-xs text-muted-foreground">
                    Clients, vendors, or candidates without a Wilco account.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Input
                      value={externalName}
                      onChange={(event) => setExternalName(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          addExternal();
                        }
                      }}
                      placeholder="Name"
                      className="h-9 min-w-32 flex-1"
                    />
                    <Input
                      value={externalEmail}
                      onChange={(event) => setExternalEmail(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          addExternal();
                        }
                      }}
                      placeholder="Email (optional)"
                      type="email"
                      className="h-9 min-w-32 flex-1"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-9 gap-1.5"
                      onClick={addExternal}
                      disabled={!externalName.trim() && !externalEmail.trim()}
                    >
                      <UserPlus className="h-3.5 w-3.5" /> Add
                    </Button>
                  </div>
                  {externals.length > 0 && (
                    <div className="flex flex-wrap gap-2 pt-1">
                      {externals.map((guest) => (
                        <span
                          key={guest.name}
                          className="flex items-center gap-1.5 rounded-full border bg-muted px-3 py-1 text-xs"
                        >
                          {guest.name}
                          {guest.email && (
                            <span className="text-muted-foreground">{guest.email}</span>
                          )}
                          <button
                            type="button"
                            aria-label={`Remove ${guest.name}`}
                            onClick={() =>
                              setExternals((current) =>
                                current.filter((item) => item.name !== guest.name)
                              )
                            }
                            className="text-muted-foreground hover:text-foreground"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <label className="flex items-start gap-3 rounded-md border p-3 text-sm">
                <Checkbox checked={consent} onCheckedChange={(value) => setConsent(value === true)} />
                <span>I have informed everyone present and have permission to record this meeting.</span>
              </label>
              <Button onClick={startNewRecording} disabled={!consent} className="gap-2">
                <Mic className="h-4 w-4" /> Start recording
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2 text-base"><RotateCcw className="h-4 w-4" /> Recover a session</CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-3">
              {recoverable.length === 0 && <p className="text-sm text-muted-foreground">No interrupted recordings.</p>}
              {recoverable.map((recording) => (
                <div key={recording.id} className="rounded-md border p-3">
                  <p className="text-sm font-medium">{recording.title}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{recording.chunk_count} uploaded segments · {recording.status}</p>
                  <div className="mt-3 flex gap-2">
                    {recording.status === "recording" && <Button size="sm" variant="outline" onClick={() => resumeRecording(recording)}><Play className="h-3.5 w-3.5" /> Continue</Button>}
                    <Button size="sm" onClick={() => { setSession(recording); setSeconds(recording.duration_seconds); void finishRecording(recording); }}><Check className="h-3.5 w-3.5" /> Process</Button>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      )}

      {isLive && session && (
        <Card>
          <CardContent className="flex min-h-[430px] flex-col items-center justify-center gap-6 py-10">
            <div className="text-center">
              <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground"><span className={`h-2 w-2 rounded-full ${phase === "recording" ? "animate-pulse bg-red-500" : "bg-amber-500"}`} />{phase === "recording" ? "Recording" : "Paused"}</div>
              <p className="mt-3 font-mono text-4xl font-semibold tabular-nums">{formatDuration(seconds)}</p>
              <p className="mt-2 text-sm font-medium">{session.title}</p>
            </div>
            <div className="flex h-28 w-28 items-center justify-center rounded-full border-8 border-muted bg-primary text-primary-foreground" style={{ boxShadow: `0 0 0 ${Math.round(level / 5)}px color-mix(in oklab, var(--primary) 16%, transparent)` }}><Mic className="h-10 w-10" /></div>
            <div className="h-2 w-48 overflow-hidden rounded-full bg-muted"><div className="h-full bg-primary transition-[width]" style={{ width: `${Math.max(3, level)}%` }} /></div>
            <div className="flex flex-wrap justify-center gap-2">
              <Button variant="outline" onClick={phase === "paused" ? resumePausedRecording : pauseRecording}>{phase === "paused" ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}{phase === "paused" ? "Resume" : "Pause"}</Button>
              <Button variant="outline" onClick={() => setBookmarks((values) => [...values, seconds])}><Bookmark className="h-4 w-4" /> Mark moment</Button>
              <Button variant="destructive" onClick={() => void finishRecording()}><Square className="h-4 w-4" /> End meeting</Button>
            </div>
            {bookmarks.length > 0 && <p className="text-xs text-muted-foreground">Marked: {bookmarks.map(formatDuration).join(", ")}</p>}
          </CardContent>
        </Card>
      )}

      {phase === "processing" && (
        <Card>
          <CardContent className="mx-auto flex min-h-[390px] w-full max-w-2xl flex-col justify-center gap-6 py-10">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="font-medium">Processing meeting</p>
                <p className="mt-1 text-sm text-muted-foreground">Step {processingStep + 1} of {PROCESSING_STEPS.length} · {formatDuration(processingSeconds)}</p>
              </div>
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div className="h-full bg-primary transition-[width] duration-500" style={{ width: `${((processingStep + 1) / PROCESSING_STEPS.length) * 100}%` }} />
            </div>
            <div className="grid gap-3">
              {PROCESSING_STEPS.map((step, index) => {
                const complete = index < processingStep;
                const active = index === processingStep;
                return (
                  <div key={step.title} className={`flex min-h-16 items-center gap-3 rounded-md border px-4 py-3 ${active ? "border-primary/40 bg-accent/50" : ""}`}>
                    <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border ${complete ? "border-primary bg-primary text-primary-foreground" : active ? "border-primary text-primary" : "text-muted-foreground"}`}>
                      {complete ? <Check className="h-4 w-4" /> : active ? <Loader2 className="h-4 w-4 animate-spin" /> : <span className="text-xs">{index + 1}</span>}
                    </div>
                    <div>
                      <p className={`text-sm font-medium ${!active && !complete ? "text-muted-foreground" : ""}`}>{step.title}</p>
                      <p className="mt-0.5 text-xs text-muted-foreground">{step.detail}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {error && <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{error}</div>}
    </div>
  );
}
