"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, ApiError, SharedMeeting } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { FormattedSummary } from "@/components/formatted-summary";
import { STATUS_LABELS } from "@/lib/labels";
import {
  ArrowRight, CalendarDays, CircleHelp, Clock, Lightbulb, ListChecks, MessagesSquare, NotebookText, Scale, ShieldAlert,
  type LucideIcon,
} from "lucide-react";

function ListCard({ title, icon: Icon, items }: { title: string; icon: LucideIcon; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon className="h-4 w-4 text-primary" /> {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {items.map((item) => <p key={item} className="text-sm">• {item}</p>)}
      </CardContent>
    </Card>
  );
}

export default function SharedMeetingPage() {
  const { token } = useParams<{ token: string }>();
  const [meeting, setMeeting] = useState<SharedMeeting | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getSharedMeeting(token)
      .then((data) => {
        if (!cancelled) setMeeting(data);
      })
      .catch((cause) => {
        if (cancelled) return;
        setError(
          cause instanceof ApiError && cause.status === 404
            ? "This link is invalid or has been revoked."
            : "This meeting could not be loaded."
        );
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const empty = meeting !== null && !meeting.summary && !meeting.template_sections.length && !meeting.sections.length
    && !meeting.tasks.length && !meeting.decisions.length && !meeting.risks.length && !meeting.next_steps.length;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-10">
      <div className="flex items-center gap-2">
        <img src="/wilco-mark.png" alt="Wilco" className="h-8 w-8 rounded-lg" />
        <span className="text-sm font-semibold tracking-tight text-muted-foreground">
          Shared via Wilco
        </span>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {!error && !meeting && (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-40 w-full" />
        </div>
      )}

      {meeting && (
        <>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{meeting.title}</h1>
            <p className="mt-1 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
              <span className="flex items-center gap-1">
                <CalendarDays className="h-3.5 w-3.5" />
                {new Date(meeting.date).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
              </span>
              {meeting.duration_minutes > 0 && (
                <span className="flex items-center gap-1">
                  <Clock className="h-3.5 w-3.5" />
                  {meeting.duration_minutes} min
                </span>
              )}
            </p>
            {meeting.key_topics.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {meeting.key_topics.map((topic) => <Badge key={topic} variant="secondary">{topic}</Badge>)}
              </div>
            )}
          </div>

          {empty && (
            <Card>
              <CardContent className="py-6 text-sm text-muted-foreground">
                The notes for this meeting aren&apos;t ready yet, or nothing was captured. Check back in a little while.
              </CardContent>
            </Card>
          )}

          {meeting.summary && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <NotebookText className="h-4 w-4 text-primary" /> Overview
                </CardTitle>
              </CardHeader>
              <CardContent>
                <FormattedSummary summary={meeting.summary} />
              </CardContent>
            </Card>
          )}

          {meeting.template_sections.length > 0 && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {meeting.template_sections.map((block) => (
                <Card key={block.heading}>
                  <CardHeader><CardTitle className="text-base">{block.heading}</CardTitle></CardHeader>
                  <CardContent className="flex flex-col gap-2.5">
                    {block.items.map((item, index) => (
                      <p key={index} className="text-sm">
                        {item.person && <span className="font-medium">{item.person}: </span>}
                        {item.text}
                      </p>
                    ))}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {meeting.tasks.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <ListChecks className="h-4 w-4 text-primary" /> Tasks
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                {meeting.tasks.map((task, index) => (
                  <div key={index} className="flex flex-col gap-1 border-b pb-3 last:border-0 last:pb-0">
                    <p className="text-sm">{task.description}</p>
                    <div className="flex flex-wrap gap-2">
                      {task.owner && <Badge variant="outline">{task.owner}</Badge>}
                      {task.deadline && <Badge variant="outline">{task.deadline}</Badge>}
                      <Badge variant="outline">{STATUS_LABELS[task.status] ?? task.status}</Badge>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {meeting.decisions.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Scale className="h-4 w-4 text-primary" /> Decisions
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                {meeting.decisions.map((decision, index) => (
                  <div key={index} className="flex flex-col gap-1 border-b pb-3 last:border-0 last:pb-0">
                    <p className="text-sm font-medium">{decision.decision}</p>
                    {decision.reason && <p className="text-sm text-muted-foreground">{decision.reason}</p>}
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {meeting.sections.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <MessagesSquare className="h-4 w-4 text-primary" /> Discussion, in order
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                {meeting.sections.map((section, index) => (
                  <div key={`${section.title}-${index}`}>
                    <p className="text-sm font-medium">{section.title}</p>
                    {section.summary && <p className="mt-0.5 text-sm text-muted-foreground">{section.summary}</p>}
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {(meeting.next_steps.length > 0 || meeting.open_questions.length > 0 || meeting.highlights.length > 0) && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <ListCard title="Next steps" icon={ArrowRight} items={meeting.next_steps} />
              <ListCard title="Open questions" icon={CircleHelp} items={meeting.open_questions} />
              <ListCard title="Highlights" icon={Lightbulb} items={meeting.highlights} />
            </div>
          )}

          {meeting.risks.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <ShieldAlert className="h-4 w-4 text-primary" /> Risks
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                {meeting.risks.map((risk, index) => (
                  <div key={index} className="flex flex-col gap-1 border-b pb-3 last:border-0 last:pb-0">
                    <p className="text-sm">{risk.description}</p>
                    {risk.severity && <Badge variant="outline">{risk.severity}</Badge>}
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          <p className="pt-2 text-center text-xs text-muted-foreground">
            Notes written by Wilco from the meeting. They may contain mistakes.
          </p>
        </>
      )}
    </div>
  );
}
