"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { AuthShell } from "@/components/auth-shell";
import { Button } from "@/components/ui/button";
import "../signal-public.css";

/** From an email's "Unsubscribe" link. Opening the page changes nothing —
 * mail scanners follow links — the button does. */
export default function UnsubscribePage() {
  const [token, setToken] = useState<string | null>(null);
  const [done, setDone] = useState<{ label: string; email: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setToken(new URLSearchParams(window.location.search).get("token"));
  }, []);

  async function confirm() {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.unsubscribe(token);
      setDone({ label: result.label, email: result.email });
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "That didn't work. Try again, or change it in Settings.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="signal-public-auth"><AuthShell title="You're unsubscribed">
        <div className="flex flex-col items-center gap-3 text-center">
          <CheckCircle2 className="size-8 text-primary" />
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">{done.email}</span> won&apos;t get &ldquo;{done.label}&rdquo; emails any more. You still see them in
            Wilco&apos;s notifications.
          </p>
        </div>
        <Link href="/settings#email" className="text-center text-sm font-medium text-primary hover:underline">Change email preferences</Link>
      </AuthShell></div>
    );
  }

  return (
    <div className="signal-public-auth"><AuthShell title="Unsubscribe from these emails?" description="You'll stop getting this kind of email from Wilco. Security emails, like password resets, always come through.">
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Button onClick={() => void confirm()} disabled={busy || !token}>{busy ? "Unsubscribing…" : "Unsubscribe"}</Button>
      <Link href="/settings#email" className="text-center text-sm text-muted-foreground hover:text-foreground hover:underline">Choose which emails instead</Link>
    </AuthShell></div>
  );
}
