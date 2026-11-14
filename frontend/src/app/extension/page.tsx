import type { Metadata } from "next";
import Link from "next/link";
import { Wordmark } from "@/components/brand";
import {
  ArrowRight,
  Bell,
  Bot,
  Download,
  ExternalLink,
  ListChecks,
  LockKeyhole,
  Search,
  Sheet,
  Sparkles,
} from "lucide-react";

export const metadata: Metadata = { title: "Chrome extension" };

const storeUrl = process.env.NEXT_PUBLIC_CHROME_WEB_STORE_URL?.trim();
// Must match the "version" in the root manifest.json and the zip name in
// frontend/public/downloads/ — nothing enforces this automatically, so a
// bump here is a required step of every extension release, not optional.
const extensionVersion = "2.1.3";

const features = [
  { icon: Bot, title: "Invite the notetaker from the call", copy: "A small Charcha control sits in every Google Meet. One click sends the notetaker; it shows when it's waiting to be admitted, recording, or done." },
  { icon: Bell, title: "Know when notes are ready", copy: "A notification links straight to the transcript, summary and tasks a few minutes after the call ends. The toolbar badge shows REC while it records." },
  { icon: ListChecks, title: "Your tasks, one click away", copy: "Open the toolbar popup to see what's assigned to you across every meeting, and tick things off without opening the workspace." },
  { icon: Sparkles, title: "Ask from anywhere", copy: "Type mem and a space in the address bar, or right-click any selected text, to ask company memory about it." },
  { icon: Sheet, title: "Copy notes to Google Sheets", copy: "If your team tracks work in a spreadsheet, finished meetings add their tasks and summary to it automatically." },
  { icon: Search, title: "Invite automatically, if you want", copy: "Turn on auto-invite and the notetaker joins every Meet you join — once per call, never twice." },
];

const steps = [
  { title: "Download and unzip", detail: "Save the package, then extract the ZIP into a folder you'll keep on this computer." },
  { title: "Open Chrome extensions", detail: "Go to chrome://extensions in the address bar and turn on Developer mode." },
  { title: "Load the Charcha folder", detail: "Choose Load unpacked, select the extracted folder, then pin Charcha from Chrome's puzzle menu." },
];

