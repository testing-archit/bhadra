"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Bot,
  ChevronsUpDown,
  FileAudio,
  FileText,
  ListPlus,
  LogOut,
  Mic,
  Monitor,
  Moon,
  NotebookPen,
  Plus,
  Puzzle,
  Search,
  Settings,
  Square,
  Sun,
  Upload,
} from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useTheme, type ThemePreference } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from "@/components/ui/menu";
import { BrandMark } from "@/components/brand";
import { NAV_GROUPS, isNavActive } from "./nav-config";
import { isCaptureLive, useShell } from "./shell-context";

const THEME_OPTIONS: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "Match system", icon: Monitor },
];

export function initialsFor(name: string | null | undefined, email: string) {
  return (name || email)
    .split(/[\s@.]+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const { preference, setPreference } = useTheme();
  const { setCommandOpen, openNotetaker } = useShell();

  function go(href: string) {
    onNavigate?.();
    router.push(href);
  }

  return (
    <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
      <div className="flex h-14 shrink-0 items-center gap-2.5 px-4">
        <Link href="/dashboard" onClick={onNavigate} className="flex items-center gap-2.5 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring">
          <BrandMark className="size-8" />
          <span className="font-heading text-lg leading-none font-bold tracking-tight">Charcha</span>
        </Link>
      </div>

      <div className="flex flex-col gap-1.5 px-3 pb-3">
        <Menu>
          <MenuTrigger className="flex h-10 w-full items-center justify-center gap-2 rounded-full bg-sidebar-primary text-sm font-semibold text-sidebar-primary-foreground outline-none transition-colors hover:bg-sidebar-primary/90 focus-visible:ring-3 focus-visible:ring-sidebar-ring">
            <Plus className="size-4" /> New charcha
          </MenuTrigger>
          <MenuContent className="w-64">
            <MenuItem onClick={() => { onNavigate?.(); openNotetaker(); }}>
              <Bot /> Send notetaker to a Meet
            </MenuItem>
            <MenuItem onClick={() => go("/meetings/new?source=upload")}>
              <Upload /> Upload a recording
            </MenuItem>
            <MenuItem onClick={() => go("/meetings/new?source=paste")}>
              <FileText /> Paste a transcript
            </MenuItem>
            <MenuItem onClick={() => go("/record")}>
              <Mic /> Record in person
            </MenuItem>
            <MenuItem onClick={() => go("/recap")}>
              <FileAudio /> Recap a call or voice note
            </MenuItem>
            <MenuSeparator />
            <MenuItem onClick={() => go("/meetings/prep")}>
              <NotebookPen /> Prepare for a meeting
            </MenuItem>
            <MenuItem onClick={() => go("/tasks?new=1")}>
              <ListPlus /> Add a task
            </MenuItem>
          </MenuContent>
        </Menu>
        <button
          type="button"
          onClick={() => { onNavigate?.(); setCommandOpen(true); }}
          className="flex h-9 w-full items-center gap-2 rounded-lg border border-sidebar-border bg-sidebar-accent/50 px-3 text-sm text-sidebar-foreground/65 outline-none transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring"
        >
          <Search className="size-4" />
          <span className="flex-1 text-left">Search</span>
          <kbd className="rounded border border-sidebar-border bg-sidebar px-1.5 font-sans text-[10px] font-medium">⌘K</kbd>
        </button>
      </div>

      <nav className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-3 py-2" aria-label="Primary">
        {NAV_GROUPS.map((group) => {
          const items = group.items.filter((item) => !item.adminOnly || user?.is_admin);
          if (!items.length) return null;
          return (
            <div key={group.label ?? "main"} className="flex flex-col gap-0.5">
              {group.label && <p className="px-2.5 pb-1 text-xs font-medium text-sidebar-foreground/55">{group.label}</p>}
              {items.map((item) => {
                const active = isNavActive(item, pathname);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "group relative flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-sm text-sidebar-foreground/80 outline-none transition-colors hover:bg-sidebar-accent/70 hover:text-sidebar-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring",
                      active && "bg-sidebar-accent font-medium text-sidebar-accent-foreground before:absolute before:inset-y-2 before:-left-3 before:w-1 before:rounded-r-full before:bg-sidebar-primary hover:bg-sidebar-accent",
                    )}
                  >
                    <item.icon className={cn("size-4 shrink-0 text-sidebar-foreground/55", active && "text-sidebar-primary")} />
                    {item.label}
                  </Link>
                );
              })}
            </div>
          );
        })}
      </nav>

      <LiveNotetakers />

      <div className="flex flex-col gap-0.5 border-t border-sidebar-border p-3">
        <Link
          href="/extension"
          onClick={onNavigate}
          className="flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-sm text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent/70 hover:text-sidebar-foreground"
        >
          <Puzzle className="size-4 text-sidebar-foreground/55" /> Chrome extension
        </Link>
        <Link
          href="/settings"
          onClick={onNavigate}
          aria-current={pathname === "/settings" ? "page" : undefined}
          className={cn(
            "flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-sm text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent/70 hover:text-sidebar-foreground",
            pathname === "/settings" && "bg-sidebar-accent font-medium text-sidebar-accent-foreground",
          )}
        >
          <Settings className="size-4 text-sidebar-foreground/55" /> Settings
        </Link>

        {user && (
          <Menu>
            <MenuTrigger className="mt-1 flex w-full items-center gap-2.5 rounded-lg p-1.5 text-left outline-none transition-colors hover:bg-sidebar-accent/70 focus-visible:ring-2 focus-visible:ring-sidebar-ring">
              <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-sidebar-primary text-xs font-bold text-sidebar-primary-foreground">
                {initialsFor(user.name, user.email)}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{user.name || user.email.split("@")[0]}</span>
                <span className="block truncate text-xs text-sidebar-foreground/60">{user.team_name || user.department || user.email}</span>
              </span>
              <ChevronsUpDown className="size-4 shrink-0 text-sidebar-foreground/55" />
            </MenuTrigger>
            <MenuContent side="top" align="start" className="w-60">
              <MenuLabel className="truncate">{user.email}</MenuLabel>
              <MenuItem onClick={() => go("/settings")}>
                <Settings /> Account settings
              </MenuItem>
              <MenuSeparator />
              <MenuLabel>Appearance</MenuLabel>
              {THEME_OPTIONS.map((option) => (
                <MenuItem key={option.value} onClick={() => setPreference(option.value)}>
                  <option.icon />
                  <span className="flex-1">{option.label}</span>
                  {preference === option.value && <span className="size-1.5 rounded-full bg-primary" aria-label="Selected" />}
                </MenuItem>
              ))}
              <MenuSeparator />
              <MenuItem onClick={logout}>
                <LogOut /> Log out
              </MenuItem>
            </MenuContent>
          </Menu>
        )}
      </div>
    </div>
  );
}

