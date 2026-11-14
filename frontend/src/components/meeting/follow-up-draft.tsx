"use client";

import { useState } from "react";
import { Check, Copy, Mail } from "lucide-react";
import type { MeetingAttendee, MeetingDecision, MeetingTask } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** The draft starts with "Subject: …" when the model wrote one. */
function splitDraft(draft: string): { subject: string; body: string } {
  const match = draft.match(/^Subject:\s*(.+)\n+([\s\S]*)$/);
  return match ? { subject: match[1].trim(), body: match[2].trim() } : { subject: "", body: draft.trim() };
}

const ACTION_HEADING = /^\s*(action items|tasks|next steps)\s*:?\s*$/i;
const DECISION_HEADING = /^\s*(key decisions|decisions|decisions made)\s*:?\s*$/i;
const LIST_ITEM = /^\s*([-*•]|\d+[.)])\s+/;
const SIGN_OFF = /^\s*(best|thanks|thank you|regards|warm regards|kind regards|cheers)\b/i;

function taskLine(task: MeetingTask): string {
  const due = task.deadline || task.due_date;
  return `- ${task.owner ? `${task.owner}: ` : ""}${task.description}${due ? ` (due ${due})` : ""}${task.status === "done" ? " (done)" : ""}`;
}

/** Swap the list under a heading for `items`; false when the heading isn't there. */
function replaceList(lines: string[], heading: RegExp, items: string[]): boolean {
  const start = lines.findIndex((line) => heading.test(line));
  if (start < 0) return false;
  let end = start + 1;
  while (end < lines.length && (LIST_ITEM.test(lines[end]) || (end === start + 1 && !lines[end].trim()))) end += 1;
  lines.splice(start, end - start, ...(items.length ? [lines[start], ...items] : []));
  return true;
}

/** The AI writes the draft once, but tasks and decisions get edited after
 * that. Its "Action Items" and "Decisions" lists are rebuilt from the
 * meeting's current tasks and decisions, so an edit anywhere shows here too. */
export function liveDraft(draft: string, tasks: MeetingTask[], decisions: MeetingDecision[]): string {
  const lines = draft.split("\n");
  replaceList(lines, DECISION_HEADING, decisions.map((decision) => `- ${decision.decision}`));
  if (!replaceList(lines, ACTION_HEADING, tasks.map(taskLine)) && tasks.length) {
    let at = lines.findLastIndex((line) => SIGN_OFF.test(line));
    if (at < 0) at = lines.length;
    lines.splice(at, 0, "Action Items:", ...tasks.map(taskLine), "");
  }
  return lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

/** The AI follow-up email, addressed to the meeting's invitees. Wilco never
 * sends it: it opens in Gmail (or the default mail app) for the person to
 * review and send from their own account. */
export function FollowUpDraft({ draft: aiDraft, title, attendees, tasks, decisions }: { draft: string; title: string; attendees: MeetingAttendee[]; tasks: MeetingTask[]; decisions: MeetingDecision[] }) {
  const draft = liveDraft(aiDraft, tasks, decisions);
  const { user } = useAuth();
  const [copied, setCopied] = useState(false);
  const own = user?.email.toLowerCase();
  const recipients = [
    ...new Set(
      attendees
        .map((person) => person.email?.trim().toLowerCase())
        .filter((email): email is string => !!email && email !== own),
    ),
  ];
  const { subject: draftSubject, body } = splitDraft(draft);
  const subject = draftSubject || `Follow-up: ${title}`;
  const to = recipients.join(",");
  const gmail = `https://mail.google.com/mail/?${new URLSearchParams({ view: "cm", fs: "1", to, su: subject, body })}`;
  const mailto = `mailto:${recipients.map(encodeURIComponent).join(",")}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;

  async function copy() {
    await navigator.clipboard.writeText(draft);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2_000);
  }

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2 text-base"><Mail className="h-4 w-4 text-primary" /> Follow-up draft</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            {recipients.length > 0
              ? `To ${recipients.length} invitee${recipients.length === 1 ? "" : "s"}. `
              : "No invitee email addresses on this meeting. "}
            Review it and send it yourself — Wilco never emails attendees.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <a href={gmail} target="_blank" rel="noopener noreferrer" className={cn(buttonVariants({ size: "sm" }))} title={recipients.join(", ")}>
            <Mail className="h-3.5 w-3.5" /> Open in Gmail
          </a>
          <a href={mailto} className={cn(buttonVariants({ size: "sm", variant: "outline" }))}>
            Mail app
          </a>
          <Button size="sm" variant="outline" onClick={() => void copy()}>
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {recipients.length > 0 && (
          <p className="truncate text-xs text-muted-foreground" title={recipients.join(", ")}>
            <span className="font-medium text-foreground">To:</span> {recipients.join(", ")}
          </p>
        )}
        <p className="whitespace-pre-wrap rounded-md bg-muted/40 p-3 text-sm">{draft}</p>
      </CardContent>
    </Card>
  );
}
