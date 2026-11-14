"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Mic, MicOff, PhoneOff, Sparkles } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

type Phase = "idle" | "listening" | "hearing" | "thinking" | "speaking";
interface Turn {
  role: "user" | "assistant";
  content: string;
  language?: string | null;
}

const LANGUAGE_LABELS: Record<string, string> = {
  "hi-IN": "Hindi / Hinglish", "en-IN": "English", "ta-IN": "தமிழ்", "te-IN": "తెలుగు", "kn-IN": "ಕನ್ನಡ",
  "ml-IN": "മലയാളം", "mr-IN": "मराठी", "bn-IN": "বাংলা", "gu-IN": "ગુજરાતી", "pa-IN": "ਪੰਜਾਬੀ",
};

const PHASE_LABEL: Record<Phase, string> = {
  idle: "Tap to start talking",
  listening: "Sun raha hoon… bolo",
  hearing: "Sun raha hoon…",
  thinking: "Soch raha hoon…",
  speaking: "Bol raha hoon… (interrupt anytime)",
};

// Voice activity: speech starts after this many loud frames (50 ms each) and
// ends after this much quiet. Short blips are dropped.
const START_FRAMES = 3;
const END_SILENCE_MS = 900;
const MIN_UTTERANCE_MS = 450;
const MAX_UTTERANCE_MS = 30_000;

/** Wilco Live: a hands-free spoken conversation, like Gemini Live, built
 * on Gnani. Prisma hears each utterance, Gemini answers from your meetings,
 * Timbre says it; talking over Wilco stops it and it listens. */
