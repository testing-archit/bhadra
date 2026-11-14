"use client";

import ReactMarkdown from "react-markdown";
import { ChatSegmentRef, ChatSource } from "@/lib/api";
import { formatClock } from "@/lib/media-time";

const CITATION = /\[M(\d+)(?::S(\d+))?\]/g;

export interface ResolvedCitation {
  source: ChatSource;
  segment: ChatSegmentRef | null;
}

/** Meeting-grounded answers cite [M1:S12] (a transcript line) or [M1] (the
 * meeting's notes). Each one becomes a chip that opens that exact evidence;
 * anything that doesn't resolve to a returned source is dropped, so a
 * rendered citation always leads somewhere the reader can access. */
export function CitedMarkdown({
  content,
  sources,
  onCite,
}: {
  content: string;
  sources: ChatSource[];
  onCite: (citation: ResolvedCitation) => void;
}) {
  const byTag = new Map(sources.filter((s) => s.tag).map((s) => [s.tag as string, s]));
  const multiMeeting = byTag.size > 1;
  const resolved = new Map<string, ResolvedCitation>();

  const linked = content.replace(CITATION, (_match, meeting: string, seq?: string) => {
    const source = byTag.get(`M${meeting}`);
    if (!source) return "";
    const segment = seq !== undefined ? source.segments?.find((ref) => ref.seq === Number(seq)) ?? null : null;
    if (seq !== undefined && !segment) return "";
    const key = `M${meeting}${seq !== undefined ? `-S${seq}` : ""}`;
    resolved.set(key, { source, segment });
    const time = segment ? (segment.start_ms !== null ? formatClock(segment.start_ms) : `line ${segment.seq + 1}`) : "notes";
    const label = multiMeeting ? `M${meeting} · ${time}` : time;
    return ` [${label}](#cite-${key})`;
  });

  return (
    <div className="flex flex-col gap-2 text-sm [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
      <ReactMarkdown
        components={{
          p: ({ children }) => <p className="whitespace-pre-wrap">{children}</p>,
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
          ul: ({ children }) => <ul className="list-disc space-y-1 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal space-y-1 pl-5">{children}</ol>,
          li: ({ children }) => <li>{children}</li>,
          h1: ({ children }) => <p className="font-semibold">{children}</p>,
          h2: ({ children }) => <p className="font-semibold">{children}</p>,
          h3: ({ children }) => <p className="font-semibold">{children}</p>,
          a: ({ children, href }) => {
            const citation = href?.startsWith("#cite-") ? resolved.get(href.slice(6)) : undefined;
            if (citation) {
              return (
                <button
                  type="button"
                  onClick={() => onCite(citation)}
                  title={citation.segment ? `${citation.segment.speaker}: “${citation.segment.excerpt}”` : citation.source.meeting_title}
                  className="mx-0.5 inline-flex items-center rounded border bg-muted/60 px-1 py-px align-baseline text-[11px] font-medium text-foreground/80 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {children}
                </button>
              );
            }
            return (
              <a href={href} target="_blank" rel="noopener noreferrer" className="underline">
                {children}
              </a>
            );
          },
        }}
      >
        {linked}
      </ReactMarkdown>
    </div>
  );
}
