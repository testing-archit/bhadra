"use client";
import { useState } from "react";
import Link from "next/link";
import { ArrowUp, Loader2 } from "lucide-react";
import { api, type ChatResponse } from "@/lib/api";
import { VoiceAskButton } from "@/components/voice-ask-button";

export const HOME_QUESTIONS = [
  "What's blocking the release?",
  "Why PostgreSQL?",
  "What changed on search?",
];
export function HomeAsk() {
  const [question, setQuestion] = useState("");
  const [reply, setReply] = useState<ChatResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function ask(value: string) {
    if (!value.trim() || busy) return;
    setQuestion(value);
    setBusy(true);
    setError(null);
    try {
      setReply(await api.chat(value));
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not answer. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      className="ink-panel home-ask"
      aria-labelledby="home-ask-heading"
      aria-busy={busy}
    >
      <h2 id="home-ask-heading">Ask your meetings.</h2>
      <div className="home-question-chips">
        {HOME_QUESTIONS.map((value) => (
          <button key={value} disabled={busy} onClick={() => void ask(value)}>
            {value}
          </button>
        ))}
      </div>
      {reply && (
        <div className="home-ask-answer" role="status">
          <p title={reply.answer}>{reply.answer.split(/(?<=[.!?])\s/)[0]}</p>
          {reply.sources[0]?.meeting_id && (
            <Link href={`/meetings/${reply.sources[0].meeting_id}`}>
              [1] {reply.sources[0].meeting_title}
            </Link>
          )}
        </div>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void ask(question);
        }}
      >
        <label className="sr-only" htmlFor="home-question">
          Ask your meetings
        </label>
        <input
          id="home-question"
          placeholder="Ask Wilco…"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          disabled={busy}
        />
        <VoiceAskButton
          onQuestion={(value) => void ask(value)}
          onError={setError}
          disabled={busy}
        />
        <button
          className="home-ask-send"
          type="submit"
          aria-label="Ask"
          disabled={busy || !question.trim()}
        >
          {busy ? (
            <Loader2 className="animate-spin motion-reduce:animate-none" />
          ) : (
            <ArrowUp />
          )}
        </button>
      </form>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
