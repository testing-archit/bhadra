"use client";

import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type AiCostReport, type AiCostGroup } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const FEATURE_LABELS: Record<string, string> = {
  meeting_notes: "Meeting notes",
  detailed_summary: "Detailed summaries",
  memory_chat: "Company memory chat",
  meeting_chat: "Ask about a meeting",
  live_translation: "Live call translation",
  decision_conflicts: "Decision conflict checks",
  policy_assistant: "Policy assistant",
  pre_meeting_brief: "Pre-meeting briefs",
  meeting_prep: "Meeting prep",
  series_review: "Recurring-meeting review",
  meeting_type: "Meeting type detection",
  transcription: "Transcription (Gnani Prisma)",
  other: "Other",
};

const inr = (value: number) =>
  value < 1 ? `₹${value.toFixed(2)}` : `₹${value.toLocaleString("en-IN", { maximumFractionDigits: value < 100 ? 2 : 0 })}`;
const usd = (value: number) => `$${value < 1 ? value.toFixed(4) : value.toFixed(2)}`;
const compact = (value: number) => new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(value);

/** AI spend from the usage ledger: every Gemini and Gnani Prisma call, priced in
 * USD and converted at the exchange rate in force when it happened. */
export function AdminAiCosts() {
  const [days, setDays] = useState(30);
  const [report, setReport] = useState<AiCostReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setReport(null);
    api
      .adminAiCosts(days)
      .then(setReport)
      .catch((cause) => setError(cause instanceof ApiError ? cause.message : "AI spend couldn't be loaded."));
  }, [days]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">AI spend</h2>
          <p className="text-sm text-muted-foreground">Each call is priced when it happens, at that moment&apos;s USD→INR rate.</p>
        </div>
        <div className="flex gap-1 rounded-lg bg-muted p-0.5" role="tablist" aria-label="Period">
          {[7, 30, 90].map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={days === value}
              onClick={() => setDays(value)}
              className={cn("h-7 rounded-md px-3 text-sm text-muted-foreground", days === value && "bg-background font-medium text-foreground shadow-sm")}
            >
              {value} days
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {!report && !error && <Skeleton className="h-96 w-full rounded-xl" />}

      {report && (
        <>
          <div className="grid grid-cols-1 gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-2 lg:grid-cols-4">
            <Tile label={`Spent, last ${report.days} days`} value={inr(report.totals.inr)} note={usd(report.totals.usd)} />
            <Tile label="AI calls" value={compact(report.totals.calls)} note={report.totals.calls ? `${inr(report.totals.inr / report.totals.calls)} each on average` : "None yet"} />
            <Tile label="Tokens" value={compact(report.totals.input_tokens + report.totals.output_tokens)} note={`${compact(report.totals.cached_tokens)} served from cache`} />
            <Tile label="Audio transcribed" value={`${report.totals.audio_minutes} min`} note={`USD→INR now ${report.rate_now.usd_to_inr.toFixed(2)} (${report.rate_now.source})`} />
          </div>

          <DailyChart rows={report.by_day} />

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
            <Ranked title="By feature" rows={report.by_feature} label={(key) => FEATURE_LABELS[key ?? ""] ?? key ?? "Other"} />
            <Ranked title="By model" rows={report.by_model} label={(key) => key ?? "Unknown"} />
            <Ranked title="By person" rows={report.by_user} label={(_, row) => row.label ?? "System"} />
          </div>

          <div className="rounded-xl border bg-card">
            <div className="flex flex-wrap items-baseline justify-between gap-2 border-b px-4 py-3">
              <h3 className="font-medium">Recent calls</h3>
              <p className="text-xs text-muted-foreground">
                Pricing: {report.prices.model_in_use}
                {report.prices.overridden.length
                  ? `, custom prices for ${report.prices.overridden.join(", ")}`
                  : `, Google's published prices (${report.prices.source ?? "default table"})`}
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2 font-medium">When</th>
                    <th className="font-medium">Feature</th>
                    <th className="font-medium">Model</th>
                    <th className="font-medium">Usage</th>
                    <th className="font-medium">Rate</th>
                    <th className="pr-4 text-right font-medium">Cost</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {report.recent.map((row, index) => (
                    <tr key={`${row.occurred_at}-${index}`}>
                      <td className="px-4 py-2 text-muted-foreground tabular-nums">
                        {new Date(row.occurred_at).toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}
                      </td>
                      <td>{FEATURE_LABELS[row.feature] ?? row.feature}</td>
                      <td className="text-muted-foreground">{row.model}</td>
                      <td className="text-muted-foreground tabular-nums">
                        {row.audio_seconds ? `${Math.round(row.audio_seconds / 60)} min audio` : `${compact(row.input_tokens)} in, ${compact(row.output_tokens)} out`}
                      </td>
                      <td className="text-muted-foreground tabular-nums" title={row.rate_source ?? undefined}>{row.usd_to_inr.toFixed(2)}</td>
                      <td className="pr-4 text-right tabular-nums">
                        {inr(row.inr)} <span className="text-xs text-muted-foreground">{usd(row.usd)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {report.recent.length === 0 && <p className="p-8 text-center text-sm text-muted-foreground">No AI calls recorded yet.</p>}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Tile({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      <p className="mt-0.5 truncate text-xs text-muted-foreground">{note}</p>
    </div>
  );
}

function DailyChart({ rows }: { rows: AiCostReport["by_day"] }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = useMemo(() => Math.max(...rows.map((row) => row.inr), 0), [rows]);
  if (!rows.length) return null;
  const active = hover !== null ? rows[hover] : null;
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3 className="font-medium">Spend per day</h3>
        <p className="text-sm text-muted-foreground tabular-nums">
          {active
            ? `${new Date(active.day).toLocaleDateString(undefined, { day: "numeric", month: "short" })}: ${inr(active.inr)}, ${active.calls} call${active.calls === 1 ? "" : "s"}`
            : `Highest ${inr(max)}`}
        </p>
      </div>
      <div className="flex h-36 items-end gap-0.5 border-b" onMouseLeave={() => setHover(null)}>
        {rows.map((row, index) => (
          <button
            key={row.day}
            type="button"
            className="group flex h-full flex-1 items-end focus-visible:outline-none"
            onMouseEnter={() => setHover(index)}
            onFocus={() => setHover(index)}
            aria-label={`${row.day}: ${inr(row.inr)}`}
          >
            <span
              className={cn("block w-full rounded-t-[4px] bg-primary/70 transition-colors group-hover:bg-primary", hover === index && "bg-primary")}
              style={{ height: `${max ? Math.max(2, (row.inr / max) * 100) : 0}%` }}
            />
          </button>
        ))}
      </div>
      <div className="mt-1.5 flex justify-between text-xs text-muted-foreground tabular-nums">
        <span>{new Date(rows[0].day).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</span>
        <span>{new Date(rows[rows.length - 1].day).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</span>
      </div>
    </div>
  );
}

function Ranked({ title, rows, label }: { title: string; rows: AiCostGroup[]; label: (key: string | null, row: AiCostGroup) => string }) {
  const max = Math.max(...rows.map((row) => row.inr), 0);
  return (
    <div className="rounded-xl border bg-card p-4">
      <h3 className="mb-3 font-medium">{title}</h3>
      {rows.length === 0 && <p className="text-sm text-muted-foreground">Nothing yet.</p>}
      <ul className="flex flex-col gap-2.5">
        {rows.slice(0, 8).map((row) => (
          <li key={row.key ?? "none"} title={`${row.calls} calls, ${usd(row.usd)}`}>
            <div className="flex items-baseline justify-between gap-2 text-sm">
              <span className="truncate">{label(row.key, row)}</span>
              <span className="shrink-0 tabular-nums">{inr(row.inr)}</span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary/70" style={{ width: `${max ? Math.max(2, (row.inr / max) * 100) : 0}%` }} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
