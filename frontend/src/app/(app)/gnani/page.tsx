"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AudioLines, Brain, CircleCheck, Fingerprint, Loader2, Mic, Radio, Square, Trash2, Volume2 } from "lucide-react";
import { api, type GnaniModels, type VoiceUpdate } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const LANGUAGES: Array<{ code: string; label: string; sample: string }> = [
  { code: "hi-en", label: "Hinglish", sample: "Vedant, login bug Friday tak fix kar dena, release usi pe blocked hai." },
  { code: "en-IN", label: "English", sample: "Vedant will fix the login bug by Friday; the release is blocked on it." },
  { code: "hi-IN", label: "हिन्दी", sample: "वेदांत शुक्रवार तक लॉगिन बग ठीक करेंगे, रिलीज़ उसी पर रुकी है।" },
  { code: "mr-IN", label: "मराठी", sample: "वेदांत शुक्रवारपर्यंत लॉगिन बग दुरुस्त करेल, रिलीज त्यावर अडकले आहे." },
  { code: "bn-IN", label: "বাংলা", sample: "বেদান্ত শুক্রবারের মধ্যে লগইন বাগ ঠিক করবে, রিলিজ তার উপর আটকে আছে।" },
  { code: "gu-IN", label: "ગુજરાતી", sample: "વેદાંત શુક્રવાર સુધીમાં લોગિન બગ ઠીક કરશે, રિલીઝ તેના પર અટકેલી છે." },
  { code: "pa-IN", label: "ਪੰਜਾਬੀ", sample: "ਵੇਦਾਂਤ ਸ਼ੁੱਕਰਵਾਰ ਤੱਕ ਲੌਗਇਨ ਬੱਗ ਠੀਕ ਕਰੇਗਾ, ਰਿਲੀਜ਼ ਉਸੇ 'ਤੇ ਰੁਕੀ ਹੈ।" },
  { code: "ta-IN", label: "தமிழ்", sample: "வேதாந்த் வெள்ளிக்கிழமைக்குள் லாகின் பிழையை சரிசெய்வார், வெளியீடு அதில் நிற்கிறது." },
  { code: "te-IN", label: "తెలుగు", sample: "వేదాంత్ శుక్రవారం లోగా లాగిన్ బగ్‌ను సరిచేస్తాడు, విడుదల దానిపై ఆగి ఉంది." },
  { code: "kn-IN", label: "ಕನ್ನಡ", sample: "ವೇದಾಂತ್ ಶುಕ್ರವಾರದೊಳಗೆ ಲಾಗಿನ್ ದೋಷವನ್ನು ಸರಿಪಡಿಸುತ್ತಾರೆ, ಬಿಡುಗಡೆ ಅದರ ಮೇಲೆ ನಿಂತಿದೆ." },
  { code: "ml-IN", label: "മലയാളം", sample: "വെള്ളിയാഴ്ചയ്ക്കകം വേദാന്ത് ലോഗിൻ ബഗ് പരിഹരിക്കും, റിലീസ് അതിൽ കുടുങ്ങിയിരിക്കുന്നു." },
];

const LANGUAGE_NAMES: Record<string, string> = {
  "hi-IN": "Hindi", "en-IN": "English", "ta-IN": "Tamil", "te-IN": "Telugu", "kn-IN": "Kannada", "ml-IN": "Malayalam",
  "mr-IN": "Marathi", "bn-IN": "Bengali", "gu-IN": "Gujarati", "pa-IN": "Punjabi", "or-IN": "Odia",
};

/** Where each Gnani model runs inside Wilco. */
const IN_WILCO = [
  { model: "Prisma v3", icon: Mic, uses: ["Transcribes every meeting, Hinglish and 10+ Indian languages", "Hears Wilco Live and spoken questions", "Auto-detects the language for each answer"] },
  { model: "Timbre v2.5 + v3", icon: Volume2, uses: ["Wilco's voice in Google Meet calls", "Spoken replies in Wilco Live, in your language", "Listen to meeting notes in 11 languages"] },
  { model: "Timbre voice cloning", icon: Fingerprint, uses: ["Your update read in your own voice in a call you'll miss", "Opt-in, your voice only, deletable anytime"] },
  { model: "Evon v3.3", icon: Brain, uses: ["Answers Wilco Live when the team hosts it", "Gemini takes over if Evon is unreachable"] },
];