/** The notetakers currently joining, recording or processing — the one thing
 * on screen that is happening right now, so it lives in the sidebar. */
function LiveNotetakers() {
  const { captures, refreshCaptures } = useShell();
  // Only visits this person still gets notes from (a colleague's notetaker
  // they stopped following drops out of their list).
  const live = captures.filter((item) => isCaptureLive(item) && item.subscribed !== false).slice(0, 3);
  if (!live.length) return null;

  async function stop(id: string) {
    try {
      await api.stopCaptureRequest(id);
    } finally {
      void refreshCaptures();
    }
  }

  return (
    <div className="mx-3 mb-3 flex flex-col gap-2 rounded-xl border border-sidebar-border bg-sidebar-accent/60 p-3">
      {live.map((request) => {
        const recording = request.status === "capturing";
        return (
          <div key={request.id} className="flex items-start gap-2.5">
            <span className="relative mt-1.5 flex size-2 shrink-0">
              {recording && <span className="absolute inline-flex size-full animate-ping rounded-full bg-destructive/60" />}
              <span className={cn("relative inline-flex size-2 rounded-full", recording ? "bg-destructive" : "bg-warning")} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{request.title || request.meeting_code}</p>
              <p className="truncate text-xs text-sidebar-foreground/60">
                {request.requested_by ? `${request.requested_by}'s notetaker, ` : ""}
                {request.queue_position ? `Queued, ${request.queue_position} ahead` : request.status_label}
              </p>
            </div>
            {request.active && !request.stop_requested && (
              <button
                type="button"
                onClick={() => void stop(request.id)}
                className="grid size-6 shrink-0 place-items-center rounded-md text-sidebar-foreground/60 transition-colors hover:bg-destructive/20 hover:text-sidebar-foreground"
                aria-label={request.status === "requested" ? "Cancel notetaker" : "Stop notetaker"}
                title={request.status === "requested" ? "Cancel" : "Stop recording"}
              >
                <Square className="size-3" />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
