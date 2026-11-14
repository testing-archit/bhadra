"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type CaptureRequestItem } from "@/lib/api";

const ACTIVE_POLL_MS = 5_000;
const IDLE_POLL_MS = 60_000;

/** A notetaker that is still on its way in, in the call, or being processed. */
export function isCaptureLive(request: CaptureRequestItem) {
  return request.active || request.status === "stopped";
}

interface ShellContextValue {
  commandOpen: boolean;
  setCommandOpen: (open: boolean) => void;
  notetakerOpen: boolean;
  /** Opens the "Send notetaker" dialog, optionally pre-filled with a meeting link. */
  openNotetaker: (meetingUrl?: string) => void;
  closeNotetaker: () => void;
  notetakerPrefill: string;
  captures: CaptureRequestItem[];
  refreshCaptures: () => Promise<void>;
}

const ShellContext = createContext<ShellContextValue | null>(null);

export function ShellProvider({ children }: { children: ReactNode }) {
  const [commandOpen, setCommandOpen] = useState(false);
  const [notetakerOpen, setNotetakerOpen] = useState(false);
  const [notetakerPrefill, setNotetakerPrefill] = useState("");
  const [captures, setCaptures] = useState<CaptureRequestItem[]>([]);

  const refreshCaptures = useCallback(async () => {
    try {
      setCaptures(await api.listCaptureRequests());
    } catch {
      // The notetaker may not be configured on this server; the UI just shows nothing live.
    }
  }, []);

  const anyLive = captures.some(isCaptureLive);

  // Poll fast only while a notetaker is actually doing something, so an idle
  // tab costs one request a minute.
  useEffect(() => {
    void refreshCaptures();
    const handle = window.setInterval(() => {
      if (document.visibilityState === "visible") void refreshCaptures();
    }, anyLive ? ACTIVE_POLL_MS : IDLE_POLL_MS);
    return () => window.clearInterval(handle);
  }, [anyLive, refreshCaptures]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen((open) => !open);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const value = useMemo<ShellContextValue>(
    () => ({
      commandOpen,
      setCommandOpen,
      notetakerOpen,
      openNotetaker: (meetingUrl = "") => {
        setNotetakerPrefill(meetingUrl);
        setNotetakerOpen(true);
      },
      closeNotetaker: () => setNotetakerOpen(false),
      notetakerPrefill,
      captures,
      refreshCaptures,
    }),
    [commandOpen, notetakerOpen, notetakerPrefill, captures, refreshCaptures],
  );

  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}

export function useShell() {
  const ctx = useContext(ShellContext);
  if (!ctx) throw new Error("useShell must be used within ShellProvider");
  return ctx;
}