export default function ExtensionPage() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="border-b bg-card/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <Link href="/" className="flex items-center gap-2.5" aria-label="Charcha home">
            <Wordmark />
          </Link>
          <Link href="/login" className="rounded-lg border bg-card px-3.5 py-2 text-sm font-medium transition-colors hover:bg-muted">
            Open workspace
          </Link>
        </div>
      </header>

      <section className="border-b bg-card">
        <div className="mx-auto grid grid-cols-1 max-w-6xl gap-12 px-5 py-16 sm:px-8 sm:py-20 lg:grid-cols-[1.1fr_.9fr] lg:items-center">
          <div>
            <p className="text-sm font-medium text-primary">Charcha for Chrome, version {extensionVersion}</p>
            <h1 className="mt-3 max-w-2xl text-4xl font-semibold leading-[1.08] tracking-tight sm:text-5xl">
              Send the notetaker without leaving the call.
            </h1>
            <p className="mt-5 max-w-xl text-lg leading-8 text-muted-foreground">
              Invite Charcha's notetaker into any Google Meet, follow it from the toolbar, and get the notes the moment they&apos;re
              written — all on the same account as the Charcha workspace.
            </p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              {storeUrl ? (
                <a href={storeUrl} target="_blank" rel="noreferrer" className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-primary px-5 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90">
                  Add to Chrome <ExternalLink className="size-4" />
                </a>
              ) : (
                <a href={`/downloads/charcha-extension-v${extensionVersion}.zip`} download className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-primary px-5 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90">
                  Download for Chrome <Download className="size-4" />
                </a>
              )}
              <a href="#install" className="inline-flex h-11 items-center justify-center gap-2 rounded-xl border bg-card px-5 text-sm font-semibold transition-colors hover:bg-muted">
                How to install <ArrowRight className="size-4" />
              </a>
            </div>
            {!storeUrl && (
              <p className="mt-4 max-w-xl text-sm leading-6 text-muted-foreground">
                Until the Chrome Web Store listing is approved, install it manually. After that, installs and updates happen automatically.
              </p>
            )}
          </div>

          {/* A faithful mock of the control the extension adds to Meet. */}
          <div className="relative mx-auto w-full max-w-md">
            <div className="overflow-hidden rounded-2xl border bg-[#202124] shadow-2xl">
              <div className="flex items-center gap-2 border-b border-white/10 px-4 py-2.5">
                <span className="size-2.5 rounded-full bg-white/15" />
                <span className="size-2.5 rounded-full bg-white/15" />
                <span className="size-2.5 rounded-full bg-white/15" />
                <span className="ml-2 text-xs text-white/50">meet.google.com/abc-defg-hij</span>
              </div>
              <div className="relative grid h-72 grid-cols-2 gap-2 p-3">
                {["Asha", "Ravi", "Neha", "You"].map((name) => (
                  <div key={name} className="flex items-end rounded-lg bg-white/[.06] p-2 text-xs text-white/60">{name}</div>
                ))}
                <div className="absolute bottom-5 left-5 w-64 rounded-2xl border border-white/10 bg-[#1D1A3B]/95 p-3 text-[#FAF7F1] shadow-xl">
                  <div className="flex items-center gap-2">
                    <span className="grid size-6 place-items-center rounded-lg bg-[#2E2A8C]"><img src="/charcha-mark.png" alt="" className="size-4 rounded" /></span>
                    <span className="text-[13px] font-semibold">Charcha</span>
                  </div>
                  <p className="mt-2.5 flex items-center gap-2 text-[13px] font-medium">
                    <span className="relative flex size-2"><span className="absolute inline-flex size-full animate-ping rounded-full bg-red-500/60 motion-reduce:animate-none" /><span className="relative size-2 rounded-full bg-red-500" /></span>
                    Recording this call
                  </p>
                  <p className="mt-1 text-xs leading-5 text-[#C8C4EB]">Notes, tasks and decisions appear in Charcha a few minutes after the call ends.</p>
                  <div className="mt-3 rounded-lg bg-red-500/15 py-2 text-center text-xs font-semibold text-red-300">Stop notetaker</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
        <h2 className="text-2xl font-semibold tracking-tight">What it does</h2>
        <div className="mt-8 grid grid-cols-1 gap-x-10 gap-y-8 sm:grid-cols-2 lg:grid-cols-3">
          {features.map(({ icon: Icon, title, copy }) => (
            <article key={title}>
              <Icon className="size-5 text-primary" />
              <h3 className="mt-3 font-semibold">{title}</h3>
              <p className="mt-1.5 text-sm leading-6 text-muted-foreground">{copy}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="install" className="scroll-mt-8 border-t bg-card">
        <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
          <h2 className="text-2xl font-semibold tracking-tight">Install in about two minutes</h2>
          <p className="mt-2 text-muted-foreground">Only needed while the Chrome Web Store listing is in review.</p>
          <ol className="mt-8 grid grid-cols-1 gap-4 lg:grid-cols-3">
            {steps.map((step, index) => (
              <li key={step.title} className="rounded-xl border bg-background p-5">
                <span className="grid size-7 place-items-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">{index + 1}</span>
                <h3 className="mt-4 font-semibold">{step.title}</h3>
                <p className="mt-1.5 text-sm leading-6 text-muted-foreground">{step.detail}</p>
              </li>
            ))}
          </ol>
          <div className="mt-6 flex items-start gap-3 rounded-xl border border-warning/40 bg-warning/10 p-4 text-sm leading-6">
            <LockKeyhole className="mt-0.5 size-4 shrink-0" />
            <p>Keep the extracted folder after installing — moving or deleting it disables the extension. Upgrading from version 1.x? Remove the old extension first; this version no longer needs microphone or tab-capture access.</p>
          </div>
        </div>
      </section>

      <footer className="border-t">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-5 py-6 text-sm text-muted-foreground sm:flex-row sm:justify-between sm:px-8">
          <span>Charcha, built by team Bhadra</span>
          <span>Works with Google Meet in Chrome</span>
        </div>
      </footer>
    </main>
  );
}
