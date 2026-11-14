"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowRight, Check, CircleHelp, ListChecks, Play, Scale, Share2, UserRound } from "lucide-react";
import { api, ApiError, type EvidenceRef, type MeetingDetail, type TranscriptSpeaker } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth-context";

type ReviewItem =
  | { kind: "task"; id: string; text: string; detail: string; evidence?: EvidenceRef[] }
  | { kind: "decision"; id: string; text: string; detail: string; evidence?: EvidenceRef[] }
  | { kind: "speaker"; id: string; text: string; detail: string };

export function GuidedReview({ meeting, onChanged, onEvidence, onShare, shareBusy, shareCopied }: {
  meeting: MeetingDetail;
  onChanged: () => Promise<void>;
  onEvidence: (ref: EvidenceRef) => void;
  onShare: () => void;
  shareBusy: boolean;
  shareCopied: boolean;
}) {
  const { user } = useAuth();
  const [speakers, setSpeakers] = useState<TranscriptSpeaker[]>([]);
  const [speakersLoading, setSpeakersLoading] = useState(true);
  const [cursor, setCursor] = useState(0);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    void api.getTranscript(meeting.id, { limit: 1 }).then((page) => setSpeakers(page.speakers)).catch(() => undefined).finally(() => setSpeakersLoading(false));
  }, [meeting.id]);

  const items = useMemo(() => {
    const rows: ReviewItem[] = [];
    for (const task of meeting.tasks.filter((entry) => !entry.verified_at)) {
      rows.push({ kind: "task", id: task.id, text: task.description, detail: [task.owner && `Owner: ${task.owner}`, task.deadline && `Due: ${task.deadline}`].filter(Boolean).join(" · ") || "Confirm the task and owner", evidence: task.evidence });
    }
    for (const decision of meeting.decisions.filter((entry) => !entry.verified_at)) {
      rows.push({ kind: "decision", id: decision.id, text: decision.decision, detail: decision.reason || "Confirm this was agreed", evidence: decision.evidence });
    }
    for (const speaker of speakers.filter((entry) => !entry.named && entry.segment_count > 0)) {
      rows.push({ kind: "speaker", id: speaker.key, text: `Who is ${speaker.generic}?`, detail: `${speaker.segment_count} transcript ${speaker.segment_count === 1 ? "turn" : "turns"} need a name` });
    }
    return rows;
  }, [meeting, speakers]);
  const position = Math.min(cursor, Math.max(0, items.length - 1));
  const current = items[position];
  const finished = items.length === 0;
  if (dismissed) return null;

  async function confirm() {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      if (current.kind === "task") {
        const task = meeting.tasks.find((entry) => entry.id === current.id);
        if (!task) return;
        await api.updateTask(task.id, { description: task.description });
      } else if (current.kind === "decision") {
        const decision = meeting.decisions.find((entry) => entry.id === current.id);
        if (!decision) return;
        await api.updateDecision(decision.id, { decision: decision.decision, reason: decision.reason || "", alternatives: decision.alternatives, participants: decision.participants });
      } else {
        const chosen = name.trim();
        if (!chosen) { setError("Choose the speaker's name first."); return; }
        await api.renameTranscriptSpeakers(meeting.id, { [current.id]: chosen });
        if (user?.name && chosen.toLocaleLowerCase() === user.name.toLocaleLowerCase()) {
          // Naming your own voice is the explicit confirmation needed before
          // this meeting can improve your future speaker matches.
          void api.confirmVoiceSpeaker(meeting.id, current.id).catch(() => undefined);
        }
        setSpeakers((old) => old.map((speaker) => speaker.key === current.id ? { ...speaker, label: chosen, named: true } : speaker));
        setName("");
      }
      await onChanged();
      setCursor(0);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save this review.");
    } finally {
      setBusy(false);
    }
  }

  return <section id="guided-review" aria-label="Meeting review" className="overflow-hidden rounded-3xl border border-primary/20 bg-card shadow-sm">
    <div className="flex items-center justify-between border-b px-5 py-4 sm:px-7">
      <div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Meeting review</p><h2 className="mt-1 font-heading text-lg font-semibold">{finished ? "Ready to share" : "Resolve what matters"}</h2></div>
      <button type="button" onClick={() => setDismissed(true)} className="text-xs font-medium text-muted-foreground hover:text-foreground">View full meeting</button>
    </div>
    {speakersLoading && finished ? <div className="px-5 py-8 text-sm text-muted-foreground sm:px-7">Checking the meeting…</div> : finished ? <div className="px-5 py-8 sm:px-7">
      <span className="mb-4 grid size-12 place-items-center rounded-2xl bg-success/10 text-success"><Check className="size-6" /></span>
      <p className="max-w-xl text-sm leading-6 text-muted-foreground">{meeting.summary || "Tasks, decisions and speakers have been reviewed. The full meeting record is available below."}</p>
      {meeting.can_manage_access && !meeting.confidential && <Button className="mt-6" onClick={onShare} disabled={shareBusy}><Share2 className="size-4" />{shareCopied ? "Link copied" : shareBusy ? "Creating link…" : "Copy recap link"}</Button>}
    </div> : <div className="px-5 py-6 sm:px-7 sm:py-8" aria-live="polite">
      <div className="flex items-center justify-between text-xs text-muted-foreground"><span>{current.kind === "task" ? "TASK" : current.kind === "decision" ? "DECISION" : "SPEAKER"}</span><span className="font-mono tabular-nums">{position + 1} / {items.length}</span></div>
      <div className="mt-4 flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">{current.kind === "task" ? <ListChecks className="size-5" /> : current.kind === "decision" ? <Scale className="size-5" /> : <UserRound className="size-5" />}</span><div><h3 className="font-heading text-xl font-semibold leading-snug sm:text-2xl">{current.text}</h3><p className="mt-2 text-sm text-muted-foreground">{current.detail}</p></div></div>
      {current.kind === "speaker" && <div className="mt-6 max-w-sm"><label htmlFor="review-speaker" className="mb-2 block text-xs font-semibold">Who spoke?</label><Input id="review-speaker" list="review-attendees" value={name} onChange={(event) => setName(event.target.value)} placeholder="Choose or enter a name" /><datalist id="review-attendees">{meeting.attendees.map((attendee) => <option key={attendee.id} value={attendee.name} />)}</datalist><p className="mt-2 flex gap-1.5 text-xs text-muted-foreground"><CircleHelp className="size-3.5 shrink-0" />Unsure? Leave this speaker unnamed and check the transcript later.</p></div>}
      {current.kind !== "speaker" && current.evidence?.[0] && <button type="button" onClick={() => onEvidence(current.evidence![0])} className="mt-6 inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold hover:bg-accent"><Play className="size-3.5" />Hear the source moment</button>}
      {error && <p className="mt-4 text-sm text-destructive" role="alert">{error}</p>}
      <div className="mt-7 flex flex-wrap items-center gap-3">
        <Button onClick={() => void confirm()} disabled={busy}><Check className="size-4" />{busy ? "Saving…" : current.kind === "speaker" ? "Save speaker" : "Confirm"}</Button>
        {current.kind === "speaker" && <button type="button" onClick={() => setCursor((position + 1) % items.length)} className="text-sm text-muted-foreground hover:text-foreground">I&apos;m not sure</button>}
        {items.length > 1 && <button type="button" onClick={() => setCursor((position + 1) % items.length)} className="ml-auto inline-flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground">Next item <ArrowRight className="size-4" /></button>}
      </div>
    </div>}
  </section>;
}
