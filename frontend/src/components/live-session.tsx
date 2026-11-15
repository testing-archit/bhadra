"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { TalkingMascot } from "@/components/talking-mascot";
import { Button } from "@/components/ui/button";
import { Mic, MicOff, PhoneOff, VolumeX } from "lucide-react";
import { api, ApiError } from "@/lib/api";

type Phase = "idle" | "listening" | "hearing" | "thinking" | "speaking";
interface Turn {
  role: "user" | "assistant";
  content: string;
  language?: string | null;
}

const LANGUAGE_LABELS: Record<string, string> = {
  "hi-IN": "Hindi / Hinglish",
  "en-IN": "English",
  "ta-IN": "தமிழ்",
  "te-IN": "తెలుగు",
  "kn-IN": "ಕನ್ನಡ",
  "ml-IN": "മലയാളം",
  "mr-IN": "मराठी",
  "bn-IN": "বাংলা",
  "gu-IN": "ગુજરાતી",
  "pa-IN": "ਪੰਜਾਬੀ",
};

const PHASE_LABEL: Record<Phase, string> = {
  idle: "Ready when you are",
  listening: "I’m listening",
  hearing: "Go on, I’m listening",
  thinking: "Looking through your meetings",
  speaking: "Wilco is speaking",
};

// Voice activity: speech starts after this many loud frames (50 ms each) and
// ends after this much quiet. Short blips are dropped.
const START_FRAMES = 3;
const END_SILENCE_MS = 550;
const MIN_UTTERANCE_MS = 450;
const MAX_UTTERANCE_MS = 30_000;

/** Wilco Live: a hands-free spoken conversation, like Gemini Live, built
 * on Gnani. Prisma hears each utterance, Gemini answers from your meetings,
 * Timbre says it; talking over Wilco stops it and it listens. */
