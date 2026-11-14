"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { MailCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { AuthShell } from "@/components/auth-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setEmail(new URLSearchParams(window.location.search).get("email") ?? "");
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.forgotPassword(email);
      setSent(true);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Something went wrong. Try again in a minute.");
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <AuthShell title="Check your email">
        <div className="flex flex-col items-center gap-3 text-center">
          <MailCheck className="size-8 text-primary" />
          <p className="text-sm text-muted-foreground">
            If <span className="font-medium text-foreground">{email}</span> has a Charcha account, a link to choose a new password is on its way.
            It works once and expires in an hour.
          </p>
          <p className="text-xs text-muted-foreground">Nothing after a few minutes? Check spam, or make sure you used your work address.</p>
        </div>
        <Link href="/login" className="text-center text-sm font-medium text-primary hover:underline">Back to sign in</Link>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Reset your password" description="Enter your work email and we'll send you a link to choose a new password.">
      <form onSubmit={submit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="forgot-email">Email</Label>
          <Input id="forgot-email" type="email" required autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} />
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <Button type="submit" disabled={busy}>{busy ? "Sending…" : "Send reset link"}</Button>
      </form>
      <p className="text-center text-xs text-muted-foreground">
        Signed up with Google? Use <Link href="/login" className="font-medium text-foreground hover:underline">Continue with Google</Link> instead.
      </p>
    </AuthShell>
  );
}
