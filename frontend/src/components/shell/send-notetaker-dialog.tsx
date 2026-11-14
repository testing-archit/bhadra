"use client";

import { useEffect, useState } from "react";
import { Bot, CheckCircle2, Loader2, Users } from "lucide-react";
import { api, ApiError, type AssistantStatus, type CaptureRequestItem } from "@/lib/api";
import { newIdempotencyKey } from "@/lib/media-time";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useShell } from "./shell-context";

const MEET_LINK = /^(https?:\/\/)?meet\.google\.com\/(meet\/)?[a-z]{3}-[a-z]{4}-[a-z]{3}/i;
// Loose on purpose: the many Teams forms (Outlook-wrapped ones too) are checked
// by the server, which says what's wrong with a link it can't use.
const TEAMS_LINK = /^(https?:\/\/)?([\w-]+\.)*(teams\.microsoft\.com|teams\.live\.com|teams\.cloud\.microsoft|safelinks\.protection\.outlook\.com)\//i;

export function SendNotetakerDialog() {
  const { notetakerOpen, closeNotetaker, notetakerPrefill, refreshCaptures } = useShell();
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [meetingUrl, setMeetingUrl] = useState("");
  const [title, setTitle] = useState("");
  const [template, setTemplate] = useState("auto");
  const [consent, setConsent] = useState(false);
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CaptureRequestItem | null>(null);

  useEffect(() => {
    if (!notetakerOpen) return;
    setMeetingUrl(notetakerPrefill);
    setTitle("");
    setConsent(false);
    setError(null);
    setResult(null);
    setKey(newIdempotencyKey());
    if (!status) api.getAssistantStatus().then(setStatus).catch(() => setStatus(null));
  }, [notetakerOpen, notetakerPrefill, status]);

  const linkLooksValid = MEET_LINK.test(meetingUrl.trim()) || TEAMS_LINK.test(meetingUrl.trim());
  const capture = status?.capture;

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
      if (created.joined_existing || created.queue_position) setResult(created);
      else closeNotetaker();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The notetaker could not be sent. Check the link and try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={notetakerOpen} onOpenChange={(open) => !open && !busy && closeNotetaker()}>
      <DialogContent className="sm:max-w-md">
        {result ? (
          <div className="grid gap-4">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                {result.joined_existing ? <Users className="h-4 w-4 text-primary" /> : <CheckCircle2 className="h-4 w-4 text-primary" />}
                {result.joined_existing ? "Already being recorded" : "In the queue"}
              </DialogTitle>
              <DialogDescription>
                {result.joined_existing
                  ? `${result.requested_by ?? "A colleague"} already sent the notetaker to this meeting, so it's recorded once for everyone. You'll get the notes too.`
                  : `All notetakers are in other meetings right now (${result.queue_position} ahead). It will join as soon as one is free.`}
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button onClick={closeNotetaker}>Done</Button>
            </DialogFooter>
          </div>
        ) : (
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-primary" /> Send the notetaker
            </DialogTitle>
            <DialogDescription>
              {capture?.bot_name ?? "The Charcha notetaker"} asks to join your Google Meet or Teams call. Admit it from the call, and the
              transcript, notes and tasks appear in Charcha when the meeting ends.
            </DialogDescription>
          </DialogHeader>

          {capture && !capture.configured && (
            <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-foreground">
              The notetaker isn&apos;t set up on this server yet. Ask an admin to configure it.
            </p>
          )}
          {capture?.configured && !capture.online && (
            <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-foreground">
              The notetaker hasn&apos;t checked in recently. Your request will wait in the queue and time out if nothing picks it up.
            </p>
          )}

          <div className="grid gap-1.5">
            <Label htmlFor="notetaker-url">Meeting link</Label>
            <Input
              id="notetaker-url"
              value={meetingUrl}
              onChange={(event) => setMeetingUrl(event.target.value)}
              placeholder="Google Meet or Microsoft Teams link"
              inputMode="url"
              autoFocus
              aria-invalid={meetingUrl.trim().length > 0 && !linkLooksValid}
            />
            {meetingUrl.trim() && !linkLooksValid && (
              <p className="text-xs text-destructive">Paste a Google Meet or Microsoft Teams meeting link.</p>
            )}
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor="notetaker-title">Title</Label>
              <Input id="notetaker-title" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Optional" />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="notetaker-template">Notes style</Label>
              <select
                id="notetaker-template"
                value={template}
                onChange={(event) => setTemplate(event.target.value)}
                className="h-8 rounded-lg border bg-background px-2.5 text-sm"
              >
                {(status?.templates ?? [{ id: "auto", label: "Detect automatically" }]).map((item) => (
                  <option key={item.id} value={item.id}>{item.label}</option>
                ))}
              </select>
            </div>
          </div>
          <label className="flex items-start gap-2.5 rounded-lg border bg-muted/40 p-3 text-sm">
            <Checkbox checked={consent} onCheckedChange={(value) => setConsent(value === true)} className="mt-0.5" />
            <span>
              Everyone in the call will know a notetaker is recording.
              <span className="mt-0.5 block text-xs text-muted-foreground">Anyone can say &ldquo;notetaker please leave&rdquo;, and you can stop it from Charcha at any time.</span>
            </span>
          </label>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={closeNotetaker} disabled={busy}>Cancel</Button>
            <Button type="submit" disabled={!linkLooksValid || !consent || busy || capture?.configured === false}>
              {busy ? <Loader2 className="animate-spin" /> : <Bot />}
              Send notetaker
            </Button>
          </DialogFooter>
        </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
