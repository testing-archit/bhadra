"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowRight, Check, Mic, RotateCcw, ShieldCheck, Square, Trash2 } from "lucide-react";
import { api, ApiError, type VoiceProfileStatus } from "@/lib/api";
import { Button } from "@/components/ui/button";

const RECORD_SECONDS = 15;

export default function VoiceSetupPage() {
  const [profile, setProfile] = useState<VoiceProfileStatus | null>(null);
  const [clip, setClip] = useState<Blob | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [recording, setRecording] = useState(false);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    void api.getVoiceProfile().then(setProfile).catch((cause) => setError(cause instanceof ApiError ? cause.message : "Voice setup could not load."));
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (recorderRef.current?.state === "recording") recorderRef.current.stop();
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  async function start() {
    setError(null);
    setClip(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false });
      streamRef.current = stream;
      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : undefined;
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      recorderRef.current = recorder;
      const parts: BlobPart[] = [];
      recorder.ondataavailable = (event) => { if (event.data.size) parts.push(event.data); };
      recorder.onstop = () => {
        if (timerRef.current) clearInterval(timerRef.current);
        stream.getTracks().forEach((track) => track.stop());
        setRecording(false);
        const result = new Blob(parts, { type: recorder.mimeType || "audio/webm" });
        if (result.size) setClip(result);
      };
      setSeconds(0);
      recorder.start();
      setRecording(true);
      timerRef.current = setInterval(() => setSeconds((elapsed) => {
        if (elapsed + 1 >= RECORD_SECONDS) {
          recorder.stop();
          return RECORD_SECONDS;
        }
        return elapsed + 1;
      }), 1000);
    } catch {
      setError("Microphone access is needed to record your voice.");
    }
  }

  async function save() {
    if (!clip || !consent) return;
    setBusy(true);
    setError(null);
    try {
      await api.enrollVoice(clip);
      setProfile(await api.getVoiceProfile());
      setClip(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save your voice profile.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api.deleteVoiceProfile();
      setProfile(await api.getVoiceProfile());
      setClip(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not remove your voice profile.");
    } finally {
      setBusy(false);
    }
  }

  return <div className="mx-auto max-w-2xl pb-12">
    <Link href="/dashboard" className="text-xs font-semibold text-primary hover:underline">← Back to briefing</Link>
    <p className="mt-10 inline-flex rounded-full bg-tint-sky px-3 py-1 text-xs font-semibold text-tint-sky-foreground">One-time setup</p>
    <h1 className="mt-2 font-heading text-4xl font-semibold tracking-tight">Let Wilco learn your voice</h1>
    <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">A short recording helps Wilco tell when you spoke in a meeting, even when Meet captions miss your name.</p>
    <div className="mt-8 rounded-3xl border bg-card p-6 shadow-sm sm:p-8">
      {profile?.enrolled ? <div>
        <span className="grid size-12 place-items-center rounded-2xl bg-success/10 text-success"><Check className="size-6" /></span>
        <h2 className="mt-5 font-heading text-xl font-semibold">Your voice is set up</h2>
        <p className="mt-2 text-sm text-muted-foreground">Wilco will use your profile to identify your speech when the match is clear. You can replace or remove it at any time.</p>
        <div className="mt-6 flex flex-wrap gap-3"><Button variant="outline" onClick={() => setProfile({ ...profile, enrolled: false })}><RotateCcw className="size-4" /> Record again</Button><Button variant="outline" onClick={() => void remove()} disabled={busy}><Trash2 className="size-4" /> Remove profile</Button><Link href="/dashboard" className="inline-flex h-9 items-center gap-2 px-3 text-sm font-semibold text-primary">Open briefing <ArrowRight className="size-4" /></Link></div>
      </div> : !profile ? <p className="text-sm text-muted-foreground">Checking voice setup…</p> : !profile.available ? <p className="text-sm text-muted-foreground">Voice matching is being prepared on this server. Your meetings and notes still work.</p> : <>
        <div className="flex items-start gap-4"><span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-primary/10 text-primary"><Mic className="size-6" /></span><div><h2 className="font-heading text-xl font-semibold">Speak for 15 seconds</h2><p className="mt-1 text-sm leading-6 text-muted-foreground">Use your normal speaking voice. You can speak in English, Hindi, or another language you use at work. A quiet room helps.</p></div></div>
        <div className="mt-6 rounded-2xl bg-muted/60 p-5"><p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">You can say</p><p className="mt-2 text-base leading-7">“Hi, I’m [your name]. Today I’m sharing an update with my team. We’ll decide what to do next and who owns each task.”</p></div>
        <div className="mt-7 flex flex-wrap items-center gap-4">
          {recording ? <Button onClick={() => recorderRef.current?.stop()}><Square className="size-4" /> Stop recording · {seconds}s</Button> : <Button onClick={() => void start()}><Mic className="size-4" /> {clip ? "Record again" : "Start recording"}</Button>}
          {recording && <div className="h-1.5 w-28 overflow-hidden rounded-full bg-primary/10"><div className="h-full bg-primary transition-all" style={{ width: `${(seconds / RECORD_SECONDS) * 100}%` }} /></div>}
          {clip && !recording && <span className="text-xs font-medium text-success">Recording ready</span>}
        </div>
        {clip && <label className="mt-7 flex items-start gap-3 text-sm leading-6"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} className="mt-1 size-4 accent-primary" /><span>I agree to create a voice profile for speaker matching in my organization’s meetings.</span></label>}
        {clip && <Button className="mt-5" disabled={!consent || busy} onClick={() => void save()}>{busy ? "Saving…" : "Save my voice"}</Button>}
      </>}
    </div>
    <p className="mt-5 flex items-start gap-2 text-xs leading-5 text-muted-foreground"><ShieldCheck className="mt-0.5 size-4 shrink-0" /> Wilco stores an encrypted voice pattern, not this raw setup recording. Uncertain meeting speakers stay unnamed until someone corrects them.</p>
    {error && <p className="mt-4 text-sm text-destructive" role="alert">{error}</p>}
  </div>;
}
