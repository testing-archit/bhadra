"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { AuthShell } from "@/components/auth-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Reached from the password-reset email and from an admin's invitation
 * (?invite=1). Setting the password signs you in. */
export default function ResetPasswordPage() {
  const router = useRouter();
  const { login } = useAuth();
  const [token, setToken] = useState<string | null>(null);
  const [invite, setInvite] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setToken(params.get("token"));
    setInvite(params.get("invite") === "1");
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    if (password !== confirm) {
      setError("The two passwords don't match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const me = await login(await api.resetPassword(token, password));
      router.replace(me.department ? "/dashboard" : "/settings");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The password couldn't be saved. Try again.");
    } finally {
      setBusy(false);
    }
  }

  if (token === null) {
    return (
      <AuthShell title="This link is incomplete" description="Open the link straight from your email, or ask for a new one.">
        <Link href="/forgot-password" className="text-center text-sm font-medium text-primary hover:underline">Ask for a new link</Link>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title={invite ? "Welcome to Charcha" : "Choose a new password"}
      description={invite ? "Set a password for your new account. You can also sign in with Google using the same address." : "You'll be signed out everywhere else."}
    >
      <form onSubmit={submit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="new-password">New password</Label>
          <Input id="new-password" type="password" required minLength={8} maxLength={128} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} />
          <p className="text-xs text-muted-foreground">At least 8 characters.</p>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="confirm-password">Confirm password</Label>
          <Input id="confirm-password" type="password" required autoComplete="new-password" value={confirm} onChange={(event) => setConfirm(event.target.value)} />
        </div>
        {error && (
          <p className="text-sm text-destructive">
            {error}{" "}
            {error.includes("expired") && <Link href="/forgot-password" className="font-medium underline">Get a new link</Link>}
          </p>
        )}
        <Button type="submit" disabled={busy}>{busy ? "Saving…" : invite ? "Set password and continue" : "Save and sign in"}</Button>
      </form>
    </AuthShell>
  );
}