function useRecorder(maxSeconds: number) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const timerRef = useRef<number | null>(null);
  const resolveRef = useRef<((blob: Blob | null) => void) | null>(null);

  const stop = useCallback(() => {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  }, []);

  const start = useCallback(async (): Promise<Blob | null> => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (event) => event.data.size && chunks.push(event.data);
    const done = new Promise<Blob | null>((resolve) => { resolveRef.current = resolve; });
    recorder.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
      if (timerRef.current) window.clearInterval(timerRef.current);
      setRecording(false);
      resolveRef.current?.(chunks.length ? new Blob(chunks, { type: recorder.mimeType || "audio/webm" }) : null);
    };
    recorderRef.current = recorder;
    recorder.start();
    setSeconds(0);
    setRecording(true);
    const began = performance.now();
    timerRef.current = window.setInterval(() => {
      const elapsed = (performance.now() - began) / 1000;
      setSeconds(Math.floor(elapsed));
      if (elapsed >= maxSeconds) recorder.stop();
    }, 200);
    return done;
  }, [maxSeconds]);

  useEffect(() => () => { stop(); if (timerRef.current) window.clearInterval(timerRef.current); }, [stop]);
  return { recording, seconds, start, stop };
}

function playBase64(audio: string) {
  const element = new Audio(`data:audio/mpeg;base64,${audio}`);
  return element.play().then(() => element);
}

function ModelChip({ children }: { children: React.ReactNode }) {
  return <Badge variant="secondary" className="font-mono text-[11px]">{children}</Badge>;
}

function PrismaCard({ model }: { model?: GnaniModels["prisma"] }) {
  const recorder = useRecorder(30);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Awaited<ReturnType<typeof api.gnaniPrisma>> | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    if (recorder.recording) return recorder.stop();
    setError(null);
    setResult(null);
    try {
      const clip = await recorder.start();
      if (!clip) return;
      setBusy(true);
      setResult(await api.gnaniPrisma(clip));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Couldn't use the microphone.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Mic className="size-4 text-primary" aria-hidden="true" />Prisma · speech to text</CardTitle>
        <CardDescription>Speak in any Indian language, or mix Hindi and English mid-sentence. Prisma detects the language on its own.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => void toggle()} disabled={busy} variant={recorder.recording ? "destructive" : "default"}>
            {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : recorder.recording ? <Square aria-hidden="true" /> : <Mic aria-hidden="true" />}
            {busy ? "Transcribing" : recorder.recording ? `Stop · ${recorder.seconds}s` : "Speak"}
          </Button>
          {model && <ModelChip>{model.model} · {model.mode}</ModelChip>}
        </div>
        {result && (
          <div className="flex flex-col gap-2 rounded-lg bg-muted px-3 py-3">
            <p className="text-base leading-relaxed">{result.text || "I didn't catch any speech. Try again a little closer to the mic."}</p>
            <div className="flex flex-wrap gap-1.5">
              {result.language && <ModelChip>{LANGUAGE_NAMES[result.language] ?? result.language} detected</ModelChip>}
              <ModelChip>{Math.round(result.latency_ms)} ms</ModelChip>
              {result.speakers > 1 && <ModelChip>{result.speakers} speakers</ModelChip>}
            </div>
          </div>
        )}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      </CardContent>
    </Card>
  );
}

function TimbreCard() {
  const [language, setLanguage] = useState("ta-IN");
  const [text, setText] = useState(LANGUAGES.find((item) => item.code === "ta-IN")!.sample);
  const [busy, setBusy] = useState(false);
  const [meta, setMeta] = useState<{ model: string; voice: string; latency_ms: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const label = LANGUAGES.find((item) => item.code === language)?.label ?? language;

  async function speak() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.gnaniTimbre(text, language);
      setMeta(result);
      await playBase64(result.audio);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Timbre couldn't speak that.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Volume2 className="size-4 text-primary" aria-hidden="true" />Timbre · text to speech</CardTitle>
        <CardDescription>The voice Wilco speaks with in calls and in Live. Pick a language and hear the same update.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Select value={language} onValueChange={(next) => {
          if (!next) return;
          setLanguage(next);
          setText(LANGUAGES.find((item) => item.code === next)?.sample ?? "");
          setMeta(null);
        }}>
          <SelectTrigger aria-label="Language" className="w-44"><SelectValue>{() => label}</SelectValue></SelectTrigger>
          <SelectContent>{LANGUAGES.map((item) => <SelectItem key={item.code} value={item.code}>{item.label}</SelectItem>)}</SelectContent>
        </Select>
        <Textarea value={text} onChange={(event) => setText(event.target.value)} rows={3} maxLength={600} aria-label="Text to speak" />
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => void speak()} disabled={busy || !text.trim()}>
            {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Volume2 aria-hidden="true" />}Speak
          </Button>
          {meta && <><ModelChip>{meta.model}</ModelChip><ModelChip>voice {meta.voice}</ModelChip><ModelChip>{Math.round(meta.latency_ms)} ms</ModelChip></>}
        </div>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      </CardContent>
    </Card>
  );
}

