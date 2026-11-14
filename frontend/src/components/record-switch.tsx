"use client";

import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

/** The per-meeting "send the notetaker" switch used wherever calendar
 * meetings are listed. */
export function RecordSwitch({ on, busy, title, onToggle }: { on: boolean; busy: boolean; title: string; onToggle: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={`${on ? "Don't record" : "Record"} ${title}`}
      disabled={busy}
      onClick={onToggle}
      className={cn(
        "relative h-5 w-9 shrink-0 rounded-full transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        on ? "bg-primary" : "bg-input",
      )}
    >
      {busy ? (
        <Loader2 className="absolute inset-0 m-auto size-3 animate-spin text-primary-foreground" />
      ) : (
        <span className={cn("absolute top-0.5 left-0.5 size-4 rounded-full bg-background shadow-sm transition-transform", on && "translate-x-4")} />
      )}
    </button>
  );
}
