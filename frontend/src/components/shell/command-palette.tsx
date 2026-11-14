"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import {
  Bot,
  CalendarDays,
  CornerDownLeft,
  FileText,
  ListPlus,
  Loader2,
  Mic,
  NotebookPen,
  Search,
  Settings,
  Sparkles,
  Upload,
  type LucideIcon,
} from "lucide-react";
import { api, type MeetingSummary } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";
import { NAV_GROUPS } from "./nav-config";
import { useShell } from "./shell-context";

interface Command {
  id: string;
  label: string;
  hint?: string;
  icon: LucideIcon;
  group: string;
  run: () => void;
}

export function CommandPalette() {
  const router = useRouter();
  const { user } = useAuth();
  const { commandOpen, setCommandOpen, openNotetaker } = useShell();
  const [query, setQuery] = useState("");
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [searching, setSearching] = useState(false);
  const [cursor, setCursor] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!commandOpen) {
      setQuery("");
      setMeetings([]);
      setCursor(0);
    }
  }, [commandOpen]);

  // Meetings are searched on the server (title, summary and transcript).
  useEffect(() => {
    const q = query.trim();
    if (!commandOpen || q.length < 2) {
      setMeetings([]);
      return;
    }
    const handle = window.setTimeout(() => {
      setSearching(true);
      api
        .listMeetings(q)
        .then((results) => setMeetings(results.slice(0, 6)))
        .catch(() => setMeetings([]))
        .finally(() => setSearching(false));
    }, 220);
    return () => window.clearTimeout(handle);
  }, [query, commandOpen]);

  const commands = useMemo<Command[]>(() => {
    const close = () => setCommandOpen(false);
    const go = (href: string) => () => {
      close();
      router.push(href);
    };
    const q = query.trim();
    const list: Command[] = [];

    if (q) {
      list.push({
        id: "ask",
        label: `Ask company memory: “${q}”`,
        icon: Sparkles,
        group: "Ask",
        run: go(`/memory?q=${encodeURIComponent(q)}`),
      });
    }
    for (const meeting of meetings) {
      list.push({
        id: `meeting-${meeting.id}`,
        label: meeting.title,
        hint: new Date(meeting.date).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
        icon: CalendarDays,
        group: "Meetings",
        run: go(`/meetings/${meeting.id}`),
      });
    }

    const actions: Command[] = [
      { id: "notetaker", label: "Send notetaker to a Meet", icon: Bot, group: "Actions", run: () => { close(); openNotetaker(); } },
      { id: "upload", label: "Upload a recording", icon: Upload, group: "Actions", run: go("/meetings/new?source=upload") },
      { id: "paste", label: "Paste a transcript", icon: FileText, group: "Actions", run: go("/meetings/new?source=paste") },
      { id: "record", label: "Record in person", icon: Mic, group: "Actions", run: go("/record") },
      { id: "prep", label: "Prepare for a meeting", icon: NotebookPen, group: "Actions", run: go("/meetings/prep") },
      { id: "task", label: "Add a task", icon: ListPlus, group: "Actions", run: go("/tasks?new=1") },
    ];
    const pages: Command[] = NAV_GROUPS.flatMap((group) => group.items)
      .filter((item) => !item.adminOnly || user?.is_admin)
      .map((item) => ({ id: `page-${item.href}`, label: item.label, icon: item.icon, group: "Go to", run: go(item.href) }));
    pages.push({ id: "page-settings", label: "Settings", icon: Settings, group: "Go to", run: go("/settings") });

    const needle = q.toLowerCase();
    const matches = (command: Command) => !needle || command.label.toLowerCase().includes(needle);
    return [...list, ...actions.filter(matches), ...pages.filter(matches)];
  }, [query, meetings, router, setCommandOpen, openNotetaker, user?.is_admin]);

  useEffect(() => {
    setCursor(0);
  }, [query]);

  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${cursor}"]`)?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((value) => Math.min(commands.length - 1, value + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((value) => Math.max(0, value - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      commands[cursor]?.run();
    }
  }

  let lastGroup = "";

  return (
    <DialogPrimitive.Root open={commandOpen} onOpenChange={setCommandOpen}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Backdrop className="fixed inset-0 z-50 bg-black/25 supports-backdrop-filter:backdrop-blur-xs data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0" />
        <DialogPrimitive.Popup
          aria-label="Search and commands"
          className="fixed top-[12vh] left-1/2 z-50 flex max-h-[70vh] w-[min(640px,calc(100vw-2rem))] -translate-x-1/2 flex-col overflow-hidden rounded-2xl border bg-popover text-popover-foreground shadow-2xl outline-none data-open:animate-in data-open:fade-in-0 data-open:zoom-in-98 data-closed:animate-out data-closed:fade-out-0"
        >
          <div className="flex items-center gap-3 border-b px-4">
            {searching ? <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" /> : <Search className="size-4 shrink-0 text-muted-foreground" />}
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Search meetings, jump to a page, or ask a question…"
              className="h-13 w-full bg-transparent text-[15px] outline-none placeholder:text-muted-foreground"
              role="combobox"
              aria-expanded="true"
              aria-controls="command-list"
              aria-activedescendant={commands[cursor] ? `command-${commands[cursor].id}` : undefined}
            />
            <kbd className="hidden rounded border px-1.5 text-[10px] text-muted-foreground sm:block">Esc</kbd>
          </div>
          <div ref={listRef} id="command-list" role="listbox" className="min-h-0 flex-1 overflow-y-auto p-2">
            {commands.length === 0 && (
              <p className="px-3 py-8 text-center text-sm text-muted-foreground">Nothing matches “{query}”.</p>
            )}
            {commands.map((command, index) => {
              const header = command.group !== lastGroup ? command.group : null;
              lastGroup = command.group;
              return (
                <div key={command.id}>
                  {header && <p className="px-3 pt-3 pb-1 text-xs font-medium text-muted-foreground first:pt-1">{header}</p>}
                  <button
                    type="button"
                    id={`command-${command.id}`}
                    role="option"
                    aria-selected={index === cursor}
                    data-index={index}
                    onMouseMove={() => setCursor(index)}
                    onClick={command.run}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm outline-none",
                      index === cursor && "bg-accent text-accent-foreground",
                    )}
                  >
                    <command.icon className="size-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate">{command.label}</span>
                    {command.hint && <span className="shrink-0 text-xs text-muted-foreground">{command.hint}</span>}
                    {index === cursor && <CornerDownLeft className="size-3.5 shrink-0 text-muted-foreground" />}
                  </button>
                </div>
              );
            })}
          </div>
          <div className="flex items-center gap-4 border-t px-4 py-2 text-xs text-muted-foreground">
            <span>↑↓ to move</span>
            <span>↵ to open</span>
            <span className="ml-auto">Type 2+ letters to search transcripts</span>
          </div>
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