function VoiceCloneCard({ status, demo, onChange }: { status?: GnaniModels["voice_clone"]; demo?: boolean; onChange: () => void }) {
  const recorder = useRecorder(25);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [line, setLine] = useState("Hi team, quick update: payments are live, and I'm blocked on the KYC keys.");
  const [meetingUrl, setMeetingUrl] = useState("");
  const [update, setUpdate] = useState("");
  const [updates, setUpdates] = useState<VoiceUpdate[]>([]);
  const enrolled = Boolean(status?.enrolled);

  const loadUpdates = useCallback(async () => {
    try { setUpdates(await api.voiceUpdates()); } catch {}
  }, []);
  useEffect(() => { if (enrolled) void loadUpdates(); }, [enrolled, loadUpdates]);

  async function run(label: string, work: () => Promise<void>) {
    setBusy(label);
    setError(null);
    try { await work(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Something went wrong. Try again."); }
    finally { setBusy(null); }
  }

  async function record() {
    if (recorder.recording) return recorder.stop();
    await run("record", async () => {
      const clip = await recorder.start();
      if (!clip) return;
      setBusy("enroll");
      await api.enrollVoiceClone(clip);
      onChange();
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Fingerprint className="size-4 text-primary" aria-hidden="true" />Timbre voice cloning · your voice</CardTitle>
        <CardDescription>Missing a stand-up? Leave a typed update and Wilco says it in the call in your voice, announced as an AI copy.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {demo ? (
          <p className="text-sm text-muted-foreground">Voice cloning needs a free account: your voice is only ever yours. Everything else on this page works in the demo.</p>
        ) : !enrolled ? (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-muted-foreground">Read anything aloud for 10 to 20 seconds in a quiet place. Only the voice embedding is kept, never the recording.</p>
            <label className="flex items-start gap-2 text-sm">
              <Checkbox checked={consent} onCheckedChange={(checked) => setConsent(Boolean(checked))} className="mt-0.5" />
              <span>This is my own voice, and I agree to Wilco keeping an AI copy of it that only I can use. I can delete it anytime.</span>
            </label>
            <div className="flex items-center gap-2">
              <Button onClick={() => void record()} disabled={!consent || busy === "enroll"} variant={recorder.recording ? "destructive" : "default"}>
                {busy === "enroll" ? <Loader2 className="animate-spin" aria-hidden="true" /> : recorder.recording ? <Square aria-hidden="true" /> : <Mic aria-hidden="true" />}
                {busy === "enroll" ? "Learning your voice" : recorder.recording ? `Stop · ${recorder.seconds}s` : "Record my voice"}
              </Button>
              {status && <ModelChip>{status.model}</ModelChip>}
            </div>
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-2">
              <Label htmlFor="clone-line">Hear yourself</Label>
              <Textarea id="clone-line" value={line} onChange={(event) => setLine(event.target.value)} rows={2} maxLength={600} />
              <div className="flex flex-wrap items-center gap-2">
                <Button onClick={() => void run("speak", async () => { await playBase64((await api.speakInMyVoice(line)).audio); })} disabled={busy !== null || !line.trim()}>
                  {busy === "speak" ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Volume2 aria-hidden="true" />}Say it in my voice
                </Button>
                <Button variant="outline" onClick={() => void run("delete", async () => { await api.deleteVoiceClone(); setUpdates([]); onChange(); })} disabled={busy !== null}>
                  <Trash2 aria-hidden="true" />Delete my voice
                </Button>
                {status && <ModelChip>{status.model}</ModelChip>}
              </div>
            </div>
            <form className="flex flex-col gap-2 border-t pt-4" onSubmit={(event) => {
              event.preventDefault();
              void run("update", async () => { await api.createVoiceUpdate(meetingUrl, update); setUpdate(""); await loadUpdates(); });
            }}>
              <Label htmlFor="update-meeting">Leave an update for a call you'll miss</Label>
              <Input id="update-meeting" value={meetingUrl} onChange={(event) => setMeetingUrl(event.target.value)} placeholder="https://meet.google.com/abc-defg-hij" required />
              <Textarea value={update} onChange={(event) => setUpdate(event.target.value)} rows={2} maxLength={800} placeholder="Yesterday: payments shipped. Today: KYC. Blocked on: sandbox keys." aria-label="Your update" required />
              <div className="flex items-center gap-2">
                <Button type="submit" disabled={busy !== null}>{busy === "update" ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Radio aria-hidden="true" />}Leave update</Button>
                <p className="text-xs text-muted-foreground">In the call, anyone says “Wilco, play updates”.</p>
              </div>
            </form>
            {updates.length > 0 && (
              <ul className="flex flex-col gap-2">
                {updates.map((item) => (
                  <li key={item.id} className="flex items-start justify-between gap-3 rounded-lg bg-muted px-3 py-2 text-sm">
                    <div className="min-w-0">
                      <p className="line-clamp-2">{item.text}</p>
                      <p className="text-xs text-muted-foreground">{item.meeting_url.replace("https://", "")} · {item.delivered_at ? "played in the call" : "waiting for the call"}</p>
                    </div>
                    {!item.delivered_at && (
                      <Button size="icon-sm" variant="ghost" aria-label="Delete update" onClick={() => void run("del", async () => { await api.deleteVoiceUpdate(item.id); await loadUpdates(); })}>
                        <Trash2 aria-hidden="true" />
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      </CardContent>
    </Card>
  );
}

function EvonCard({ status }: { status?: GnaniModels["evon"] }) {
  const [prompt, setPrompt] = useState("Kal ki meeting ka ek line mein summary do: launch Friday, pricing same.");
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState<{ reply: string; latency_ms: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Brain className="size-4 text-primary" aria-hidden="true" />Evon v3.3 · Indic LLM</CardTitle>
        <CardDescription>Gnani's open-weights model for 11 Indian languages. When the team hosts it, Wilco Live answers with Evon, and Gemini takes over if it's unreachable.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {status?.configured ? (
          <>
            <Textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={2} aria-label="Ask Evon" />
            <div className="flex flex-wrap items-center gap-2">
              <Button disabled={busy || !prompt.trim()} onClick={() => {
                setBusy(true); setError(null);
                api.gnaniEvon(prompt).then(setReply).catch((cause) => setError(cause instanceof Error ? cause.message : "Evon didn't answer.")).finally(() => setBusy(false));
              }}>{busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Brain aria-hidden="true" />}Ask Evon</Button>
              <ModelChip>{status.model}</ModelChip>
              {reply && <ModelChip>{Math.round(reply.latency_ms)} ms</ModelChip>}
            </div>
            {reply && <p className="rounded-lg bg-muted px-3 py-2 text-sm leading-relaxed">{reply.reply}</p>}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">Not connected on this server. Point <code className="font-mono">EVON_URL</code> at any OpenAI-compatible server (vLLM or llama.cpp) running <code className="font-mono">gnani-evon-v3.3-30B-A3B</code>.</p>
        )}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      </CardContent>
    </Card>
  );
}

export default function GnaniLabPage() {
  const [models, setModels] = useState<GnaniModels | null>(null);
  const refresh = useCallback(() => { api.gnaniModels().then(setModels).catch(() => setModels(null)); }, []);
  useEffect(() => { refresh(); }, [refresh]);

  return (
    <div className="flex w-full flex-col gap-6">
      <header className="flex flex-col gap-2">
        <h1 className="font-heading text-2xl font-semibold tracking-tight md:text-3xl">Built on Gnani</h1>
        <p className="max-w-2xl text-muted-foreground">Every voice in Wilco comes from Gnani's models: Prisma hears, Timbre speaks, and voice cloning lets your update speak for you. Try each one live.</p>
      </header>

      <section aria-label="Where each model runs in Wilco" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {IN_WILCO.map(({ model, icon: Icon, uses }) => (
          <div key={model} className="flex flex-col gap-2 rounded-xl border bg-card p-4">
            <p className="flex items-center gap-2 text-sm font-semibold"><Icon className="size-4 text-primary" aria-hidden="true" />{model}</p>
            <ul className="flex flex-col gap-1.5">
              {uses.map((use) => <li key={use} className="flex gap-1.5 text-xs leading-snug text-muted-foreground"><CircleCheck className="mt-px size-3.5 shrink-0 text-primary" aria-hidden="true" />{use}</li>)}
            </ul>
          </div>
        ))}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <PrismaCard model={models?.prisma} />
        <TimbreCard />
        <VoiceCloneCard status={models?.voice_clone} demo={models?.demo} onChange={refresh} />
        <EvonCard status={models?.evon} />
      </div>

      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <AudioLines className="size-3.5" aria-hidden="true" />
        Warp, Gnani's speech-to-speech model, has no public API yet. Wilco Live runs the same loop as Prisma, then an LLM, then Timbre.
      </p>
    </div>
  );
}
