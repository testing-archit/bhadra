"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Loader2, Lock, Search } from "lucide-react";
import { api, ApiError, type AdminMeetingRow } from "@/lib/api";
import { SOURCE_LABELS } from "@/lib/labels";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** Every meeting in the organisation — the only place admins see meetings
 * they weren't part of, so their own workspace stays theirs. A confidential
 * meeting the admin wasn't in shows only that it exists. */
export function AdminMeetings() {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<AdminMeetingRow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setLoading(true);
      api
        .adminMeetings(query.trim())
        .then((result) => {
          setRows(result.meetings);
          setTotal(result.total);
          setError(null);
        })
        .catch((cause) => setError(cause instanceof ApiError ? cause.message : "Meetings couldn't be loaded."))
        .finally(() => setLoading(false));
    }, 250);
    return () => window.clearTimeout(handle);
  }, [query]);

  async function loadMore() {
    if (!rows) return;
    setLoading(true);
    try {
      const result = await api.adminMeetings(query.trim(), rows.length);
      setRows([...rows, ...result.meetings]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">All meetings</h2>
        <p className="text-sm text-muted-foreground">
          Every meeting recorded in Wilco. Opening one here is an admin view; it doesn&apos;t add the meeting to your own workspace.
        </p>
      </div>
      <div className="relative">
        {loading ? (
          <Loader2 className="absolute top-1/2 left-3 size-4 -translate-y-1/2 animate-spin text-muted-foreground" />
        ) : (
          <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
        )}
        <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search by title, summary or who recorded it" className="h-9 pl-9" aria-label="Search all meetings" />
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <div className="overflow-x-auto rounded-xl border bg-card">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-2.5 font-medium">Meeting</th>
              <th className="font-medium">Recorded by</th>
              <th className="font-medium">Source</th>
              <th className="font-medium">Access</th>
              <th className="pr-4 text-right font-medium">Date</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows?.map((row) => (
              <tr key={row.id} className="hover:bg-muted/40">
                <td className="max-w-80 px-4 py-2.5">
                  {row.can_open === false ? (
                    <span
                      className="inline-flex items-center gap-1.5 font-medium text-muted-foreground"
                      title="Only the people in this meeting can open it, admins included"
                    >
                      <Lock className="size-3.5" /> {row.title}
                    </span>
                  ) : (
                    <Link href={`/meetings/${row.id}`} className="inline-flex items-center gap-1.5 font-medium hover:text-primary">
                      {row.confidential && <Lock className="size-3.5 text-warning" aria-label="Confidential" />}
                      {row.title}
                    </Link>
                  )}
                  <span className="ml-2 text-xs text-muted-foreground">{row.duration_minutes} min</span>
                </td>
                <td className="text-muted-foreground">{row.owner ?? "—"}</td>
                <td className="text-muted-foreground">{row.source ? SOURCE_LABELS[row.source] ?? row.source : "—"}</td>
                <td>
                  <span className="text-muted-foreground">{row.with_access} can read</span>
                  {row.pending_access > 0 && (
                    <span className="ml-2 inline-flex items-center gap-1 text-xs text-warning">
                      <Lock className="size-3" /> {row.pending_access} waiting
                    </span>
                  )}
                </td>
                <td className="pr-4 text-right text-muted-foreground tabular-nums">
                  {new Date(row.date).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows?.length === 0 && <p className="p-10 text-center text-sm text-muted-foreground">No meetings match.</p>}
      </div>
      {rows && rows.length < total && (
        <Button variant="outline" onClick={() => void loadMore()} disabled={loading}>
          Show more ({total - rows.length} left)
        </Button>
      )}
    </div>
  );
}
