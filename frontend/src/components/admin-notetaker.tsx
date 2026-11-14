"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Bot, CircleCheck, Clock, Radio, Server } from "lucide-react";
import { api, ApiError, type NotetakerInstance, type NotetakerOverview, type NotetakerVisit } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const REFRESH_MS = 15_000;

function ago(value: string | null) {
  if (!value) return "never";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)} h ago`;
  const days = Math.round(seconds / 86_400);
  if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;
  return new Date(value).toLocaleDateString();
}

const SOURCE_LABELS: Record<NotetakerVisit["source"], string> = { link: "Link", calendar: "Calendar", invite: "Invite" };

/** The notetaker fleet across the organisation: who's in which meeting,
 * what's waiting, how much room there is, and why visits failed. */
export function AdminNotetaker() {
  const [data, setData] = useState<NotetakerOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .adminNotetaker()
      .then((value) => {
        setData(value);
        setError(null);
      })
      .catch((cause) => setError(cause instanceof ApiError ? cause.message : "The notetaker status couldn't be loaded."));
  }, []);

  useEffect(() => {
    load();
    const handle = window.setInterval(() => document.visibilityState === "visible" && load(), REFRESH_MS);
    return () => window.clearInterval(handle);
  }, [load]);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">Notetaker</h2>
        <p className="text-sm text-muted-foreground">Every visit across the organisation. Refreshes every 15 seconds.</p>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {!data && !error && <Skeleton className="h-96 w-full rounded-xl" />}

      {data && (
        <>
          <div className="grid grid-cols-1 gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-2 lg:grid-cols-4">
            <Tile
              label="Status"
              value={data.online ? "Online" : "Offline"}
              note={`Last check-in ${ago(data.last_heartbeat_at)}`}
              tone={data.online ? "ok" : "bad"}
            />
            <Tile
              label="In meetings"
              value={data.capacity.known ? `${data.capacity.active} of ${data.capacity.total}` : String(data.live.length)}
              note={data.capacity.known ? `${data.capacity.free} free right now` : "Capacity not reported by this notetaker version"}
            />
            <Tile label="Queued" value={String(data.queue_length)} note={data.queue_length ? "Waiting for a free notetaker" : "Nothing waiting"} tone={data.queue_length ? "warn" : undefined} />
            <Tile
              label={`Failed, last ${data.failures.days} days`}
              value={String(data.failures.total)}
              note={data.failures.visits ? `of ${data.failures.visits} visits` : "No visits yet"}
              tone={data.failures.total ? "warn" : undefined}
            />
          </div>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <VisitList title="Live" icon={Radio} visits={data.live} empty="No notetaker is in a meeting." />
            <VisitList title="Queue" icon={Clock} visits={data.queued} empty="Nothing is waiting." queue />
          </div>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <section className="rounded-xl border bg-card">
              <h3 className="flex items-center gap-2 border-b px-4 py-3 text-sm font-semibold"><Server className="size-4 text-primary" /> Notetakers</h3>
              {data.instances.length === 0 ? (
                <p className="px-4 py-6 text-center text-sm text-muted-foreground">No notetaker has checked in recently.</p>
              ) : (
                <div className="divide-y">{data.instances.map((item) => <InstanceRow key={item.name} item={item} />)}</div>
              )}
            </section>

            <section className="rounded-xl border bg-card">
              <h3 className="flex items-center gap-2 border-b px-4 py-3 text-sm font-semibold"><AlertTriangle className="size-4 text-warning" /> Why visits failed</h3>
              {data.failures.groups.length === 0 ? (
                <p className="flex items-center justify-center gap-2 px-4 py-6 text-sm text-muted-foreground"><CircleCheck className="size-4" /> No failures in the last {data.failures.days} days.</p>
              ) : (
                <div className="divide-y">
                  {data.failures.groups.map((group) => (
                    <div key={group.reason} className="flex gap-3 px-4 py-3">
                      <span className="w-8 shrink-0 text-right text-lg font-semibold tabular-nums">{group.count}</span>
                      <div className="min-w-0">
                        <p className="text-sm font-medium">{group.label}</p>
                        {group.example && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{group.example}</p>}
                        <p className="mt-0.5 text-xs text-muted-foreground">Last {ago(group.last_at)}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>

          <section className="rounded-xl border border-dashed p-4 text-sm">
            <h3 className="flex items-center gap-2 font-semibold"><Bot className="size-4 text-primary" /> Adding capacity</h3>
            <p className="mt-1 text-muted-foreground">
              Each meeting is a full browser (about 700 MB of memory), so one notetaker holds a few meetings at most. To record more at
              once, run another notetaker container anywhere that can reach Charcha — a second VM or a spot instance — with the same{" "}
              <code className="rounded bg-muted px-1 font-mono text-xs">BOT_API_SECRET</code>,{" "}
              <code className="rounded bg-muted px-1 font-mono text-xs">BACKEND_URL</code> and Google sign-in. Visits are claimed with{" "}
              <code className="rounded bg-muted px-1 font-mono text-xs">SKIP LOCKED</code>, so two notetakers never take the same meeting. Give
              each a <code className="rounded bg-muted px-1 font-mono text-xs">NOTETAKER_INSTANCE_NAME</code> to tell them apart here, and
              raise <code className="rounded bg-muted px-1 font-mono text-xs">MAX_CONCURRENT_MEETINGS</code> only on machines with the memory.
            </p>
          </section>
        </>
      )}
    </div>
  );
}

function Tile({ label, value, note, tone }: { label: string; value: string; note: string; tone?: "ok" | "warn" | "bad" }) {
  return (
    <div className="bg-card p-5">
      <p className="text-[10px] font-semibold tracking-[.14em] text-muted-foreground uppercase">{label}</p>
      <p className={cn("mt-3 text-2xl font-semibold tracking-tight", tone === "bad" && "text-destructive", tone === "ok" && "text-success")}>{value}</p>
      <p className={cn("mt-1 text-xs text-muted-foreground", tone === "warn" && "text-warning")}>{note}</p>
    </div>
  );
}

function VisitList({ title, icon: Icon, visits, empty, queue = false }: { title: string; icon: typeof Radio; visits: NotetakerVisit[]; empty: string; queue?: boolean }) {
  return (
    <section className="rounded-xl border bg-card">
      <h3 className="flex items-center gap-2 border-b px-4 py-3 text-sm font-semibold">
        <Icon className="size-4 text-primary" /> {title}
        <span className="text-xs font-normal text-muted-foreground">{visits.length}</span>
      </h3>
      {visits.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-muted-foreground">{empty}</p>
      ) : (
        <div className="divide-y">
          {visits.map((visit, index) => (
            <div key={visit.id} className="flex items-start gap-3 px-4 py-3">
              {queue && <span className="mt-0.5 w-5 shrink-0 text-xs text-muted-foreground tabular-nums">#{index + 1}</span>}
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{visit.title}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {visit.status_label} · {SOURCE_LABELS[visit.source] ?? visit.source} · {visit.requested_by}
                  {visit.subscribers > 1 && ` +${visit.subscribers - 1}`}
                </p>
              </div>
              <span className="shrink-0 text-xs text-muted-foreground">
                {queue ? `waiting ${ago(visit.scheduled_start ?? visit.created_at).replace(" ago", "")}` : `since ${ago(visit.claimed_at).replace(" ago", "")}`}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function InstanceRow({ item }: { item: NotetakerInstance }) {
  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <span className={cn("size-2 shrink-0 rounded-full", item.online ? "bg-success" : "bg-muted-foreground/40")} />
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-sm">{item.name}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {item.online ? "Online" : "Offline"} · checked in {ago(item.last_seen_at)}
          {item.signed_in === false && <span className="text-warning"> · not signed in to Google</span>}
        </p>
      </div>
      {item.max_concurrent !== null && (
        <span className="shrink-0 text-sm tabular-nums">
          {item.active ?? 0}/{item.max_concurrent} <span className="text-xs text-muted-foreground">meetings</span>
        </span>
      )}
    </div>
  );
}
