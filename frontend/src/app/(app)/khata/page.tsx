"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, MessageCircle, Mic, Send, Square, Trash2, Volume2 } from "lucide-react";
import { api, type KhataLedger } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const LANGUAGES = [
  { code: "hi-en", label: "Hinglish" }, { code: "hi-IN", label: "हिन्दी" }, { code: "mr-IN", label: "मराठी" },
  { code: "gu-IN", label: "ગુજરાતી" }, { code: "bn-IN", label: "বাংলা" }, { code: "pa-IN", label: "ਪੰਜਾਬੀ" },
  { code: "ta-IN", label: "தமிழ்" }, { code: "te-IN", label: "తెలుగు" }, { code: "kn-IN", label: "ಕನ್ನಡ" },
  { code: "ml-IN", label: "മലയാളം" }, { code: "en-IN", label: "English" },
];
const EXAMPLES = ["Gupta ji ne 500 ka atta aur dal udhaar liya", "Meena didi ne 300 jama kiye", "Murugan anna 450 rupees kadan vaangitu ponaar"];
const rupees = (value: number) => `₹${Math.round(value).toLocaleString("en-IN")}`;

export default function KhataPage() {
  const [ledger, setLedger] = useState<KhataLedger | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [heard, setHeard] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [language, setLanguage] = useState("hi-en");
  const [reminder, setReminder] = useState<{ customer: string; text: string; audio: string | null } | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);

  const load = useCallback(() => { api.khata().then(setLedger).catch(() => setError("Couldn't load the khata.")); }, []);
  useEffect(() => { load(); }, [load]);

  async function run(label: string, work: () => Promise<void>) {
    setBusy(label);
    setError(null);
    try { await work(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Something went wrong."); }
    finally { setBusy(null); }
  }

  async function toggleVoice() {
    if (recorderRef.current?.state === "recording") return recorderRef.current.stop();
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => event.data.size && chunks.push(event.data);
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        setRecording(false);
        const clip = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
        void run("voice", async () => {
          const result = await api.khataVoice(clip);
          setHeard(result.heard);
          setLedger(result);
        });
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecording(true);
      window.setTimeout(() => recorder.state === "recording" && recorder.stop(), 30_000);
    } catch {
      setError("Allow the microphone to speak entries, or type them below.");
    }
  }

  return (
    <div className="flex w-full flex-col gap-6">
      <header className="flex flex-col gap-2">
        <h1 className="font-heading text-2xl font-semibold tracking-tight md:text-3xl">Voice khata</h1>
        <p className="max-w-2xl text-muted-foreground">Keep the shop&apos;s udhaar book by speaking, in any Indian language. Gnani Prisma hears it, Wilco writes it down, and reminders go out politely in your customer&apos;s language.</p>
      </header>

      <Card>
        <CardContent className="flex flex-col gap-4 pt-6">
          <div className="flex flex-col items-center gap-3 text-center">
            <Button size="lg" variant={recording ? "destructive" : "brand"} className="h-14 rounded-full px-8 text-base" onClick={() => void toggleVoice()} disabled={busy === "voice"}>
              {busy === "voice" ? <Loader2 className="animate-spin" aria-hidden="true" /> : recording ? <Square aria-hidden="true" /> : <Mic aria-hidden="true" />}
              {busy === "voice" ? "Writing it down" : recording ? "Stop" : "Speak an entry"}
            </Button>
            <p className="text-sm text-muted-foreground">Try: “{EXAMPLES[0]}”</p>
            {heard && <p className="rounded-lg bg-muted px-3 py-2 text-sm">Heard: “{heard}” <Badge variant="secondary" className="ml-1 text-[11px]">Gnani Prisma</Badge></p>}
          </div>
          <form className="flex gap-2" onSubmit={(event) => {
            event.preventDefault();
            void run("text", async () => { setLedger(await api.khataText(text)); setText(""); setHeard(null); });
          }}>
            <Input value={text} onChange={(event) => setText(event.target.value)} placeholder="Or type: Meena didi ne 300 jama kiye" aria-label="Type an entry" />
            <Button type="submit" variant="outline" disabled={busy !== null || text.trim().length < 3} aria-label="Add entry">
              {busy === "text" ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Send aria-hidden="true" />}
            </Button>
          </form>
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        </CardContent>
      </Card>

      {ledger && (
        <section aria-label="Totals" className="grid grid-cols-3 gap-3">
          {[["To collect", ledger.outstanding], ["Udhaar given", ledger.given], ["Received", ledger.received]].map(([label, value]) => (
            <div key={label as string} className="rounded-xl border bg-card p-4">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className="mt-1 text-xl font-semibold tabular-nums sm:text-2xl">{rupees(value as number)}</p>
            </div>
          ))}
        </section>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="h-full">
          <CardHeader>
            <CardTitle>Customers</CardTitle>
            <CardDescription>Who owes what. Send a reminder in their language as a WhatsApp message or a voice note.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-1 flex-col gap-3">
            <Select value={language} onValueChange={(next) => next && setLanguage(next)}>
              <SelectTrigger aria-label="Reminder language" className="w-44"><SelectValue>{() => `Remind in ${LANGUAGES.find((item) => item.code === language)?.label}`}</SelectValue></SelectTrigger>
              <SelectContent>{LANGUAGES.map((item) => <SelectItem key={item.code} value={item.code}>{item.label}</SelectItem>)}</SelectContent>
            </Select>
            {!ledger?.customers.length ? (
              <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">No customers yet. Speak your first entry above.</p>
            ) : (
              <ul className="flex flex-col divide-y rounded-lg border">
                {ledger.customers.map((item) => (
                  <li key={item.customer} className="flex items-center justify-between gap-3 px-3 py-2.5">
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium">{item.customer}</span>
                      <span className={`text-sm tabular-nums ${item.balance > 0 ? "text-destructive" : "text-muted-foreground"}`}>{item.balance > 0 ? `${rupees(item.balance)} due` : "Settled"}</span>
                    </span>
                    {item.balance > 0 && (
                      <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => void run(`remind:${item.customer}`, async () => {
                        setReminder(await api.khataReminder(item.customer, language, true));
                      })}>
                        {busy === `remind:${item.customer}` ? <Loader2 className="animate-spin" aria-hidden="true" /> : <MessageCircle aria-hidden="true" />}Remind
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {reminder && (
              <div className="flex flex-col gap-2 rounded-lg bg-muted px-3 py-3">
                <p className="text-sm leading-relaxed">{reminder.text}</p>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" nativeButton={false} render={<a href={`https://wa.me/?text=${encodeURIComponent(reminder.text)}`} target="_blank" rel="noopener noreferrer" />}>
                    <MessageCircle aria-hidden="true" />Send on WhatsApp
                  </Button>
                  {reminder.audio && (
                    <>
                      <Button size="sm" variant="outline" onClick={() => void new Audio(`data:audio/mpeg;base64,${reminder.audio}`).play()}>
                        <Volume2 aria-hidden="true" />Listen
                      </Button>
                      <Button size="sm" variant="ghost" nativeButton={false} render={<a href={`data:audio/mpeg;base64,${reminder.audio}`} download={`reminder-${reminder.customer}.mp3`} />}>
                        Voice note
                      </Button>
                    </>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">{reminder.audio ? "Voice by Gnani Timbre." : "Voice note unavailable right now; the text is ready."}</p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="h-full">
          <CardHeader>
            <CardTitle>Recent entries</CardTitle>
            <CardDescription>Exactly what was heard, so every line can be trusted or fixed.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-1 flex-col">
            {!ledger?.entries.length ? (
              <p className="flex flex-1 items-center justify-center rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">Entries appear here as you speak them.</p>
            ) : (
              <ul className="flex flex-col divide-y">
                {ledger.entries.slice(0, 20).map((entry) => (
                  <li key={entry.id} className="flex items-start justify-between gap-3 py-2.5">
                    <span className="min-w-0 text-sm">
                      <span className="font-medium">{entry.customer}</span>{" "}
                      <span className={entry.kind === "credit" ? "text-destructive" : "text-primary"}>{entry.kind === "credit" ? `took ${rupees(entry.amount)} udhaar` : `paid ${rupees(entry.amount)}`}</span>
                      {entry.note && <span className="text-muted-foreground"> · {entry.note}</span>}
                      {entry.said && <span className="block truncate text-xs text-muted-foreground">“{entry.said}”</span>}
                    </span>
                    <Button size="icon-sm" variant="ghost" aria-label={`Delete entry for ${entry.customer}`} onClick={() => void run("del", async () => setLedger(await api.khataDelete(entry.id)))}>
                      <Trash2 aria-hidden="true" />
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
