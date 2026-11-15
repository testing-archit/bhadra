"use client";

import { useEffect, useState } from "react";
import { ExternalLink } from "lucide-react";
import { api } from "@/lib/api";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function FigJamBoard({ captureId }: { captureId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let disposed = false;
    const refresh = async () => {
      try {
        const status = await api.figjamStatus(captureId);
        if (!disposed) { setUrl(status.file_url); setError(false); }
      } catch { if (!disposed) setError(true); }
    };
    void refresh();
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 3000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [captureId]);
  return <Card>
    <CardHeader><CardTitle>FigJam</CardTitle></CardHeader>
    <CardContent className="flex flex-col items-start gap-3">
      <p className="text-sm text-muted-foreground">{url ? "Open the meeting’s FigJam file. Access follows its Figma sharing settings." : "Say “Wilco, open FigJam” in the meeting. Its file link will appear here."}</p>
      {url && <a className={buttonVariants()} href={url} target="_blank" rel="noopener noreferrer"><ExternalLink data-icon="inline-start" />Open FigJam</a>}
      {error && <p role="status" className="text-sm text-muted-foreground">Could not check the FigJam link. Retrying…</p>}
    </CardContent>
  </Card>;
}
