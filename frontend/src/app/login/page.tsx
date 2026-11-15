"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowDown, CalendarDays, CheckCircle2 } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { GoogleLoginButton, googleSignInEnabled } from "@/components/google-login-button";
import { EmailPasswordAuthForm } from "@/components/email-password-auth-form";
import { TryDemoButton } from "@/components/try-demo-button";
import { Separator } from "@/components/ui/separator";
import { Waveform, Wordmark } from "@/components/brand";

export default function LoginPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [loading, user, router]);

  return (
    <div className="grid flex-1 bg-sidebar p-2 lg:grid-cols-[1.15fr_1fr]">
      <section className="hero-band relative flex flex-col justify-between gap-12 overflow-hidden rounded-[1.4rem] px-6 py-8 sm:px-12 lg:py-12">
        <Wordmark markClassName="size-9" className="text-band-foreground" />

        <div className="flex flex-col gap-10">
          <h1 className="max-w-xl text-5xl leading-[0.98] font-semibold tracking-[-0.04em] sm:text-6xl xl:text-7xl">
            Heard.
            <span className="block text-band-muted">Will comply.</span>
          </h1>

          {/* The product in one exchange: a spoken line becomes an owned task.
              Illustrative content, not a real meeting. */}
          <figure className="flex max-w-md flex-col gap-3" aria-label="Example: a spoken request becomes a task">
            <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
              <div className="flex items-center gap-3">
                <Waveform bars={14} className="h-6 shrink-0" />
                <span className="text-xs text-band-muted">Sprint planning · 14:32</span>
              </div>
              <p className="mt-3 text-[0.95rem] leading-relaxed">
                <span className="font-semibold">Archit:</span> Vedant, login bug Friday tak fix kar dena, release usi pe blocked hai.
              </p>
            </div>
            <ArrowDown className="mx-auto size-4 text-band-muted" aria-hidden="true" />
            <div className="flex items-start gap-3 rounded-2xl bg-card p-4 text-card-foreground">
              <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-tint-mint-foreground" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold">Fix the login bug blocking the release</p>
                <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                  <span className="rounded-full bg-tint-lilac px-2 py-0.5 font-medium text-tint-lilac-foreground">Vedant</span>
                  <span className="inline-flex items-center gap-1 rounded-full bg-tint-peach px-2 py-0.5 font-medium text-tint-peach-foreground"><CalendarDays className="size-3" /> Fri</span>
                  <span className="rounded-full bg-tint-rose px-2 py-0.5 font-medium text-tint-rose-foreground">High</span>
                </div>
              </div>
            </div>
          </figure>
        </div>

        <p className="text-sm text-band-muted">Hears Hinglish and 10+ Indian languages with Gnani Prisma. Speaks them back with Gnani Timbre.</p>
      </section>

      <section className="flex flex-col items-center justify-center rounded-[1.4rem] bg-background px-4 py-12 sm:px-8 lg:ml-2">
        <div className="flex w-full max-w-sm flex-col gap-6">
          <div>
            <h2 className="text-3xl font-semibold tracking-tight">Sign in</h2>
            <p className="mt-1.5 text-sm text-muted-foreground">Pick up where your last meeting left off.</p>
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