export function LiveSession() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [level, setLevel] = useState(0);
  const [starting, setStarting] = useState(false);
  const [speakerLevel, setSpeakerLevel] = useState(0);
  const sessionRef = useRef(0);
  const startingRef = useRef(false);
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
  const listenAfterRef = useRef(0);

  const go = useCallback((next: Phase) => {
    phaseRef.current = next;
    setPhase(next);
  }, []);

  const stopSpeaking = useCallback(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.onended = null;
      audio.onplaying = null;
      audio.pause();
      audio.src = "";
    }
    setSpeakerLevel(0);
    listenAfterRef.current = performance.now() + 350;
  }, []);

  const sendTurn = useCallback(
    async (clip: Blob) => {
      const session = sessionRef.current;
      go("thinking");
      try {
        const history = turnsRef.current
          .slice(-8)
          .map(({ role, content }) => ({ role, content }));
        const result = await api.liveTurn(clip, history);
        if (session !== sessionRef.current) return;
        if (!result.transcript || !result.reply) {
          go("listening");
          return;
        }
        const next: Turn[] = [
          ...turnsRef.current,
          {
            role: "user",
            content: result.transcript,
            language: result.language,
          },
          {
            role: "assistant",
            content: result.reply,
            language: result.language,
          },
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
        audio.onended = () => {
          listenAfterRef.current = performance.now() + 350;
          if (phaseRef.current === "speaking") go("listening");
        };
        audio.onplaying = () => {
          if (session === sessionRef.current) go("speaking");
        };
        await audio.play().catch(() => {
          if (session === sessionRef.current) {
            setError("Audio couldn’t play. You can read the answer below.");
            go("listening");
          }
        });
      } catch (cause) {
        if (session !== sessionRef.current) return;
        setError(
          cause instanceof ApiError
            ? cause.message
            : "Wilco couldn't answer that. Say it again?",
        );
        go("listening");
      }
    },
    [go],
  );

  const beginUtterance = useCallback(() => {
    const stream = streamRef.current;
    if (!stream) return;
    const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find(
      (type) => MediaRecorder.isTypeSupported(type),
    );
    const recorder = new MediaRecorder(
      stream,
      mimeType ? { mimeType } : undefined,
    );
    chunksRef.current = [];
    recorder.ondataavailable = (event) =>
      event.data.size && chunksRef.current.push(event.data);
    recorder.onstop = () => {
      const duration = performance.now() - startedAtRef.current;
      const clip = new Blob(chunksRef.current, {
        type: recorder.mimeType || "audio/webm",
      });
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
    sessionRef.current += 1;
    startingRef.current = false;
    setStarting(false);
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
    audioRef.current = null;
    mutedRef.current = false;
    setMuted(false);
    setLevel(0);
    go("idle");
  }, [go, stopSpeaking]);

  const start = useCallback(async () => {
    if (startingRef.current || phaseRef.current !== "idle") return;
    setError(null);
    if (
      !navigator.mediaDevices?.getUserMedia ||
      typeof MediaRecorder === "undefined"
    ) {
      setError("This browser can't record audio.");
      return;
    }
    startingRef.current = true;
    setStarting(true);
    const session = ++sessionRef.current;
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch {
      if (session !== sessionRef.current) return;
      startingRef.current = false;
      setStarting(false);
      setError("Allow microphone access to talk with Wilco.");
      return;
    }
    if (session !== sessionRef.current) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    startingRef.current = false;
    setStarting(false);
    streamRef.current = stream;
    try {
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
      audioRef.current = new Audio();
      const output = context.createAnalyser();
      output.fftSize = 256;
      context.createMediaElementSource(audioRef.current).connect(output);
      output.connect(context.destination);
      const outputSamples = new Float32Array(output.fftSize);
      await context.resume();
      if (session !== sessionRef.current) return;
      go("listening");

      timerRef.current = window.setInterval(() => {
        analyser.getFloatTimeDomainData(samples);
        let sum = 0;
        for (const value of samples) sum += value * value;
        const rms = Math.sqrt(sum / samples.length);
        setLevel(mutedRef.current ? 0 : Math.min(1, rms * 12));
        if (phaseRef.current === "speaking") {
          output.getFloatTimeDomainData(outputSamples);
          let outputSum = 0;
          for (const sample of outputSamples) outputSum += sample * sample;
          setSpeakerLevel(
            Math.min(1, Math.sqrt(outputSum / outputSamples.length) * 7),
          );
        } else setSpeakerLevel(0);
        const current = phaseRef.current;
        if (mutedRef.current) return;
        // Speaker echo must never start another turn. The existing Interrupt
        // control stops playback explicitly; resume after the acoustic tail.
        if (current === "speaking" || performance.now() < listenAfterRef.current) {
          loudFrames = 0;
          return;
        }
        const threshold = Math.max(0.012, noise * 3);
        if (current === "listening") {
          if (rms > threshold) {
            loudFrames += 1;
            if (loudFrames >= START_FRAMES) {
              loudFrames = 0;
              quietSince = 0;
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
    } catch {
      if (session === sessionRef.current) {
        stop();
        setError("Audio couldn’t start. Please try again.");
      }
    }
  }, [beginUtterance, endUtterance, go, stopSpeaking, stop]);

  useEffect(() => () => stop(), [stop]);

  const last = turns.slice(-2);
  const active = phase !== "idle";

  return (
    <div className="live-studio">
      <header className="live-heading">
        <h1>
          A little less typing.
          <br />A little more talking.
        </h1>
        <p>Ask about your meetings, out loud.</p>
      </header>
      <div className="live-stage" data-phase={phase}>
        <div className="live-mascot-halo" aria-hidden="true" />
        <TalkingMascot phase={phase} level={speakerLevel} muted={muted} />
        <div className="live-level" aria-hidden="true">
          {[0.45, 0.7, 1, 0.75, 0.5].map((height, index) => (
            <span
              key={index}
              style={{
                transform: `scaleY(${active && !muted ? 0.2 + level * height : 0.15})`,
              }}
            />
          ))}
        </div>
      </div>
      <div className="live-status" role="status">
        <span data-active={active && !muted} />
        {starting
          ? "Waiting for microphone access…"
          : muted
            ? "Microphone paused"
            : PHASE_LABEL[phase]}
      </div>
      <div className="live-controls">
        {active ? (
          <>
            <Button
              variant="outline"
              size="lg"
              aria-pressed={muted}
              onClick={() => {
                const next = !mutedRef.current;
                mutedRef.current = next;
                setMuted(next);
                streamRef.current?.getAudioTracks().forEach((track) => {
                  track.enabled = !next;
                });
                if (next && recorderRef.current?.state === "recording") {
                  recorderRef.current.onstop = null;
                  recorderRef.current.stop();
                  go("listening");
                }
              }}
            >
              {muted ? (
                <MicOff aria-hidden="true" />
              ) : (
                <Mic aria-hidden="true" />
              )}
              {muted ? "Unmute" : "Mute"}
            </Button>
            {phase === "speaking" && (
              <Button
                variant="outline"
                size="lg"
                onClick={() => {
                  stopSpeaking();
                  go("listening");
                }}
              >
                <VolumeX aria-hidden="true" />
                Interrupt
              </Button>
            )}
            <Button variant="destructive" size="lg" onClick={stop}>
              <PhoneOff aria-hidden="true" />
              End
            </Button>
          </>
        ) : starting ? (
          <Button variant="outline" size="lg" onClick={stop}>
            Cancel
          </Button>
        ) : (
          <Button variant="brand" size="lg" onClick={() => void start()}>
            <Mic aria-hidden="true" />
            Start talking
          </Button>
        )}
      </div>
      <p className="live-helper">
        {active
          ? "Speak naturally. You can interrupt Wilco."
          : "Your microphone turns on only when you start."}
      </p>
      {error && (
        <p role="alert" className="live-error">
          {error}
        </p>
      )}
      {last.length > 0 ? (
        <section className="live-transcript" aria-label="Latest exchange">
          {last.map((turn, index) => (
            <div key={`${turns.length}-${index}`}>
              <span>{turn.role === "user" ? "You" : "Wilco"}</span>
              <p>{turn.content}</p>
            </div>
          ))}
          {last[0]?.language && LANGUAGE_LABELS[last[0].language] && (
            <small>{LANGUAGE_LABELS[last[0].language]}</small>
          )}
        </section>
      ) : (
        <div className="live-starters">
          <span>Try asking</span>
          <p>“What did we decide in our last meeting?”</p>
          <Link href="/memory">Prefer to type? Open Memory</Link>
        </div>
      )}
    </div>
  );
}
