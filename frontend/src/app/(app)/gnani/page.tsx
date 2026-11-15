"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowRight, AudioLines, Brain, PhoneCall, Fingerprint, ListChecks, Loader2, Mic, Radio, Square, Trash2, Volume2 } from "lucide-react";
import { api, type GnaniModels, type VoiceUpdate } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import "../support-pages.css";
import "../voice-lab.css";

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
  return <Badge variant="secondary" className="text-[11px] font-medium">{children}</Badge>;
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
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Mic className="size-4 text-primary" aria-hidden="true" />Prisma · speech to text</CardTitle>
        <CardDescription>Speak in English, Hindi, or a mix. See the transcript and detected language.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => void toggle()} disabled={busy} variant={recorder.recording ? "destructive" : "default"}>
            {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : recorder.recording ? <Square aria-hidden="true" /> : <Mic aria-hidden="true" />}
            {busy ? "Transcribing" : recorder.recording ? `Stop · ${recorder.seconds}s` : "Speak"}
          </Button>
          {model && <ModelChip>{model.model} · {model.mode}</ModelChip>}
        </div>
        {!result && (
          <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
            {recorder.recording ? "Listening… tap Stop when you're done." : busy ? "Prisma is transcribing…" : (
              <span className="flex flex-col gap-2">
                <span>Your transcript will appear here.</span>
                <span className="text-xs">Try: “Vedant, login bug Friday tak fix kar dena.”</span>
              </span>
            )}
          </div>
        )}
        {result && (
          <div className="flex flex-1 flex-col gap-2 rounded-lg bg-muted px-3 py-3">
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
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Volume2 className="size-4 text-primary" aria-hidden="true" />Timbre · text to speech</CardTitle>
        <CardDescription>Pick a language and hear an engineering update in Wilco&apos;s voice.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
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
  const [briefing, setBriefing] = useState("");
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
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Fingerprint className="size-4 text-primary" aria-hidden="true" />Timbre voice cloning · your AI stand-in</CardTitle>
        <CardDescription>With your consent, an AI stand-in can deliver your update in a call you miss. It identifies itself as AI and sends questions back to you.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-4">
        {demo ? (
          <div className="flex flex-1 flex-col gap-3">
            <ol className="flex flex-col gap-2 rounded-lg bg-muted px-3 py-3 text-sm" aria-label="How a stand-in sounds in a call">
              <li><span className="font-medium">Wilco:</span> AI stand-in here for Vedant. It speaks in an AI copy of his voice and answers only from his briefing.</li>
              <li><span className="font-medium">Ravi:</span> Wilco, ask Vedant, is KYC done?</li>
              <li><span className="font-medium">Vedant&apos;s AI stand-in</span> <span className="text-xs text-muted-foreground">(AI voice)</span>: KYC is waiting on the sandbox keys; I&apos;ll confirm once they arrive.</li>
              <li><span className="font-medium">Ravi:</span> Can he take the Jira migration?</li>
              <li><span className="font-medium">Vedant&apos;s AI stand-in</span> <span className="text-xs text-muted-foreground">(AI voice)</span>: I don&apos;t have that from Vedant. I&apos;ll pass it on.</li>
            </ol>
            <p className="text-center text-xs text-muted-foreground">Cloning needs a free account, because your voice is only ever yours. Vedant sees every question afterwards.</p>
          </div>
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
              void run("update", async () => { await api.createVoiceUpdate(meetingUrl, update, briefing); setUpdate(""); setBriefing(""); await loadUpdates(); });
            }}>
              <Label htmlFor="update-meeting">Send your AI stand-in to a call you'll miss</Label>
              <Input id="update-meeting" value={meetingUrl} onChange={(event) => setMeetingUrl(event.target.value)} placeholder="https://meet.google.com/abc-defg-hij" required />
              <Textarea value={update} onChange={(event) => setUpdate(event.target.value)} rows={2} maxLength={800} placeholder="Your update. Yesterday: payments shipped. Today: KYC. Blocked on: sandbox keys." aria-label="Your update" required />
              <Textarea value={briefing} onChange={(event) => setBriefing(event.target.value)} rows={3} maxLength={3000} placeholder="What your stand-in may answer, e.g. KYC needs the sandbox keys from Razorpay; I'm fine moving the demo to Friday; don't commit me to new work." aria-label="Briefing for your AI stand-in" />
              <div className="flex items-center gap-2">
                <Button type="submit" disabled={busy !== null}>{busy === "update" ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Radio aria-hidden="true" />}Leave update</Button>
                <p className="text-xs text-muted-foreground">In the call: “Wilco, play updates” or “Wilco, ask {"<your name>"}, …”. It answers in your voice, says it&apos;s AI, and never commits you to anything.</p>
              </div>
            </form>
            {updates.length > 0 && (
              <ul className="flex flex-col gap-2">
                {updates.map((item) => (
                  <li key={item.id} className="flex items-start justify-between gap-3 rounded-lg bg-muted px-3 py-2 text-sm">
                    <div className="min-w-0">
                      <p className="line-clamp-2">{item.text}</p>
                      <p className="text-xs text-muted-foreground">{item.meeting_url.replace("https://", "")} · {item.delivered_at ? "played in the call" : "waiting for the call"}</p>
                      {item.qa.length > 0 && (
                        <ul className="mt-2 flex flex-col gap-1.5 border-l-2 border-primary/30 pl-2">
                          {item.qa.map((entry) => (
                            <li key={entry.at} className="text-xs">
                              <p><span className="font-medium">{entry.asked_by ?? "Someone"} asked:</span> {entry.question}</p>
                              <p className="text-muted-foreground">{entry.known ? `Your stand-in: ${entry.answer}` : "Your stand-in didn't know and said you'd follow up."}</p>
                            </li>
                          ))}
                        </ul>
                      )}
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
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Brain className="size-4 text-primary" aria-hidden="true" />Evon v3.3 · Indic LLM</CardTitle>
        <CardDescription>Optional self-hosted model for multilingual answers in Wilco Live.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
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
          <div className="flex flex-1 flex-col justify-center gap-1 rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
            <p className="font-medium text-foreground">Not connected on this server</p>
            <details className="mt-2"><summary className="cursor-pointer text-primary">Setup details</summary><p className="mt-2">Point <code className="rounded bg-muted px-1 text-xs">EVON_URL</code> at an OpenAI-compatible server running <code className="rounded bg-muted px-1 text-xs">gnani-evon-v3.3-30B-A3B</code>.</p></details>
          </div>
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
    <div className="signal-support voice-lab flex w-full flex-col gap-6">
      <section className="voice-lab-hero" aria-labelledby="voice-lab-title">
        <div className="voice-lab-intro">
          <span className="voice-lab-eyebrow"><AudioLines className="size-4" aria-hidden="true" /> Powered by Gnani AI</span>
          <h1 id="voice-lab-title">Make every voice count.</h1>
          <p>Multilingual speech becomes a transcript, clear follow-ups, and a voice your team can hear back.</p>
          <div className="voice-lab-actions">
            <a href="#voice-demos" className="voice-lab-primary">Try the voice tools <ArrowRight className="size-4" aria-hidden="true" /></a>
            <Link href="/live" className="voice-lab-secondary">Talk to Wilco</Link>
          </div>
        </div>
        <div className="voice-lab-path" aria-label="Wilco voice workflow: meeting speech, Prisma transcription, meeting actions, Timbre playback">
          <div className="voice-lab-pulse" aria-hidden="true"><i /><i /><i /><i /><i /><i /><i /><i /><i /><i /><i /></div>
          <div className="voice-lab-node"><span><AudioLines aria-hidden="true" /></span><strong>Team speech</strong><small>Mixed languages</small></div>
          <div className="voice-lab-connector" aria-hidden="true" />
          <div className="voice-lab-node"><span><Mic aria-hidden="true" /></span><strong>Prisma</strong><small>Transcript</small></div>
          <div className="voice-lab-connector" aria-hidden="true" />
          <div className="voice-lab-node"><span><ListChecks aria-hidden="true" /></span><strong>Wilco</strong><small>Decisions and owners</small></div>
          <div className="voice-lab-connector" aria-hidden="true" />
          <div className="voice-lab-node"><span><Volume2 aria-hidden="true" /></span><strong>Timbre</strong><small>Spoken recap</small></div>
        </div>
      </section>

      <div id="voice-demos" className="voice-lab-demo-heading"><div><h2>Try the models</h2><p>Speak or edit the sample line. Results come from the connected services.</p></div><span>{models?.demo ? "Demo workspace" : "Voice tools"}</span></div>
      <div className="voice-lab-demo-grid grid gap-6 lg:grid-cols-2">
        <PrismaCard model={models?.prisma} />
        <TimbreCard />
      </div>

      <details className="voice-lab-advanced">
        <summary><span><strong>Advanced models</strong><small>AI stand-in and optional self-hosted answers</small></span><ArrowRight className="size-5" aria-hidden="true" /></summary>
        <div className="grid gap-6 p-4 lg:grid-cols-2">
          <VoiceCloneCard status={models?.voice_clone} demo={models?.demo} onChange={refresh} />
          <EvonCard status={models?.evon} />
        </div>
      </details>

      <Link href="/recap" className="voice-lab-recap flex items-center justify-between gap-4 rounded-xl border bg-card px-4 py-3 transition-colors hover:bg-muted">
        <span className="flex items-center gap-3"><PhoneCall className="size-5 shrink-0 text-primary" aria-hidden="true" /><span><span className="block text-sm font-semibold">Have a call recording?</span><span className="block text-xs text-muted-foreground">Upload it for a recap and follow-ups.</span></span></span>
        <ArrowRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      </Link>
    </div>
  );
}
