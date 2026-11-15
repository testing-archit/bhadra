"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowDown, ArrowUpRight, CalendarDays, CheckCircle2, GitPullRequest, Radio, Sparkles } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { GoogleLoginButton, googleSignInEnabled } from "@/components/google-login-button";
import { EmailPasswordAuthForm } from "@/components/email-password-auth-form";
import { TryDemoButton } from "@/components/try-demo-button";
import { Separator } from "@/components/ui/separator";
import { Waveform, Wordmark } from "@/components/brand";
import "./signal-login.css";

export default function LoginPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [loading, user, router]);

  return (
    <div className="signal-login grid flex-1 p-2 lg:grid-cols-[1.15fr_1fr]">
      <section className="signal-login-story relative flex flex-col justify-between gap-12 overflow-hidden rounded-[1.4rem] px-6 py-8 sm:px-12 lg:py-12">
        <div className="relative z-10 flex items-center justify-between gap-4">
          <Wordmark markClassName="size-9" className="text-white" />
          <span className="signal-login-status inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium"><Radio className="size-3.5" aria-hidden="true" /> Meeting intelligence for builders</span>
        </div>

        <div className="relative z-10 flex flex-col gap-10">
          <h1 className="max-w-2xl text-5xl leading-[0.98] font-semibold tracking-[-0.055em] sm:text-6xl xl:text-7xl">
            Turn meetings into
            <span className="signal-login-headline block">shipped work.</span>
          </h1>
          <p className="signal-login-lede max-w-lg text-base leading-relaxed sm:text-lg">Wilco joins your calls, captures decisions and blockers, and gives every follow-up an owner.</p>

          {/* The product in one exchange: a spoken line becomes an owned task.
              Illustrative content, not a real meeting. */}
          <figure className="signal-login-flow flex max-w-lg flex-col gap-3" aria-label="Example: a spoken blocker becomes an owned task">
            <div className="signal-login-quote rounded-2xl p-4">
              <div className="flex items-center gap-3">
                <Waveform bars={14} className="h-6 shrink-0" />
                <span className="signal-login-muted text-xs">Sprint planning · 14:32</span>
              </div>
              <p className="mt-3 text-[0.95rem] leading-relaxed">
                <span className="font-semibold">Archit:</span> Vedant, login bug Friday tak fix kar dena, release usi pe blocked hai.
              </p>
            </div>
            <ArrowDown className="signal-login-muted mx-auto size-4" aria-hidden="true" />
            <div className="signal-login-result flex items-start gap-3 rounded-2xl p-4">
              <CheckCircle2 className="signal-login-cyan mt-0.5 size-5 shrink-0" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold">Fix the login bug blocking the release</p>
                <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                  <span className="signal-login-chip rounded-full px-2 py-0.5 font-medium">Vedant</span>
                  <span className="signal-login-chip inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium"><CalendarDays className="size-3" /> Fri</span>
                  <span className="signal-login-chip inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium"><GitPullRequest className="size-3" /> Release blocker</span>
                </div>
              </div>
            </div>
          </figure>
        </div>

        <div className="relative z-10 flex flex-wrap items-center gap-4 text-sm">
          <span className="signal-login-muted inline-flex items-center gap-2"><Sparkles className="size-4" aria-hidden="true" /> Built for software teams that move fast</span>
          <span className="signal-login-muted inline-flex items-center gap-1">Meetings <ArrowUpRight className="size-3.5" aria-hidden="true" /> Decisions <ArrowUpRight className="size-3.5" aria-hidden="true" /> Delivery</span>
        </div>
      </section>

      <section className="signal-login-auth flex flex-col items-center justify-center rounded-[1.4rem] px-4 py-12 sm:px-8 lg:ml-2">
        <div className="flex w-full max-w-sm flex-col gap-6">
          <div>
            <h2 className="text-3xl font-semibold tracking-tight">Sign in</h2>
            <p className="mt-1.5 text-sm text-muted-foreground">Your team&apos;s decisions, tasks, and context are waiting.</p>
          </div>
          <TryDemoButton />
          <div className="flex items-center gap-3">
            <Separator className="flex-1" />
            <span className="text-xs text-muted-foreground">or sign in</span>
            <Separator className="flex-1" />
          </div>
          {googleSignInEnabled && (
            <>
              <GoogleLoginButton />
              <div className="flex items-center gap-3">
                <Separator className="flex-1" />
                <span className="text-xs text-muted-foreground">or use email</span>
                <Separator className="flex-1" />
              </div>
            </>
          )}
          <EmailPasswordAuthForm />
          <Link href="/extension" className="text-sm font-semibold underline-offset-4 hover:underline">
            Get the Chrome extension
          </Link>
        </div>
      </section>
    </div>
  );
}
