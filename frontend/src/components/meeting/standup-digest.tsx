"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ChevronDown, UsersRound } from "lucide-react";
import { api, type StandupDigest } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const shortDate = (value: string) => new Date(value).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });

const ROWS = [
  { key: "updates", label: "Updates" },
  { key: "blockers", label: "Blockers" },
  { key: "plans", label: "Plans" },
] as const;

/** A stand-up series read per person: what each person said across the last
 * five occurrences, and blockers that keep coming back. */
export function StandupDigestPanel({ meetingId }: { meetingId: string }) {
  const [digest, setDigest] = useState<StandupDigest | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    api.getStandupDigest(meetingId).then(setDigest).catch(() => setDigest(null));
  }, [meetingId]);

  if (!digest || digest.people.length === 0) return null;
  const span = digest.occurrences.length;

  return (
    <Card id="standup">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <UsersRound className="h-4 w-4 text-primary" /> Stand-up by person
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          The last {span} stand-up{span === 1 ? "" : "s"}
          {span > 1 && `, ${shortDate(digest.occurrences[0].date)} – ${shortDate(digest.occurrences[span - 1].date)}`}.
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {digest.repeated_blockers.length > 0 && (
          <div className="rounded-lg border border-warning/40 bg-warning/10 p-3">
            <p className="flex items-center gap-1.5 text-sm font-medium">
              <AlertTriangle className="size-4 text-warning" /> Blockers raised more than once
            </p>
            <ul className="mt-2 flex flex-col gap-1.5">
              {digest.repeated_blockers.map((blocker) => (
                <li key={`${blocker.person}-${blocker.first_date}`} className="text-sm">
                  <span className="font-medium">{blocker.person}:</span> {blocker.text}
                  <span className="text-xs text-muted-foreground">
                    {" "}· {blocker.times} stand-ups since {shortDate(blocker.first_date)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="divide-y rounded-lg border">
          {digest.people.map((person) => {
            const expanded = open === person.name;
            const latest = person.occurrences[person.occurrences.length - 1];
            return (
              <div key={person.name}>
                <button
                  type="button"
                  aria-expanded={expanded}
                  onClick={() => setOpen(expanded ? null : person.name)}
                  className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{person.name}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {latest.updates[0] ?? latest.plans[0] ?? latest.blockers[0] ?? "—"}
                    </p>
                  </div>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {person.occurrences.length}/{span}
                    {person.blocker_count > 0 && <span className="ml-2 text-warning">{person.blocker_count} blocker{person.blocker_count === 1 ? "" : "s"}</span>}
                  </span>
                  <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", expanded && "rotate-180")} />
                </button>
                {expanded && (
                  <ol className="flex flex-col gap-3 border-t bg-muted/30 px-3 py-3">
                    {person.occurrences.map((slot) => (
                      <li key={slot.meeting_id} className="grid grid-cols-1 gap-1 sm:grid-cols-[96px_1fr] sm:gap-3">
                        <Link href={`/meetings/${slot.meeting_id}`} className="text-xs font-medium text-primary hover:underline">
                          {shortDate(slot.date)}
                        </Link>
                        <dl className="flex flex-col gap-1">
                          {ROWS.filter((row) => slot[row.key].length > 0).map((row) => (
                            <div key={row.key} className="text-sm">
                              <dt className={cn("inline text-xs font-medium text-muted-foreground", row.key === "blockers" && "text-warning")}>{row.label}: </dt>
                              <dd className="inline">{slot[row.key].join("; ")}</dd>
                            </div>
                          ))}
                        </dl>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
