import { cn } from "@/lib/utils";

/** Charcha's mark: a speech bubble with a marigold bindi on neel. Drawn
 * inline so it stays crisp at every size and follows the theme tokens. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 56 56" className={cn("size-8 shrink-0", className)} aria-hidden="true">
      <rect width="56" height="56" rx="13" className="fill-primary dark:fill-[oklch(0.36_0.15_279)]" />
      <rect x="11" y="13.7" width="34" height="24.6" rx="10.4" className="fill-[oklch(0.978_0.008_85)]" />
      <path d="M16.4 35 L25.7 37.2 L13.7 46.5 Z" className="fill-[oklch(0.978_0.008_85)]" />
      <circle cx="28" cy="26" r="5.3" className="fill-marigold" />
    </svg>
  );
}

export function Wordmark({ className, markClassName }: { className?: string; markClassName?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <BrandMark className={markClassName} />
      <span className="font-heading text-xl leading-none font-bold tracking-tight">Charcha</span>
    </span>
  );
}

/** The record disc: marigold centre with rangoli-style dotted rings. Used as
 * the hero on sign-in; pass `live` to pulse the outer ring while recording. */
export function VoiceDisc({ className, live = false }: { className?: string; live?: boolean }) {
  const dots = (count: number, radius: number, size: number) =>
    Array.from({ length: count }, (_, i) => {
      const angle = (i / count) * Math.PI * 2;
      // Rounded so server and client render identical attribute strings.
      const cx = Math.round((100 + Math.cos(angle) * radius) * 100) / 100;
      const cy = Math.round((100 + Math.sin(angle) * radius) * 100) / 100;
      return <circle key={`${radius}-${i}`} cx={cx} cy={cy} r={size} />;
    });
  return (
    <svg viewBox="0 0 200 200" className={cn("size-48", className)} aria-hidden="true">
      <g className="fill-marigold/35">{dots(36, 92, 2.2)}</g>
      <g className="fill-marigold/55">{dots(24, 74, 2.6)}</g>
      <circle cx="100" cy="100" r="56" className={cn("fill-marigold/20", live && "animate-pulse")} />
      <circle cx="100" cy="100" r="42" className="fill-marigold" />
      <g className="fill-marigold-foreground">
        <rect x="91" y="76" width="18" height="30" rx="9" />
        <path d="M82 100a18 18 0 0 0 36 0" fill="none" strokeWidth="5" strokeLinecap="round" className="stroke-marigold-foreground" />
        <rect x="97.5" y="117" width="5" height="10" rx="2.5" />
      </g>
    </svg>
  );
}
