"use client";

import { useState } from "react";
import { Check, Copy, KeyRound, Plug } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div className="flex items-start gap-2">
        <code className="min-w-0 flex-1 rounded-lg border bg-muted px-3 py-2 font-mono text-xs break-all">{value}</code>
        <Button
          size="icon-sm"
          variant="outline"
          aria-label={`Copy ${label.toLowerCase()}`}
          onClick={async () => {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1600);
          }}
        >
          {copied ? <Check /> : <Copy />}
        </Button>
      </div>
    </div>
  );
}

/** Settings card: connect Claude (Desktop, Code, claude.ai) or any MCP
 * client to this person's meetings with a 90-day connector token. */
export function ConnectClaude() {
  const [result, setResult] = useState<{ token: string; url: string; expires_at: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.createConnectorToken());
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Couldn't create a token. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base"><Plug className="h-4 w-4 text-primary" /> Connect Claude</CardTitle>
        <CardDescription>
          Let Claude search your meetings, tasks and decisions, ask your meeting memory, and add tasks. It sees only what you can see here.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {!result ? (
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => void create()} disabled={busy}>
              <KeyRound /> {busy ? "Creating…" : "Create connector token"}
            </Button>
            <p className="text-xs text-muted-foreground">Works for 90 days. Changing your password turns it off.</p>
          </div>
        ) : (
          <>
            <CopyField label="Server URL" value={result.url} />
            <CopyField label="Token" value={result.token} />
            <CopyField
              label="Claude Code"
              value={`claude mcp add --transport http wilco ${result.url} --header "Authorization: Bearer ${result.token}"`}
            />
            <p className="text-xs text-muted-foreground">
              In Claude Desktop or another MCP client, add a remote server with the URL above and the header{" "}
              <code className="font-mono">Authorization: Bearer &lt;token&gt;</code>. The token is shown once and expires{" "}
              {new Date(result.expires_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}.
            </p>
          </>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
      </CardContent>
    </Card>
  );
}
