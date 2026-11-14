"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowUp, Bot, Mic, Sparkles } from "lucide-react";
import { VoiceAskButton } from "@/components/voice-ask-button";
import { cn } from "@/lib/utils";

const EXAMPLES = [
  "Sharma ji ka kitna udhaar baaki hai?",
  "Is hafte kya decide hua?",
  "Vedant ke paas kaunse tasks pending hain?",
];

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

/** Home's centrepiece: one glass prompt to ask company memory by typing or
 * speaking (Gnani Prisma). A spoken question's answer is read back aloud. */
export function PromptHero({ firstName, onCapture }: { firstName?: string; onCapture: () => void }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  function ask(question: string, spoken = false) {
    const text = question.trim();
    if (!text) return;
    router.push(`/memory?q=${encodeURIComponent(text)}${spoken ? "&voice=1" : ""}`);
  }

  return (
    <section className="flex flex-col items-center px-1 pt-4 pb-2 text-center sm:pt-10">
      <p className="text-sm text-muted-foreground">
        {greeting()}{firstName ? `, ${firstName}` : ""} ·{" "}
        {new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
      </p>
      <h1 className="mt-3 max-w-3xl text-4xl leading-[1.05] font-bold sm:text-6xl">
        <span className="text-glow bg-clip-text text-transparent">Bolo.</span> Charcha sun raha hai.
      </h1>
      <p className="mt-3 max-w-xl text-base text-muted-foreground">
        Ask anything your team said, in Hindi, English or both. Tap the mic and Charcha answers out loud.
      </p>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          ask(query);
        }}
        className="glass mt-8 w-full max-w-2xl rounded-3xl border p-3 text-left shadow-[0_30px_80px_-30px_oklch(0.5_0.2_285/0.55)] focus-within:border-primary/40"
      >
        <textarea
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              ask(query);
            }
          }}
          rows={2}
          placeholder="Kuch bhi poocho… “Is hafte kya decide hua?”"
          aria-label="Ask company memory"
          className="w-full resize-none bg-transparent px-3 pt-2 text-lg leading-7 outline-none placeholder:text-muted-foreground/70"
        />
        <div className="mt-2 flex items-center gap-2">
          <button
            type="button"
            onClick={onCapture}
            className="inline-flex h-9 items-center gap-1.5 rounded-full border px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <Bot className="size-3.5" /> Capture a meeting
          </button>
          <Link
            href="/record"
            className="inline-flex h-9 items-center gap-1.5 rounded-full border px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <Mic className="size-3.5" /> Record in person
          </Link>
          <div className="ml-auto flex items-center gap-2">
            <VoiceAskButton onQuestion={(text) => ask(text, true)} onError={setError} />
            <button
              type="submit"
              disabled={!query.trim()}
              aria-label="Ask"
              className={cn(
                "grid size-10 place-items-center rounded-full bg-foreground text-background transition-opacity",
                !query.trim() && "opacity-40",
              )}
            >
              <ArrowUp className="size-5" />
            </button>
          </div>
        </div>
      </form>
      {error && <p className="mt-3 text-sm text-destructive">{error}</p>}

      <div className="mt-4 flex max-w-2xl flex-wrap justify-center gap-2">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => ask(example)}
            className="glass inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            <Sparkles className="size-3 text-marigold" /> {example}
          </button>
        ))}
      </div>
    </section>
  );
}
