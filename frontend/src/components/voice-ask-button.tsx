"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Mic, Square } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const MAX_SECONDS = 30;

type State = "idle" | "recording" | "transcribing";

/** Tap to speak a question, tap again to send. The clip is transcribed by
 * Gnani Prisma (Hindi, English or both) and handed to `onQuestion`. */
export function VoiceAskButton({
  onQuestion,
  onError,
  disabled = false,
}: {
  onQuestion: (text: string) => void;
  onError: (message: string) => void;
  disabled?: boolean;
}) {
  const [state, setState] = useState<State>("idle");
  const [seconds, setSeconds] = useState(0);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const timer = useRef<number | null>(null);

  useEffect(() => () => {
    if (timer.current) window.clearInterval(timer.current);
    recorder.current?.stream.getTracks().forEach((track) => track.stop());
  }, []);

  async function start() {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      onError("This browser can't record audio. Type your question instead.");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      onError("Allow microphone access to ask by voice.");
      return;
    }
    const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
    const next = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    chunks.current = [];
    next.ondataavailable = (event) => event.data.size && chunks.current.push(event.data);
    next.onstop = () => void finish(next.mimeType || mimeType || "audio/webm");
    recorder.current = next;
    next.start();
    setSeconds(0);
    setState("recording");
    timer.current = window.setInterval(() => {
      setSeconds((value) => {
        if (value + 1 >= MAX_SECONDS) stop();
        return value + 1;
      });
    }, 1000);
  }

  function stop() {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = null;
    const active = recorder.current;
    if (active && active.state !== "inactive") {
      active.stop();
      active.stream.getTracks().forEach((track) => track.stop());
    }
  }

  async function finish(mimeType: string) {
    setState("transcribing");
    try {
      const clip = new Blob(chunks.current, { type: mimeType });
      if (clip.size < 2000) throw new Error("short");
      const { text } = await api.transcribeClip(clip);
      const question = text.replace(/^Speaker \d+:\s*/gm, "").trim();
      if (!question) throw new Error("empty");
      onQuestion(question);
    } catch {
      onError("Wilco didn't catch that. Hold the mic a little closer and try again.");
    } finally {
      setState("idle");
    }
  }

  const recording = state === "recording";
  return (
    <button
      type="button"
      onClick={() => (recording ? stop() : void start())}
      disabled={disabled || state === "transcribing"}
      aria-label={recording ? "Stop and ask" : "Ask by voice"}
      aria-pressed={recording}
      title={recording ? "Tap to send your question" : "Ask by voice (Hindi, English or both)"}
      className={cn(
        "relative flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-xl px-3 text-sm font-semibold outline-none transition-colors focus-visible:ring-3 focus-visible:ring-marigold/50 disabled:opacity-60",
        recording ? "bg-destructive text-white" : "bg-marigold text-marigold-foreground hover:bg-marigold/90",
      )}
    >
      {recording && <span className="absolute inset-0 animate-pulse rounded-xl bg-destructive/40" aria-hidden="true" />}
      <span className="relative flex items-center gap-1.5">
        {state === "transcribing" ? <Loader2 className="h-4 w-4 animate-spin" /> : recording ? <Square className="h-3.5 w-3.5" /> : <Mic className="h-4 w-4" />}
        {recording ? `0:${String(seconds).padStart(2, "0")}` : state === "transcribing" ? "Listening" : null}
      </span>
    </button>
  );
}
