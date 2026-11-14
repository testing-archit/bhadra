"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Check,
  ChevronLeft,
  ChevronRight,
  ListChecks,
  Pencil,
  Play,
  Scale,
  Share2,
  UserRound,
} from "lucide-react";
import {
  api,
  ApiError,
  type EvidenceRef,
  type MeetingDetail,
  type TranscriptSpeaker,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth-context";

type ReviewItem = {
  kind: "task" | "decision" | "speaker";
  id: string;
  text: string;
  detail: string;
  evidence?: EvidenceRef[];
};

export function GuidedReview({
  meeting,
  onChanged,
  onEvidence,
  onShare,
  onOpenFullMeeting,
  shareBusy,
  shareCopied,
}: {
  meeting: MeetingDetail;
  onChanged: () => Promise<void>;
  onEvidence: (ref: EvidenceRef) => void;
  onShare: () => void;
  onOpenFullMeeting?: () => void;
  shareBusy: boolean;
  shareCopied: boolean;
}) {
  const { user } = useAuth();
  const [speakers, setSpeakers] = useState<TranscriptSpeaker[]>([]);
  const [speakersLoading, setSpeakersLoading] = useState(true);
  const [speakerError, setSpeakerError] = useState(false);
  const [deferred, setDeferred] = useState<string[]>([]);
  const [cursor, setCursor] = useState(0);
  const [name, setName] = useState("");
  const [learnVoice, setLearnVoice] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [owner, setOwner] = useState("");
  const [deadline, setDeadline] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSpeakers = useCallback(async () => {
    setSpeakersLoading(true);
    setSpeakerError(false);
    try {
      setSpeakers((await api.getTranscript(meeting.id, { limit: 1 })).speakers);
    } catch {
      setSpeakerError(true);
    } finally {
      setSpeakersLoading(false);
    }
  }, [meeting.id]);
  useEffect(() => {
    void loadSpeakers();
  }, [loadSpeakers]);

  const items = useMemo(() => {
    const rows: ReviewItem[] = [];
    for (const task of meeting.tasks.filter((entry) => !entry.verified_at))
      rows.push({
        kind: "task",
        id: task.id,
        text: task.description,
        detail: [
          task.owner || "Unassigned",
          task.deadline && `Due ${task.deadline}`,
        ]
          .filter(Boolean)
          .join(" · "),
        evidence: task.evidence,
      });
    for (const decision of meeting.decisions.filter(
      (entry) => !entry.verified_at,
    ))
      rows.push({
        kind: "decision",
        id: decision.id,
        text: decision.decision,
        detail: decision.reason || "Was this agreed?",
        evidence: decision.evidence,
      });
    for (const speaker of speakers.filter(
      (entry) =>
        !entry.named &&
        entry.segment_count > 0 &&
        !deferred.includes(entry.key),
    ))
      rows.push({
        kind: "speaker",
        id: speaker.key,
        text: `Who is ${speaker.generic}?`,
        detail: `${speaker.segment_count} transcript turns`,
      });
    return rows;
  }, [meeting, speakers, deferred]);
  const position = Math.min(cursor, Math.max(0, items.length - 1));
  const current = items[position];
  const finished = items.length === 0 && !speakersLoading && !speakerError;
  const identifiesMe = Boolean(
    user?.name &&
    name.trim().toLocaleLowerCase() === user.name.trim().toLocaleLowerCase(),
  );

  function move(next: number) {
    setCursor(next);
    setEditing(false);
    setName("");
    setLearnVoice(false);
    setError(null);
  }
  function edit() {
    if (!current) return;
    setDraft(current.text);
    const task = meeting.tasks.find((entry) => entry.id === current.id);
    setOwner(task?.owner || "");
    setDeadline(task?.deadline || "");
    setEditing(true);
  }
  async function confirm() {
    if (!current || busy) return;
    setBusy(true);
    setError(null);
    let learningFailed = false;
    try {
      if (current.kind === "task")
        await api.updateTask(
          current.id,
          editing
            ? {
                description: draft.trim(),
                owner: owner.trim() || null,
                deadline: deadline.trim() || null,
              }
            : { description: current.text },
        );
      else if (current.kind === "decision") {
        const decision = meeting.decisions.find(
          (entry) => entry.id === current.id,
        );
        if (!decision) return;
        await api.updateDecision(decision.id, {
          decision: editing ? draft.trim() : decision.decision,
          reason: decision.reason || "",
          alternatives: decision.alternatives,
          participants: decision.participants,
        });
      } else {
        const chosen = name.trim();
        if (!chosen) {
          setError("Choose a name, or leave this speaker unnamed.");
          return;
        }
        await api.renameTranscriptSpeakers(meeting.id, {
          [current.id]: chosen,
        });
        // Saving a transcript label does not imply consent to train future matches.
        if (identifiesMe && learnVoice) {
          try {
            await api.confirmVoiceSpeaker(meeting.id, current.id);
          } catch {
            learningFailed = true;
          }
        }
        setSpeakers((old) =>
          old.map((speaker) =>
            speaker.key === current.id
              ? { ...speaker, label: chosen, named: true }
              : speaker,
          ),
        );
      }
      await onChanged();
      move(0);
      if (learningFailed)
        setError("Name saved. Voice learning could not be confirmed.");
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Couldn't save. Your changes are still here.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      id="guided-review"
      aria-labelledby="review-heading"
      className="review-workspace"
    >
      <header className="flex flex-wrap items-center justify-between gap-3 border-b px-6 py-5 sm:px-8">
        <h2 id="review-heading" className="text-sm font-medium">
          {finished ? "Ready for a recap" : "A quick check"}
        </h2>
        <span className="text-xs text-muted-foreground" role="status">
          {speakersLoading
            ? "Checking speakers…"
            : finished
              ? "All set"
              : `${items.length} left`}
        </span>
      </header>
      {finished ? (
        <div className="px-6 py-8 sm:px-8">
          <span className="mb-5 grid size-11 place-items-center rounded-full bg-success/10 text-success">
            <Check className="size-5" aria-hidden="true" />
          </span>
          <h3 className="text-2xl font-medium tracking-tight">
            That&apos;s the meeting, handled.
          </h3>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
            {meeting.summary || "Your tasks and decisions are confirmed."}
          </p>
          {deferred.length > 0 && (
            <p className="mt-3 text-xs text-muted-foreground">
              {deferred.length}{" "}
              {deferred.length === 1 ? "speaker stays" : "speakers stay"}{" "}
              unnamed. You can identify them in the transcript later.
            </p>
          )}
          <div className="mt-6 flex flex-wrap gap-3">
            {meeting.can_manage_access && !meeting.confidential && (
              <Button size="lg" onClick={onShare} disabled={shareBusy}>
                <Share2 data-icon="inline-start" />
                {shareCopied
                  ? "Link copied"
                  : shareBusy
                    ? "Creating link…"
                    : "Copy recap link"}
              </Button>
            )}
            <Button variant="outline" size="lg" onClick={onOpenFullMeeting}>
              Open full meeting <ArrowRight data-icon="inline-end" />
            </Button>
          </div>
        </div>
      ) : current ? (
        <div className="px-6 py-7 sm:px-8 sm:py-9" aria-busy={busy}>
          <div className="mb-5 flex items-center gap-2 text-xs text-muted-foreground">
            {current.kind === "task" ? (
              <ListChecks className="size-4" />
            ) : current.kind === "decision" ? (
              <Scale className="size-4" />
            ) : (
              <UserRound className="size-4" />
            )}
            {current.kind === "task"
              ? "Action item"
              : current.kind === "decision"
                ? "Decision"
                : "Speaker"}
          </div>
          {editing ? (
            <div className="flex max-w-xl flex-col gap-4">
              <div>
                <label
                  htmlFor="review-text"
                  className="mb-2 block text-xs font-medium"
                >
                  {current.kind === "task" ? "Task" : "Decision"}
                </label>
                <textarea
                  id="review-text"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  rows={3}
                  className="w-full resize-y rounded-xl border bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring"
                />
              </div>
              {current.kind === "task" && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <label
                      htmlFor="review-owner"
                      className="mb-2 block text-xs font-medium"
                    >
                      Owner
                    </label>
                    <Input
                      id="review-owner"
                      value={owner}
                      onChange={(event) => setOwner(event.target.value)}
                      placeholder="Unassigned"
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="review-deadline"
                      className="mb-2 block text-xs font-medium"
                    >
                      Due
                    </label>
                    <Input
                      id="review-deadline"
                      value={deadline}
                      onChange={(event) => setDeadline(event.target.value)}
                      placeholder="No due date"
                    />
                  </div>
                </div>
              )}
            </div>
          ) : (
            <>
              <h3 className="max-w-2xl text-2xl leading-snug font-medium tracking-tight sm:text-3xl">
                {current.text}
              </h3>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
                {current.detail}
              </p>
            </>
          )}
          {current.kind === "speaker" && (
            <div className="mt-6 max-w-md">
              <label
                htmlFor="review-speaker"
                className="mb-2 block text-xs font-medium"
              >
                Speaker name
              </label>
              <Input
                id="review-speaker"
                list="review-attendees"
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                  setLearnVoice(false);
                }}
                placeholder="Choose or type a name"
              />
              <datalist id="review-attendees">
                {meeting.attendees.map((attendee) => (
                  <option key={attendee.id} value={attendee.name} />
                ))}
              </datalist>
              {identifiesMe && (
                <label className="mt-4 flex items-start gap-2 text-xs text-muted-foreground">
                  <Checkbox
                    checked={learnVoice}
                    onCheckedChange={(value) => setLearnVoice(value === true)}
                  />
                  Use this sample to improve my future voice matches.
                </label>
              )}
            </div>
          )}
          {current.evidence?.[0] && (
            <button
              type="button"
              onClick={() => onEvidence(current.evidence![0])}
              className="mt-5 inline-flex min-h-9 items-center gap-2 text-xs font-medium text-muted-foreground hover:text-foreground"
            >
              <Play className="size-3.5" aria-hidden="true" />
              Check the source
            </button>
          )}
          <div className="mt-7 flex flex-wrap items-center gap-3">
            <Button
              size="lg"
              onClick={() => void confirm()}
              disabled={
                busy ||
                (editing && !draft.trim()) ||
                (current.kind === "speaker" && !name.trim())
              }
            >
              <Check data-icon="inline-start" />
              {busy
                ? "Saving…"
                : editing
                  ? "Save & confirm"
                  : current.kind === "speaker"
                    ? "Save name"
                    : "Looks right"}
            </Button>
            {current.kind === "speaker" ? (
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => {
                  setDeferred((old) => [...old, current.id]);
                  move(0);
                }}
              >
                Leave unnamed
              </Button>
            ) : (
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => (editing ? setEditing(false) : edit())}
              >
                {!editing && <Pencil data-icon="inline-start" />}
                {editing ? "Cancel edit" : "Edit"}
              </Button>
            )}
          </div>
        </div>
      ) : (
        <p className="p-8 text-sm text-muted-foreground">
          {speakerError
            ? "Speaker names couldn't be checked."
            : "Checking the meeting…"}
        </p>
      )}
      {speakerError && (
        <div
          className="flex items-center justify-between gap-4 border-t px-6 py-4 text-xs"
          role="alert"
        >
          <span>Speaker review is unavailable.</span>
          <button
            type="button"
            onClick={() => void loadSpeakers()}
            className="underline underline-offset-4"
          >
            Try again
          </button>
        </div>
      )}
      {error && (
        <p className="px-6 pb-5 text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
      {!finished && current && (
        <footer className="flex items-center justify-between border-t px-6 py-4 sm:px-8">
          <button
            type="button"
            onClick={onOpenFullMeeting}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            Open full meeting
          </button>
          <div className="flex gap-1">
            <Button
              variant="ghost"
              size="icon-lg"
              aria-label="Previous review item"
              disabled={busy || position === 0}
              onClick={() => move(position - 1)}
            >
              <ChevronLeft />
            </Button>
            <Button
              variant="ghost"
              size="icon-lg"
              aria-label="Next review item"
              disabled={busy || position >= items.length - 1}
              onClick={() => move(position + 1)}
            >
              <ChevronRight />
            </Button>
          </div>
        </footer>
      )}
    </section>
  );
}
