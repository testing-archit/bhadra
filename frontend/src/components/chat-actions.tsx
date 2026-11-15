"use client";

import { useEffect, useState } from "react";
import { Check, Copy, RotateCcw } from "lucide-react";
import { SpeakButton } from "@/components/speak-button";

export function ChatActions({ content, onRetry, speak = false }: { content: string; onRetry: () => void; speak?: boolean }) {
  const [copied, setCopied] = useState(false);
  const [copyError,setCopyError]=useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(timer);
  }, [copied]);

  async function copyAnswer() {
    try { await navigator.clipboard.writeText(content);setCopied(true);setCopyError(false); }
    catch {setCopyError(true);}
  }

  return (
    <div className="mt-2 flex items-center gap-1 text-muted-foreground">
      {copyError&&<span role="alert" className="text-xs text-destructive">Could not copy. Try again.</span>}
      <SpeakButton text={content} compact autoPlay={speak} />
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