export function LiveSession() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [level, setLevel] = useState(0);
  const [muted, setMuted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const phaseRef = useRef<Phase>("idle");
  const mutedRef = useRef(false);
  const turnsRef = useRef<Turn[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const timerRef = useRef<number | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const startedAtRef = useRef(0);

  const go = useCallback((next: Phase) => {
    phaseRef.current = next;
    setPhase(next);
  }, []);

  const stopSpeaking = useCallback(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.src = "";
    }
  }, []);

  const sendTurn = useCallback(async (clip: Blob) => {
    go("thinking");
    try {
      const history = turnsRef.current.slice(-8).map(({ role, content }) => ({ role, content }));
      const result = await api.liveTurn(clip, history);
      if (!result.transcript || !result.reply) {
        go("listening");
        return;
      }
      const next: Turn[] = [
        ...turnsRef.current,
        { role: "user", content: result.transcript, language: result.language },
        { role: "assistant", content: result.reply, language: result.language },
      ];
      turnsRef.current = next;
      setTurns(next);
      if (!result.audio || phaseRef.current !== "thinking") {
        go("listening");
        return;
      }
      const audio = audioRef.current ?? new Audio();
      audioRef.current = audio;
      audio.src = `data:audio/mpeg;base64,${result.audio}`;
      audio.onended = () => phaseRef.current === "speaking" && go("listening");
      go("speaking");
      await audio.play().catch(() => go("listening"));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Wilco couldn't answer that. Say it again?");
      go("listening");
    }
  }, [go]);

  const beginUtterance = useCallback(() => {
    const stream = streamRef.current;
    if (!stream) return;
    const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    chunksRef.current = [];
    recorder.ondataavailable = (event) => event.data.size && chunksRef.current.push(event.data);
    recorder.onstop = () => {
      const duration = performance.now() - startedAtRef.current;
      const clip = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
      if (duration < MIN_UTTERANCE_MS || clip.size < 1500) {
        go("listening");
        return;
      }
      void sendTurn(clip);
    };
    recorderRef.current = recorder;
    startedAtRef.current = performance.now();
    recorder.start();
    go("hearing");
  }, [go, sendTurn]);

  const endUtterance = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }, []);

  const stop = useCallback(() => {
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = null;
    stopSpeaking();
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.onstop = null;
      recorderRef.current.stop();
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    void contextRef.current?.close();
    contextRef.current = null;
    setLevel(0);
    go("idle");
  }, [go, stopSpeaking]);

  const start = useCallback(async () => {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("This browser can't record audio.");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch {
      setError("Allow microphone access to talk with Wilco.");
      return;
    }
    streamRef.current = stream;
    const context = new AudioContext();
    contextRef.current = context;
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    context.createMediaStreamSource(stream).connect(analyser);
    const samples = new Float32Array(analyser.fftSize);
    let noise = 0.01;
    let loudFrames = 0;
    let quietSince = 0;
    // Unlock audio playback inside the user's tap.
    audioRef.current = audioRef.current ?? new Audio();
    go("listening");

    timerRef.current = window.setInterval(() => {
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (const value of samples) sum += value * value;
      const rms = Math.sqrt(sum / samples.length);
      setLevel(Math.min(1, rms * 12));
      const current = phaseRef.current;
      if (mutedRef.current) return;
      // Wilco's own voice leaks into the mic despite echo cancellation, so
      // interrupting while it speaks needs to be clearly louder.
      const threshold = Math.max(0.012, noise * 3) * (current === "speaking" ? 2.6 : 1);
      if (current === "listening" || current === "speaking") {
        if (rms > threshold) {
          loudFrames += 1;
          if (loudFrames >= START_FRAMES) {
            loudFrames = 0;
            quietSince = 0;
            if (current === "speaking") stopSpeaking();
            beginUtterance();
          }
        } else {
          loudFrames = 0;
          noise = noise * 0.97 + rms * 0.03;
        }
      } else if (current === "hearing") {
        const elapsed = performance.now() - startedAtRef.current;
        if (rms < threshold) {
          quietSince = quietSince || performance.now();
          if (performance.now() - quietSince > END_SILENCE_MS) {
            quietSince = 0;
            endUtterance();
          }
        } else {
          quietSince = 0;
        }
        if (elapsed > MAX_UTTERANCE_MS) endUtterance();
      }
    }, 50);
  }, [beginUtterance, endUtterance, go, stopSpeaking]);

  useEffect(() => () => stop(), [stop]);

  const last = turns.slice(-2);
  const active = phase !== "idle";
  const scale = 1 + (phase === "hearing" || phase === "listening" ? level * 0.35 : phase === "speaking" ? 0.08 : 0);

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col items-center justify-between gap-6 px-4 py-8 sm:py-12">
      <div className="text-center">
        <h1 className="text-3xl font-bold sm:text-4xl">
          <span className="text-glow bg-clip-text text-transparent">Wilco Live</span>
        </h1>
        <p className="mt-2 max-w-md text-sm text-muted-foreground">
          Just talk, in Hindi, English, Hinglish, Tamil, Marathi or any Indian language. Wilco answers from your meetings, out loud. Interrupt anytime.
        </p>
      </div>

      <button
        type="button"
        onClick={() => (active ? undefined : void start())}
        aria-label={active ? PHASE_LABEL[phase] : "Start Wilco Live"}
        className={cn("relative grid size-56 place-items-center rounded-full outline-none sm:size-64", !active && "cursor-pointer")}
      >
        <span
          aria-hidden="true"
          className={cn(
            "absolute inset-0 rounded-full bg-[radial-gradient(circle,oklch(0.74_0.15_285/0.55),oklch(0.74_0.16_350/0.25)_55%,transparent_72%)] blur-2xl transition-transform duration-150",
            phase === "thinking" && "animate-pulse",
          )}
          style={{ transform: `scale(${scale * 1.15})` }}
        />
        <span
          aria-hidden="true"
          className="absolute inset-8 rounded-full bg-[radial-gradient(circle_at_35%_30%,oklch(0.86_0.13_75),oklch(0.78_0.16_72)_45%,oklch(0.6_0.18_40)_100%)] shadow-[0_20px_60px_-10px_oklch(0.78_0.16_72/0.6)] transition-transform duration-100"
          style={{ transform: `scale(${scale})` }}
        />
        <span className="relative text-marigold-foreground">
          {active ? (muted ? <MicOff className="size-10" /> : phase === "thinking" ? <Sparkles className="size-10 animate-pulse" /> : <Mic className="size-10" />) : <Mic className="size-12" />}
        </span>
      </button>

      <div className="flex min-h-28 w-full max-w-2xl flex-col items-center gap-3 text-center" aria-live="polite">
        <p className="text-sm font-medium text-muted-foreground">{PHASE_LABEL[phase]}</p>
        {last.map((turn, index) => (
          <p
            key={`${turns.length}-${index}`}
            className={cn(turn.role === "user" ? "text-sm text-muted-foreground" : "text-lg leading-snug font-medium text-balance")}
          >
            {turn.role === "user" ? `“${turn.content}”` : turn.content}
          </p>
        ))}
        {last[0]?.language && LANGUAGE_LABELS[last[0].language] && (
          <span className="glass rounded-full border px-3 py-1 text-xs text-muted-foreground">Heard in {LANGUAGE_LABELS[last[0].language]}</span>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>

      <div className="flex items-center gap-3">
        {active ? (
          <>
            <button
              type="button"
              onClick={() => {
                mutedRef.current = !mutedRef.current;
                setMuted(mutedRef.current);
              }}
              aria-pressed={muted}
              className="glass inline-flex h-12 items-center gap-2 rounded-full border px-5 text-sm font-medium"
            >
              {muted ? <MicOff className="size-4" /> : <Mic className="size-4" />} {muted ? "Unmute" : "Mute"}
            </button>
            <button
              type="button"
              onClick={stop}
              className="inline-flex h-12 items-center gap-2 rounded-full bg-destructive px-5 text-sm font-semibold text-white"
            >
              <PhoneOff className="size-4" /> End
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => void start()}
            className="inline-flex h-12 items-center gap-2 rounded-full bg-marigold px-6 text-sm font-semibold text-marigold-foreground"
          >
            <Mic className="size-4" /> Start talking
          </button>
        )}
      </div>
      <p className="text-[11px] text-muted-foreground">Hears with Gnani Prisma · speaks with Gnani Timbre</p>
    </div>
  );
}
