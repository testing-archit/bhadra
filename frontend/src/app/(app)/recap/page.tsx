"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, FileAudio, Loader2, Pause, Phone, Play, Share2, Upload } from "lucide-react";
import { api, ApiError, type RecapResult } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const LANGUAGE_LABELS: Record<string, string> = {
  "hi-IN": "Hindi / Hinglish", "en-IN": "English", "ta-IN": "Tamil", "te-IN": "Telugu", "kn-IN": "Kannada",
  "ml-IN": "Malayalam", "mr-IN": "Marathi", "bn-IN": "Bengali", "gu-IN": "Gujarati", "pa-IN": "Punjabi",
};

function whatsappText(result: RecapResult): string {
  const items = result.action_items.map((i) => `• ${i.owner ? `${i.owner}: ` : ""}${i.task}${i.due ? ` (${i.due})` : ""}`);
  const amounts = result.amounts.map((a) => `• ${a}`);
  return [
    `*${result.title}*`,
    result.summary,
    items.length ? `\nKarna hai:\n${items.join("\n")}` : "",
    amounts.length ? `\nAmounts:\n${amounts.join("\n")}` : "",
    "\n— Wilco",
  ].filter(Boolean).join("\n");
}

export default function RecapPage() {
  const [kind, setKind] = useState<"voice_note" | "call">("voice_note");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RecapResult | null>(null);
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  async function run(selected: File) {
    setFile(selected);
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.recapAudio(selected, kind));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Couldn't recap that file. Try again.");
    } finally {
      setBusy(false);
    }
  }

  function togglePlay() {
    if (!result?.audio) return;
    const audio = audioRef.current ?? new Audio();
    audioRef.current = audio;
    if (playing) {
      audio.pause();
      setPlaying(false);
      return;
    }
    if (!audio.src) audio.src = `data:audio/mpeg;base64,${result.audio}`;
    audio.onended = () => setPlaying(false);
    void audio.play().then(() => setPlaying(true));
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Call & voice note recap"
        description="Drop in a phone call recording or a WhatsApp voice note. Wilco recaps it in the language it was spoken in, reads the recap aloud, and saves the action items."
      />

      <div className="flex gap-2" role="radiogroup" aria-label="What is it?">
        {([["voice_note", "WhatsApp voice note", FileAudio], ["call", "Phone call", Phone]] as const).map(([value, label, Icon]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={kind === value}
            onClick={() => setKind(value)}
            className={cn(
              "inline-flex h-9 items-center gap-1.5 rounded-full border px-4 text-sm font-medium transition-colors",
              kind === value ? "border-primary bg-primary text-primary-foreground" : "glass text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-4" /> {label}
          </button>
        ))}
      </div>

      <label
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          const dropped = event.dataTransfer.files?.[0];
          if (dropped && !busy) void run(dropped);
        }}
        className="glass flex cursor-pointer flex-col items-center gap-3 rounded-3xl border border-dashed px-6 py-12 text-center transition-colors hover:border-primary/50"
      >
        <input
          ref={inputRef}
          type="file"
          accept="audio/*,.opus,.ogg,.m4a,.mp3,.wav,.aac,.amr,.webm"
          className="sr-only"
          disabled={busy}
          onChange={(event) => {
            const selected = event.target.files?.[0];
            if (selected) void run(selected);
            event.target.value = "";
          }}
        />
        <span className="grid size-14 place-items-center rounded-2xl bg-marigold text-marigold-foreground">
          {busy ? <Loader2 className="size-6 animate-spin" /> : <Upload className="size-6" />}
        </span>
        <span className="text-base font-semibold">
          {busy ? `Gnani is listening to ${file?.name ?? "the audio"}…` : "Choose or drop an audio file"}
        </span>
        <span className="max-w-md text-sm text-muted-foreground">
          .opus and .ogg from WhatsApp, .m4a, .mp3, .wav or .amr from a call recorder, up to 25 MB. Hindi, English, Hinglish, Tamil, Marathi and more.
        </span>
      </label>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {result && (
        <Card>
          <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="text-xl font-bold">{result.title}</CardTitle>
              {result.language && LANGUAGE_LABELS[result.language] && (
                <p className="mt-1 text-xs text-muted-foreground">Heard in {LANGUAGE_LABELS[result.language]} · recap in the same language</p>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              {result.audio && (
                <Button onClick={togglePlay} className="bg-marigold text-marigold-foreground hover:bg-marigold/90">
                  {playing ? <Pause /> : <Play />} {playing ? "Pause" : "Play voice recap"}
                </Button>
              )}
              <a
                href={`https://wa.me/?text=${encodeURIComponent(whatsappText(result))}`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-sm font-medium transition-colors hover:bg-muted"
              >
                <Share2 className="size-4" /> Share on WhatsApp
              </a>
              {result.meeting_id && (
                <Link href={`/meetings/${result.meeting_id}`} className="inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-sm font-medium transition-colors hover:bg-muted">
                  Open in Wilco <ArrowUpRight className="size-4" />
                </Link>
              )}
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            <p className="max-w-3xl text-base leading-relaxed">{result.summary}</p>
            {result.action_items.length > 0 && (
              <section>
                <h2 className="mb-2 text-sm font-semibold">Action items</h2>
                <ul className="flex flex-col gap-1.5">
                  {result.action_items.map((item, index) => (
                    <li key={index} className="text-sm">
                      {item.owner && <span className="font-semibold">{item.owner}: </span>}
                      {item.task}
                      {item.due && <span className="text-muted-foreground"> · {item.due}</span>}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {result.amounts.length > 0 && (
              <section>
                <h2 className="mb-2 text-sm font-semibold">Amounts and numbers</h2>
                <ul className="flex flex-wrap gap-2">
                  {result.amounts.map((amount, index) => (
                    <li key={index} className="rounded-full border bg-muted px-3 py-1 text-xs">{amount}</li>
                  ))}
                </ul>
              </section>
            )}
            <details className="text-sm">
              <summary className="cursor-pointer text-muted-foreground">Transcript</summary>
              <p className="mt-2 whitespace-pre-wrap text-muted-foreground">{result.transcript}</p>
            </details>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
