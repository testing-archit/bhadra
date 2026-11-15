"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";

/** One tap into a private workspace filled with sample software-team meetings. */
export function TryDemoButton() {
  const { login } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      await login(await api.startDemo());
      router.push("/dashboard");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The demo couldn't start. Try again.");
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <Button type="button" variant="brand" size="lg" className="w-full" onClick={() => void start()} disabled={busy}>
        {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Sparkles aria-hidden="true" />}
        {busy ? "Setting up your demo" : "Try the demo, no sign-up"}
      </Button>
      <p className="text-center text-xs text-muted-foreground">A private workspace with sample engineering meetings.</p>
      {error && <p role="alert" className="text-center text-sm text-destructive">{error}</p>}
    </div>
  );
}
