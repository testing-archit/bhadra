"use client";

import { useEffect, useRef, useState } from "react";
import { Download, Languages, Loader2, MessageCircle, Square, Volume2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

// Languages Gnani Timbre speaks; labels in their own script so a reader finds theirs.
const LANGUAGES: Array<{ code: string; label: string }> = [
  { code: "en-IN", label: "English" },
  { code: "hi-en", label: "Hinglish" },
  { code: "hi-IN", label: "हिन्दी" },
  { code: "mr-IN", label: "मराठी" },
  { code: "bn-IN", label: "বাংলা" },
  { code: "gu-IN", label: "ગુજરાતી" },
  { code: "pa-IN", label: "ਪੰਜਾਬੀ" },
  { code: "ta-IN", label: "தமிழ்" },
  { code: "te-IN", label: "తెలుగు" },
  { code: "kn-IN", label: "ಕನ್ನಡ" },
  { code: "ml-IN", label: "മലയാളം" },
];
const STORAGE_KEY = "wilco.listen-language";

type State = "idle" | "loading" | "playing" | "error";

/** Hear meeting notes in your own language: Gemini translates, Gnani Timbre
 * speaks, and the translated text is shown so you can read along. */
export function ListenInLanguage({ text, title, listenLabel = "Listen", share = true, compact = false, onListen }: { text: string; title?: string; listenLabel?: string; share?: boolean; compact?: boolean; onListen?: () => void }) {
  const [language, setLanguage] = useState("en-IN");
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState<string | null>(null);
  const [heard, setHeard] = useState<{ language: string; text: string; credit: string } | null>(null);
  const [sharing, setSharing] = useState(false);
  const [voiceNote, setVoiceNote] = useState<{ language: string; audio: string } | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const generation = useRef(0);
  const cache = useRef(new Map<string, Awaited<ReturnType<typeof api.speakTranslated>>>());

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved && LANGUAGES.some((item) => item.code === saved)) setLanguage(saved);
    } catch {}
    return () => { generation.current++; audioRef.current?.pause(); };
  }, []);

  // New notes need new audio and a new translation.
  useEffect(() => {
    generation.current++;
    audioRef.current?.pause();
    setState("idle");
    cache.current.clear();
    setHeard(null);
    setVoiceNote(null);
  }, [text]);

  async function resultFor(code: string) {
    const token = generation.current;
    let result = cache.current.get(code);
    if (!result) {
      result = await api.speakTranslated(text, code);
      if (token === generation.current) cache.current.set(code, result);
    }
    if (result.audio && token === generation.current) setVoiceNote({ language: code, audio: result.audio });
    return result;
  }

  /** WhatsApp text in the chosen language (opened in WhatsApp or WhatsApp Web). */
  async function shareOnWhatsApp() {
    setSharing(true);
    setError(null);
    // Open the window inside the tap, so pop-up blockers allow it.
    const target = window.open("about:blank", "_blank");
    try {
      const body = language === "en-IN" ? text : (await resultFor(language)).text;
      const message = `${title ? `*${title}*\n` : ""}${body}\n\n_Notes by Wilco_`;
      const url = `https://wa.me/?text=${encodeURIComponent(message)}`;
      if (target) target.location.href = url;
      else window.location.href = url;
    } catch (cause) {
      target?.close();
      setError(cause instanceof Error ? cause.message : "Couldn't prepare the message.");
    } finally {
      setSharing(false);
    }
  }

  function stop() {
    generation.current++;
    audioRef.current?.pause();
    setState("idle");
  }

  async function play() {
    if (state === "playing" || state === "loading") return stop();
    onListen?.();
    const token = ++generation.current;
    setState("loading");
    setError(null);
    try {
      const result = await resultFor(language);
      if (token !== generation.current) return;
      const voice = `Gnani ${result.model.replace("timbre-", "Timbre ")} (${result.voice})`;
      setHeard(language === "en-IN" && result.audio ? null : {
        language, text: result.text,
        credit: result.translated ? `Translated by Wilco · spoken by ${voice}` : `Spoken by ${voice}`,
      });
      if (!result.audio) {
        cache.current.delete(language); // try the speech again next time
        setState("idle");
        setError(result.speech_error ?? "Couldn't play the audio right now.");
        return;
      }
      const audio = audioRef.current ?? new Audio();
      audioRef.current = audio;
      audio.src = `data:audio/mpeg;base64,${result.audio}`;
      audio.onended = () => setState("idle");
      await audio.play();
      if (token !== generation.current) { audio.pause(); return; }
      setState("playing");
    } catch (cause) {
      if (token !== generation.current) return;
      setState("error");
      setError(cause instanceof Error ? cause.message : "Wilco couldn't read this aloud. Try again.");
    }
  }

  const label = LANGUAGES.find((item) => item.code === language)?.label ?? "English";
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {!compact && <Select
          value={language}
          onValueChange={(next) => {
            if (!next) return;
            stop();
            setLanguage(next);
            try { window.localStorage.setItem(STORAGE_KEY, next); } catch {}
          }}
        >
          <SelectTrigger size="sm" aria-label="Language to listen in" className="min-w-28">
            <Languages aria-hidden="true" />
            <SelectValue>{() => label}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {LANGUAGES.map((item) => <SelectItem key={item.code} value={item.code}>{item.label}</SelectItem>)}
            </SelectGroup>
          </SelectContent>
        </Select>}
        <Button size="sm" variant="outline" onClick={() => void play()} aria-pressed={state === "playing"} title="Read aloud with Gnani Timbre">
          {state === "loading" ? <Loader2 className="animate-spin" aria-hidden="true" /> : state === "playing" ? <Square aria-hidden="true" /> : <Volume2 aria-hidden="true" />}
          {state === "loading" ? (language === "en-IN" ? "Loading" : "Translating") : state === "playing" ? "Stop" : listenLabel}
        </Button>
        {share && !compact && <Button size="sm" variant="outline" onClick={() => void shareOnWhatsApp()} disabled={sharing} title="Send these notes on WhatsApp in the chosen language">
          {sharing ? <Loader2 className="animate-spin" aria-hidden="true" /> : <MessageCircle aria-hidden="true" />}
          WhatsApp
        </Button>}
        {!compact && voiceNote?.language === language && (
          <Button size="sm" variant="ghost" nativeButton={false} render={<a href={`data:audio/mpeg;base64,${voiceNote.audio}`} download={`wilco-notes-${language}.mp3`} />} title="Download the spoken notes to forward as a voice note">
            <Download aria-hidden="true" />
            Voice note
          </Button>
        )}
      </div>
      {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
      {heard && (
        <p lang={heard.language.slice(0, 2)} className="rounded-lg bg-muted px-3 py-2 text-sm leading-relaxed text-foreground">
          {heard.text}
          <span className="mt-1.5 block text-xs text-muted-foreground">{heard.credit}</span>
        </p>
      )}
    </div>
  );
}
