"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { GoogleLoginButton, googleSignInEnabled } from "@/components/google-login-button";
import { EmailPasswordAuthForm } from "@/components/email-password-auth-form";
import { Separator } from "@/components/ui/separator";
import { VoiceDisc, Wordmark } from "@/components/brand";

export default function LoginPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [loading, user, router]);

  return (
    <div className="grid flex-1 lg:grid-cols-[1.1fr_1fr]">
      <section className="relative flex flex-col justify-between gap-10 overflow-hidden bg-sidebar px-6 py-8 text-sidebar-foreground sm:px-12 lg:py-12">
        <Wordmark markClassName="size-9" />

        <div className="flex flex-col items-start gap-8 lg:gap-10">
          <VoiceDisc className="hidden size-40 lg:block xl:size-52" />
          <div>
            <p lang="hi" className="font-heading text-6xl leading-[0.95] font-bold text-sidebar-primary sm:text-7xl xl:text-8xl">
              चर्चा
            </p>
            <h1 className="mt-5 max-w-md text-2xl leading-snug font-semibold sm:text-3xl">
              Speak in any language. Charcha remembers what was decided.
            </h1>
            <p className="mt-3 max-w-md text-base text-sidebar-foreground/75">
              Hindi, English or both in one sentence. Your meetings become clear tasks, owners and decisions your team can search later.
            </p>
          </div>
        </div>

        <p className="hidden text-sm text-sidebar-foreground/60 lg:block">Built by team Bhadra for India Runs on Voice.</p>
      </section>

      <section className="flex flex-col items-center justify-center px-4 py-10 sm:px-8">
        <div className="flex w-full max-w-sm flex-col gap-6">
          <div>
            <h2 className="text-2xl font-bold">Sign in</h2>
            <p className="mt-1 text-sm text-muted-foreground">Pick up where your last charcha left off.</p>
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
          <Link href="/extension" className="text-sm font-semibold text-primary underline-offset-4 hover:underline">
            Get the Chrome extension
          </Link>
        </div>
      </section>
    </div>
  );
}
