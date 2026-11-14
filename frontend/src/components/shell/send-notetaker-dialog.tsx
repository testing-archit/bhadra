"use client";

import { useEffect, useState } from "react";
import {
  ArrowRight,
  Bot,
  CheckCircle2,
  Clipboard,
  Link2,
  Loader2,
  ShieldCheck,
  SlidersHorizontal,
  Users,
} from "lucide-react";
import {
  api,
  ApiError,
  type AssistantStatus,
  type CaptureRequestItem,
} from "@/lib/api";
import { newIdempotencyKey } from "@/lib/media-time";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useShell } from "./shell-context";

const MEET_LINK =
  /^(https?:\/\/)?meet\.google\.com\/(meet\/)?[a-z]{3}-[a-z]{4}-[a-z]{3}/i;
// Loose on purpose: the many Teams forms (Outlook-wrapped ones too) are checked
// by the server, which says what's wrong with a link it can't use.
const TEAMS_LINK =
  /^(https?:\/\/)?([\w-]+\.)*(teams\.microsoft\.com|teams\.live\.com|teams\.cloud\.microsoft|safelinks\.protection\.outlook\.com)\//i;

export function SendNotetakerDialog() {
  const { notetakerOpen, closeNotetaker, notetakerPrefill, refreshCaptures } =
    useShell();
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [meetingUrl, setMeetingUrl] = useState("");
  const [title, setTitle] = useState("");
  const [template, setTemplate] = useState("auto");
  const [showOptions, setShowOptions] = useState(false);
  const [consent, setConsent] = useState(false);
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CaptureRequestItem | null>(null);

  useEffect(() => {
    if (!notetakerOpen) return;
    setMeetingUrl(notetakerPrefill);
    setTitle("");
    setTemplate("auto");
    setShowOptions(false);
    setConsent(false);
    setError(null);
    setResult(null);
    setKey(newIdempotencyKey());
    api
      .getAssistantStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, [notetakerOpen, notetakerPrefill]);

  const linkLooksValid =
    MEET_LINK.test(meetingUrl.trim()) || TEAMS_LINK.test(meetingUrl.trim());
  const capture = status?.capture;

  async function pasteFromClipboard() {
    try {
      const text = await navigator.clipboard.readText();
      if (text.trim()) {
        setMeetingUrl(text.trim());
        setError(null);
      }
    } catch {
      setError(
        "Clipboard access was blocked. Paste the meeting link in the field instead.",
      );
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!linkLooksValid || !consent) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.createCaptureRequest({
        meetingUrl: meetingUrl.trim(),
        title: title.trim(),
        template,
        consentAcknowledged: consent,
        idempotencyKey: key,
      });
      await refreshCaptures();
      // Worth a word when it isn't the plain case: a colleague already has the
      // notetaker on it, or every notetaker is busy and this one is queued.
      setResult(created);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The notetaker could not be sent. Check the link and try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={notetakerOpen}
      onOpenChange={(open) => !open && !busy && closeNotetaker()}
    >
      <DialogContent className="rounded-2xl p-6 sm:max-w-md">
        {result ? (
          <div className="grid gap-4">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                {result.joined_existing ? (
                  <Users className="h-4 w-4 text-primary" />
                ) : (
                  <CheckCircle2 className="h-4 w-4 text-primary" />
                )}
                {result.joined_existing
                  ? "You’re included"
                  : result.queue_position
                    ? "In the queue"
                    : "Wilco is on the way"}
              </DialogTitle>
              <DialogDescription>
                {result.joined_existing
                  ? "A teammate already invited Wilco. You’ll get the same notes."
                  : result.queue_position
                    ? `${result.queue_position} ahead of you. Wilco will join when a notetaker is free.`
                    : "Admit Wilco from your meeting’s waiting room. You can follow its status in Meetings."}
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button onClick={closeNotetaker}>Done</Button>
            </DialogFooter>
          </div>
        ) : (
          <form onSubmit={submit} className="grid gap-5">
            <DialogHeader>
              <DialogTitle className="text-2xl tracking-tight">
                Bring Wilco along.
              </DialogTitle>
              <DialogDescription>
                Admit Wilco to your call. Leave with notes and next steps.
              </DialogDescription>
            </DialogHeader>

            {capture && !capture.configured && (
              <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-foreground">
                The notetaker isn&apos;t set up on this server yet. Ask an admin
                to configure it.
              </p>
            )}
            {capture?.configured && !capture.online && (
              <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-foreground">
                The notetaker hasn&apos;t checked in recently. Your request will
                wait in the queue and time out if nothing picks it up.
              </p>
            )}

            <div className="flex flex-col gap-2">
              <Label
                htmlFor="notetaker-url"
                className="mb-2 flex items-center gap-2 text-sm font-medium"
              >
                <Link2 className="size-4 text-primary" /> Meeting link
              </Label>
              <div className="flex gap-2">
                <Input
                  id="notetaker-url"
                  value={meetingUrl}
                  onChange={(event) => setMeetingUrl(event.target.value)}
                  placeholder="Paste a Meet or Teams link"
                  inputMode="url"
                  autoFocus
                  aria-invalid={meetingUrl.trim().length > 0 && !linkLooksValid}
                  aria-describedby={
                    meetingUrl.trim() && !linkLooksValid
                      ? "notetaker-link-error"
                      : undefined
                  }
                  className="bg-background"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  onClick={() => void pasteFromClipboard()}
                  aria-label="Paste meeting link from clipboard"
                  title="Paste from clipboard"
                >
                  <Clipboard className="size-4" />
                </Button>
              </div>
              {meetingUrl.trim() && !linkLooksValid && (
                <p
                  id="notetaker-link-error"
                  className="text-xs text-destructive"
                >
                  Use a Google Meet or Microsoft Teams link.
                </p>
              )}
            </div>

            <label className="flex items-start gap-2.5 rounded-lg border bg-muted/40 p-3 text-sm">
              <Checkbox
                checked={consent}
                onCheckedChange={(value) => setConsent(value === true)}
                className="mt-0.5"
              />
              <span>
                <span className="flex items-center gap-1.5 font-medium">
                  <ShieldCheck className="size-3.5 text-primary" /> I’ve told
                  everyone it will record
                </span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  You can stop Wilco at any time.
                </span>
              </span>
            </label>
            <div>
              <button
                type="button"
                onClick={() => setShowOptions((open) => !open)}
                aria-expanded={showOptions}
                aria-controls="notetaker-options"
                className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                <SlidersHorizontal className="size-3.5" /> Options
              </button>
              {showOptions && (
                <div
                  id="notetaker-options"
                  className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2"
                >
                  <div className="grid gap-1.5">
                    <Label htmlFor="notetaker-title">Title</Label>
                    <Input
                      id="notetaker-title"
                      value={title}
                      onChange={(event) => setTitle(event.target.value)}
                      placeholder="Optional"
                    />
                  </div>
                  <div className="grid gap-1.5">
                    <Label htmlFor="notetaker-template">Notes style</Label>
                    <select
                      id="notetaker-template"
                      value={template}
                      onChange={(event) => setTemplate(event.target.value)}
                      className="h-8 rounded-lg border bg-background px-2.5 text-sm"
                    >
                      {(
                        status?.templates ?? [
                          { id: "auto", label: "Detect automatically" },
                        ]
                      ).map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              )}
            </div>
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={closeNotetaker}
                disabled={busy}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={
                  !linkLooksValid ||
                  !consent ||
                  busy ||
                  capture?.configured === false
                }
              >
                {busy ? <Loader2 className="animate-spin" /> : <Bot />}
                Invite Wilco <ArrowRight className="size-4" />
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
