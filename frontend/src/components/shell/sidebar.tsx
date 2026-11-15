"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Bot,
  CalendarDays,
  MoreHorizontal,
  Search,
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
  Settings,
  Square,
  Sun,
  Upload,
} from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useTheme, type ThemePreference } from "@/lib/theme";
import { cn } from "@/lib/utils";
import {
  Menu,
  MenuContent,
  MenuGroup,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  MenuTrigger,
} from "@/components/ui/menu";
import { BrandMark } from "@/components/brand";
import { NAV_GROUPS, isNavActive } from "./nav-config";
import { isCaptureLive, useShell } from "./shell-context";

const THEME_OPTIONS: {
  value: ThemePreference;
  label: string;
  icon: typeof Sun;
}[] = [
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
  const { openNotetaker, setCommandOpen } = useShell();
  const [taskCount,setTaskCount] = useState<number | null>(null);
  useEffect(() => {
    let active=true;
    const refresh=()=>void api.listTasks().then(rows=>{if(active)setTaskCount(rows.filter(row=>row.status!=="done").length);}).catch(()=>{});
    refresh(); window.addEventListener("wilco:tasks-changed",refresh);
    return ()=>{active=false;window.removeEventListener("wilco:tasks-changed",refresh);};
  },[]);
  const activeLinkRef = useRef<HTMLAnchorElement>(null);
  const navRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const nav = navRef.current;
    const active = activeLinkRef.current;
    if (!nav || !active) return;
    const navBounds = nav.getBoundingClientRect();
    const activeBounds = active.getBoundingClientRect();
    if (activeBounds.bottom > navBounds.bottom) {
      nav.scrollTop += activeBounds.bottom - navBounds.bottom;
    } else if (activeBounds.top < navBounds.top) {
      nav.scrollTop += activeBounds.top - navBounds.top;
    }
  }, [pathname]);

  function go(href: string) {
    onNavigate?.();
    router.push(href);
  }

  return (
    <div className="signal-sidebar flex h-full flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
      <div className="signal-brand flex shrink-0 items-center gap-2.5 px-5">
        <Link
          href="/dashboard"
          onClick={onNavigate}
          className="flex items-center gap-2.5 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
        >
          <BrandMark className="size-11" />
          <span className="signal-brand-copy">
            <span className="font-heading text-lg leading-none font-semibold tracking-tight">
              Wilco
            </span>
            <span className="signal-brand-subtitle">Meeting intelligence</span>
          </span>
        </Link>
      </div>

      <div className="signal-sidebar-actions">
        <button className="signal-new-meeting" onClick={()=>{onNavigate?.();openNotetaker();}}><Plus className="size-4" aria-hidden="true"/>Bring Wilco to a meeting</button>
        <button className="frame-search" onClick={()=>{onNavigate?.();setCommandOpen(true);}}><Search className="size-4" aria-hidden="true"/>Search<kbd>⌘K</kbd></button>
      </div>
      <nav ref={navRef} className="signal-nav" aria-label="Primary">
        <div className="signal-nav-links">
          {NAV_GROUPS.flatMap(group=>group.items).filter(item=>["/dashboard","/meetings","/tasks","/memory","/live"].includes(item.href)).map(item=>{
            const active=isNavActive(item,pathname);
            return <Link key={item.href} href={item.href} ref={active?activeLinkRef:undefined} onClick={onNavigate} aria-current={active?"page":undefined}><item.icon className="size-4" aria-hidden="true"/><span>{item.label}</span>{item.href==="/tasks"&&taskCount!==null&&<span className="nav-count">{taskCount}</span>}</Link>;
          })}
          <Link href="/meetings?view=calendar" onClick={onNavigate}><CalendarDays className="size-4" aria-hidden="true"/>Calendar</Link>
          <Menu><MenuTrigger className="frame-more"><MoreHorizontal className="size-4" aria-hidden="true"/>More</MenuTrigger><MenuContent><MenuGroup>
            {NAV_GROUPS.flatMap(group=>group.items).filter(item=>!["/dashboard","/meetings","/tasks","/memory","/live"].includes(item.href)&&(!item.adminOnly||user?.is_admin)).map(item=><MenuItem key={item.href} onClick={()=>go(item.href)}><item.icon/>{item.label}</MenuItem>)}
            <MenuSeparator/>
            <MenuItem onClick={()=>go("/record")}><Mic/>Record in person</MenuItem>
            <MenuItem onClick={()=>go("/meetings/new?source=upload")}><Upload/>Upload recording</MenuItem>
            <MenuItem onClick={()=>go("/voice-setup")}><Mic/>Voice setup</MenuItem>
          </MenuGroup></MenuContent></Menu>
        </div>
      </nav>

      <LiveNotetakers />

      <div className="signal-sidebar-footer flex shrink-0 flex-col gap-0.5 border-t border-sidebar-border p-3">
        <Link
          href="/extension"
          onClick={onNavigate}
          className="flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-sm text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent/70 hover:text-sidebar-foreground"
        >
          <Puzzle className="size-4 text-sidebar-foreground/70" /> Get the
          extension
        </Link>
        <Link
          href="/settings"
          onClick={onNavigate}
          aria-current={pathname === "/settings" ? "page" : undefined}
          className={cn(
            "flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-sm text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent/70 hover:text-sidebar-foreground",
            pathname === "/settings" &&
              "bg-sidebar-accent font-medium text-sidebar-accent-foreground",
          )}
        >
          <Settings className="size-4 text-sidebar-foreground/70" /> Settings
        </Link>

        {user && (
          <Menu>
            <MenuTrigger className="mt-1 flex w-full items-center gap-2.5 rounded-lg p-1.5 text-left outline-none transition-colors hover:bg-sidebar-accent/70 focus-visible:ring-2 focus-visible:ring-sidebar-ring">
              <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-sidebar-primary text-xs font-bold text-sidebar-primary-foreground">
                {initialsFor(user.name, user.email)}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">
                  {user.name || user.email.split("@")[0]}
                </span>
                <span className="block truncate text-xs text-sidebar-foreground/80">
                  {user.team_name || user.department || user.email}
                </span>
              </span>
              <ChevronsUpDown className="size-4 shrink-0 text-sidebar-foreground/70" />
            </MenuTrigger>
            <MenuContent side="top" align="start" className="w-60">
              <MenuLabel className="truncate">{user.email}</MenuLabel>
              <MenuItem onClick={() => go("/settings")}>
                <Settings /> Account settings
              </MenuItem>
              <MenuSeparator />
              <MenuLabel>Appearance</MenuLabel>
              {THEME_OPTIONS.map((option) => (
                <MenuItem
                  key={option.value}
                  onClick={() => setPreference(option.value)}
                >
                  <option.icon />
                  <span className="flex-1">{option.label}</span>
                  {preference === option.value && (
                    <span
                      className="size-1.5 rounded-full bg-primary"
                      aria-label="Selected"
                    />
                  )}
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
  const live = captures
    .filter((item) => isCaptureLive(item) && item.subscribed !== false)
    .slice(0, 3);
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
              {recording && (
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-destructive/60" />
              )}
              <span
                className={cn(
                  "relative inline-flex size-2 rounded-full",
                  recording ? "bg-destructive" : "bg-warning",
                )}
              />
            </span>
            <div className="min-w-0 flex-1">
              {recording ? (
                <Link href={`/meetings/live/${request.id}`} className="block truncate text-sm font-medium hover:text-sidebar-primary hover:underline">
                  {request.title || request.meeting_code}
                </Link>
              ) : (
                <p className="truncate text-sm font-medium">{request.title || request.meeting_code}</p>
              )}
              <p className="truncate text-xs text-sidebar-foreground/80">
                {request.requested_by
                  ? `${request.requested_by}'s notetaker, `
                  : ""}
                {request.queue_position
                  ? `Queued, ${request.queue_position} ahead`
                  : request.status_label}
              </p>
            </div>
            {request.active && !request.stop_requested && (
              <button
                type="button"
                onClick={() => void stop(request.id)}
                className="grid size-6 shrink-0 place-items-center rounded-md text-sidebar-foreground/80 transition-colors hover:bg-destructive/20 hover:text-sidebar-foreground"
                aria-label={
                  request.status === "requested"
                    ? "Cancel notetaker"
                    : "Stop notetaker"
                }
                title={
                  request.status === "requested" ? "Cancel" : "Stop recording"
                }
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
