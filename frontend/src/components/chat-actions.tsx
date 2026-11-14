"use client";

import { useEffect, useState } from "react";
import { Check, Copy, RotateCcw } from "lucide-react";
import { SpeakButton } from "@/components/speak-button";

export function ChatActions({ content, onRetry }: { content: string; onRetry: () => void }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(timer);
  }, [copied]);

  async function copyAnswer() {
    await navigator.clipboard.writeText(content);
    setCopied(true);
  }

  return (
    <div className="mt-2 flex items-center gap-1 text-muted-foreground">
      <SpeakButton text={content} compact />
      <button
        type="button"
        onClick={copyAnswer}
        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
        aria-label="Copy answer"
      >
        {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
        {copied ? "Copied" : "Copy"}
      </button>
      <button
        type="button"
        onClick={onRetry}
        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
        aria-label="Retry answer"
      >
        <RotateCcw className="h-3 w-3" /> Retry
      </button>
    </div>
  );
}
