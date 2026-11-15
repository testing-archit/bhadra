"use client";

import { useCallback, useEffect, useState } from "react";
import { Copy, ExternalLink } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Status = Awaited<ReturnType<typeof api.figjamStatus>>;
export function FigJamConnection({captureId}: {captureId: string}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [fileUrl, setFileUrl] = useState("");
  const [pair, setPair] = useState<{code: string; expiresAt: number} | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const next = await api.figjamStatus(captureId);
      setStatus(next);
      if (next.connected) setPair(null);
    } catch { setError("Could not check FigJam. Refresh this page to try again."); }
  }, [captureId]);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh();
      setPair(current => current && current.expiresAt <= Date.now() ? null : current);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [refresh]);
  return <Card>
    <CardHeader>
      <CardTitle>Your shared FigJam board</CardTitle>
      <CardDescription>Wilco draws editable shapes in your FigJam file. Use Figma’s Share button to invite anyone.</CardDescription>
    </CardHeader>
    <CardContent className="flex flex-col gap-4">
      <p role="status" aria-live="polite" className="text-sm">{!status ? "Checking connection…" : status.connected ? "Connected. Keep the Wilco plugin open in FigJam." : status.configured ? "Waiting for the Wilco plugin in FigJam." : "Connect a FigJam file to draw there by voice."}</p>
      {status?.file_url && <Button render={<a href={status.file_url} target="_blank" rel="noopener noreferrer" />}>
        <ExternalLink data-icon="inline-start" />Open FigJam
      </Button>}
      {status?.can_connect && !status.connected && <form className="flex flex-col gap-3" onSubmit={async event => {
        event.preventDefault(); setBusy(true); setError(null); setCopied(false);
        try {
          const result = await api.pairFigjam(captureId, fileUrl);
          setPair({code: result.code, expiresAt: Date.now()+result.expires_in_seconds*1000});
          await refresh();
        } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not connect FigJam. Try again."); }
        finally { setBusy(false); }
      }}>
        <Label htmlFor="figjam-file-url">FigJam file link</Label>
        <Input id="figjam-file-url" type="url" value={fileUrl} onChange={event => setFileUrl(event.target.value)} required placeholder="https://www.figma.com/board/…" aria-describedby="figjam-help" />
        <Button type="submit" disabled={busy}>{busy ? "Getting code…" : "Get pairing code"}</Button>
      </form>}
      {pair && <div className="flex flex-col gap-2">
        <Label htmlFor="figjam-code">One-time pairing code · expires in five minutes</Label>
        <Input id="figjam-code" readOnly value={pair.code} spellCheck={false} />
        <Button variant="outline" onClick={async () => {
          try { await navigator.clipboard.writeText(pair.code); setCopied(true); }
          catch { setError("Copy the code from the field above."); }
        }}><Copy data-icon="inline-start" />{copied ? "Copied" : "Copy code"}</Button>
      </div>}
      <details id="figjam-help" className="text-sm">
        <summary className="cursor-pointer font-medium">Set up the FigJam plugin</summary>
        <ol className="mt-3 flex list-decimal flex-col gap-2 pl-5 text-muted-foreground">
          <li>In Figma desktop, choose Plugins → Development → New plugin. Name it Wilco meeting commands, choose FigJam, and save the generated folder.</li>
          <li><a className="font-medium text-primary underline" href="/downloads/wilco-figjam.zip" download>Download the Wilco plugin files</a> and unzip them. Follow README.txt to copy your Figma-issued plugin ID using the included configure.py helper.</li>
          <li>Choose Plugins → Development → Import plugin from manifest, then select the updated Wilco manifest.json.</li>
          <li>Run Wilco meeting commands. Paste this file’s link and your one-time code. Keep the plugin open.</li>
          <li>Say “Wilco, draw a signup and payment flow.” Share the FigJam tab in Meet when presenting.</li>
        </ol>
        <p className="mt-3 text-muted-foreground">Wilco edits the shapes it creates. Other FigJam content stays yours. File access follows Figma’s sharing settings.</p>
      </details>
      {status?.connected && status.can_connect && <Button variant="outline" disabled={busy} onClick={async () => {
        setBusy(true); setError(null);
        try { await api.disconnectFigjam(captureId); await refresh(); }
        catch { setError("Could not disconnect. Try again."); }
        finally { setBusy(false); }
      }}>Disconnect FigJam</Button>}
      {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
    </CardContent>
  </Card>;
}
