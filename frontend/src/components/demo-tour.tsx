"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AudioLines, Cpu, Languages, NotebookPen, X } from "lucide-react";
import { useAuth } from "@/lib/auth-context";

const STEPS = [
  { href: "/live", icon: AudioLines, title: "Talk to Wilco", body: "Ask out loud, in Hindi, English or Tamil: “Gupta ji ka kitna udhaar baaki hai?”" },
  { href: "/khata", icon: NotebookPen, title: "Keep a khata by voice", body: "Say “Meena didi ne 300 jama kiye”, then send a reminder in Tamil or Marathi." },
  { href: "/meetings", icon: Languages, title: "Hear notes in your language", body: "Open the Sharma Kirana call, pick தமிழ் or मराठी, tap Listen, then send it on WhatsApp." },
  { href: "/gnani", icon: Cpu, title: "See the Gnani models", body: "Speak to Prisma and hear Timbre in 11 Indian languages, live." },
];
const KEY = "wilco.demo-tour-dismissed";

/** A 60-second path through the demo for guests; never shown to real accounts. */
export function DemoTour() {
  const { user } = useAuth();
  const [hidden, setHidden] = useState(true);
  const demo = Boolean(user?.email.toLowerCase().endsWith("@demo.wilco.invalid"));

  useEffect(() => {
    try { setHidden(window.localStorage.getItem(KEY) === "1"); } catch { setHidden(false); }
  }, []);

  if (!demo || hidden) return null;
  return (
    <section aria-label="Start here" className="relative rounded-2xl border bg-card p-4 sm:p-5">
      <button
        type="button"
        aria-label="Hide this guide"
        className="absolute top-3 right-3 rounded-md p-1 text-muted-foreground hover:bg-muted"
        onClick={() => { setHidden(true); try { window.localStorage.setItem(KEY, "1"); } catch {} }}
      >
        <X className="size-4" aria-hidden="true" />
      </button>
      <h2 className="text-base font-semibold">Start here: Wilco in a minute</h2>
      <p className="mt-0.5 text-sm text-muted-foreground">Everything here is sample data. Every voice is a Gnani model.</p>
      <ol className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {STEPS.map(({ href, icon: Icon, title, body }, index) => (
          <li key={href}>
            <Link href={href} className="flex h-full flex-col gap-1.5 rounded-xl bg-secondary p-3 text-secondary-foreground transition-colors hover:bg-secondary/80">
              <span className="flex items-center gap-2 text-sm font-semibold">
                <span className="grid size-5 place-items-center rounded-full bg-primary text-[11px] text-primary-foreground">{index + 1}</span>
                <Icon className="size-4" aria-hidden="true" />{title}
              </span>
              <span className="text-xs leading-snug">{body}</span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}
