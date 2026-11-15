"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type CalendarEventItem } from "@/lib/api";
import { ListenInLanguage } from "@/components/listen-in-language";

export function StandupCatchup() {
  const [standup, setStandup] = useState<Awaited<ReturnType<typeof api.latestStandup>>["standup"]>(null);
  useEffect(() => {
    let active = true;
    api.latestStandup().then((value) => { if (active) setStandup(value.standup); }).catch(() => {});
    return () => { active = false; };
  }, []);
  if (!standup) return null;
  return <section className="flex flex-col gap-3 rounded-xl border bg-card p-4" aria-label="Spoken stand-up digest">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-sm font-semibold">Missed stand-up?</h2>
      <Link href={`/meetings/${standup.meeting_id}#standup`} className="text-xs text-primary hover:underline">
        {standup.title} · {new Date(standup.date).toLocaleDateString(undefined, { day: "numeric", month: "short" })}
      </Link>
    </div>
    <ListenInLanguage text={standup.text} listenLabel="Catch me up" share={false} />
  </section>;
}


export function UpcomingVoiceBriefs() {
  const [events, setEvents] = useState<CalendarEventItem[]>([]);
  useEffect(() => {
    let active = true;
    function refresh() {
      api.listCalendarEvents(2).then((items) => {
        if (active) setEvents(items.filter((event) => event.brief?.status === "ready" && !!event.brief.text && Date.parse(event.end_at) > Date.now()));
      }).catch(() => {});
    }
    refresh();
    const timer = window.setInterval(refresh, 60_000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  return <>{events.slice(0, 2).map((event) => <section key={event.id} id={`brief-${event.id}`} className="flex flex-col gap-3 rounded-xl border bg-card p-4" aria-label={`Voice brief for ${event.title}`}>
    <h2 className="text-sm font-semibold">{event.title} · {new Date(event.start_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}</h2>
    <ListenInLanguage text={[event.brief!.text!.replace(/\[M\d+\]/g, ""), ...event.brief!.open_tasks.map((task) => `Open item: ${task.description}. Owner: ${task.owner || "not stated"}.`)].join(" ").slice(0, 6000)} listenLabel="Listen to your brief" share={false} />
  </section>)}</>;
}
