import { cn } from "@/lib/utils";

/** Wilco's mark (placeholder until the final logo lands): a check — "will
 * comply" — sending out two radio waves, ink on signal yellow. Drawn inline so
 * it stays crisp at every size. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 56 56" className={cn("size-8 shrink-0", className)} aria-hidden="true">
      <rect width="56" height="56" rx="14" className="fill-marigold" />
      <g fill="none" strokeLinecap="round" strokeLinejoin="round" className="stroke-marigold-foreground">
        <path d="M13 30.5 L22 39.5 L37 23" strokeWidth="6.2" />
        <path d="M37.5 12.5 A11 11 0 0 1 45.5 20.5" strokeWidth="4.2" />
        <path d="M38 4.5 A19 19 0 0 1 53 19.5" strokeWidth="4.2" opacity="0.45" />
      </g>
    </svg>
  );
}

export function Wordmark({ className, markClassName }: { className?: string; markClassName?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <BrandMark className={markClassName} />
      <span className="font-heading text-xl leading-none font-semibold tracking-tight">Wilco</span>
    </span>
  );
}

// A fixed, speech-like envelope: quiet edges, a busy middle. Fixed values so
// the server and client render the same bars.
const WAVE = [
  0.18, 0.3, 0.22, 0.46, 0.34, 0.62, 0.4, 0.78, 0.52, 0.94, 0.6, 0.82, 1, 0.7, 0.88, 0.5, 0.74, 0.42, 0.66,
  0.36, 0.56, 0.28, 0.44, 0.24, 0.34, 0.16, 0.26, 0.12,
];

/** The signal-yellow waveform: Wilco listening. `live` keeps it moving (only
 * while something is actually recording); otherwise the bars rise once. */
export function Waveform({ className, bars = WAVE.length, live = false }: { className?: string; bars?: number; live?: boolean }) {
  const values = WAVE.slice(0, bars);
  return (
    <div className={cn("flex h-16 items-end gap-[3px]", className)} aria-hidden="true">
      {values.map((value, index) => (
        <span
          key={index}
          className={cn("w-[3px] shrink-0 rounded-full bg-marigold motion-reduce:animate-none", live ? "wave-live" : "wave-bar")}
          style={{
            height: `${Math.round(value * 100)}%`,
            animationDelay: `${live ? (index % 7) * 110 : index * 22}ms`,
            opacity: 0.55 + value * 0.45,
          }}
        />
      ))}
    </div>
  );
}

/** Two-tone heading text: the first part in ink, the rest in grey. */
export function TwoTone({ lead, rest, className }: { lead: React.ReactNode; rest?: React.ReactNode; className?: string }) {
  return (
    <span className={className}>
      {lead}
      {rest && <span className="text-muted-foreground"> {rest}</span>}
    </span>
  );
}

/** Kept for the record page: the waveform inside a round signal disc. */
export function VoiceDisc({ className, live = false }: { className?: string; live?: boolean }) {
  return (
    <div className={cn("grid size-48 place-items-center rounded-full bg-marigold/15", className)} aria-hidden="true">
      <div className="grid size-[64%] place-items-center rounded-full bg-marigold">
        <Waveform bars={9} live={live} className="h-[38%] [&>span]:bg-marigold-foreground" />
      </div>
    </div>
  );
}
