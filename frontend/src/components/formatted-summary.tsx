import { Fragment, ReactNode } from "react";

const HEADINGS = new Set([
  "Executive overview",
  "Discussion details",
  "Decisions and rationale",
  "Commitments",
  "Risks and unresolved questions",
]);

function inlineMarkdown(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*")) {
      return <em key={index}>{part.slice(1, -1)}</em>;
    }
    return <Fragment key={index}>{part}</Fragment>;
  });
}

export function FormattedSummary({ summary }: { summary: string }) {
  const blocks: ReactNode[] = [];
  let bullets: ReactNode[] = [];
  const flushBullets = () => {
    if (!bullets.length) return;
    blocks.push(<ul key={`list-${blocks.length}`} className="ml-5 list-disc space-y-2">{bullets}</ul>);
    bullets = [];
  };

  summary.split(/\r?\n/).forEach((raw, index) => {
    const line = raw.trim().replace(/^#{1,6}\s*/, "");
    const heading = line.match(/^\*\*(.+)\*\*$/)?.[1] ?? line;
    if (!line) {
      flushBullets();
      return;
    }
    if (HEADINGS.has(heading)) {
      flushBullets();
      blocks.push(<h3 key={`heading-${index}`} className="pt-3 text-sm font-semibold text-foreground first:pt-0">{heading}</h3>);
      return;
    }
    const bullet = line.match(/^[-*]\s+(.*)$/);
    if (bullet) {
      bullets.push(<li key={`bullet-${index}`}>{inlineMarkdown(bullet[1])}</li>);
      return;
    }
    flushBullets();
    blocks.push(<p key={`paragraph-${index}`}>{inlineMarkdown(line)}</p>);
  });
  flushBullets();

  return <div className="space-y-3 text-sm leading-6">{blocks}</div>;
}
