"use client";

import { EvidenceRef } from "@/lib/api";
import { formatClock } from "@/lib/media-time";
import { AlertTriangle, CalendarClock, Quote } from "lucide-react";

const FLAG_LABELS: Record<string, { label: string; title: string }> = {
  evidence_missing: {
    label: "No supporting quote",
    title: "The AI could not point to a transcript line for this. Check it against the transcript before relying on it.",
  },
  evidence_unverified: {
    label: "Quote not found",
    title: "The quoted words don't appear in the cited line. The line is shown instead — review it.",
  },
  due_date_ambiguous: {
    label: "Ambiguous deadline",
    title: "The stated deadline could mean more than one date, so no calendar date was set.",
  },
};

/** Transcript evidence for one extracted item. A verified quote was found in
 * the cited line — it shows the item is grounded, not that it is correct. */
export function EvidenceChips({
  evidence,
  flags,
  onOpen,
}: {
  evidence?: EvidenceRef[];
  flags?: string[];
  onOpen: (ref: EvidenceRef) => void;
}) {
  const refs = evidence ?? [];
  const shownFlags = (flags ?? []).filter((flag) => FLAG_LABELS[flag]);
  if (!refs.length && !shownFlags.length) return null;
  const first = refs[0];
  return (
    <div className="mt-1.5 flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-1.5">
        {refs.map((ref) => (
          <button
            key={`${ref.segment_id}-${ref.seq}`}
            type="button"
            onClick={() => onOpen(ref)}
            title={ref.verified ? `“${ref.excerpt}”` : `Cited line (quote not found): “${ref.excerpt}”`}
            className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
              ref.verified ? "text-foreground/80" : "border-dashed border-warning/40 text-foreground"
            }`}
          >
            <Quote className="h-3 w-3" />
            {ref.start_ms !== null ? formatClock(ref.start_ms) : `Line ${ref.seq + 1}`}
            <span className="max-w-28 truncate font-normal text-muted-foreground">{ref.speaker}</span>
          </button>
        ))}
        {shownFlags.map((flag) => (
          <span
            key={flag}
            title={FLAG_LABELS[flag].title}
            className="inline-flex items-center gap-1 rounded-md bg-warning/10 px-1.5 py-0.5 text-[11px] font-medium text-foreground"
          >
            {flag === "due_date_ambiguous" ? <CalendarClock className="h-3 w-3" /> : <AlertTriangle className="h-3 w-3" />}
            {FLAG_LABELS[flag].label}
          </span>
        ))}
      </div>
      {first?.verified && (
        <p className="line-clamp-2 border-l-2 border-primary/25 pl-2 text-xs italic text-muted-foreground">“{first.excerpt}”</p>
      )}
    </div>
  );
}
