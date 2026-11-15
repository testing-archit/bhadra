"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { Menu as MenuIcon, Moon, Search, Sun } from "lucide-react";
import { NotificationBell } from "@/components/notification-bell";
import { useTheme } from "@/lib/theme";
import { useAuth } from "@/lib/auth-context";
import { pageTitleFor } from "./nav-config";
import { useShell } from "./shell-context";

const iconButton = "header-icon-button";
export function Topbar({ onOpenMenu }: { onOpenMenu: () => void }) {
  const pathname = usePathname();
  const params = useSearchParams();
  const calendar = pathname === "/meetings" && params.get("view") === "calendar";
  const { user } = useAuth();
  const { setCommandOpen } = useShell();
  const { resolved, setPreference } = useTheme();
  const home = pathname === "/dashboard";
  const hour = new Date().getHours();
  const greeting =
    hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const name = user?.name || user?.email.split("@")[0] || "Your workspace";
  const initials = name
    .split(/\s+/)
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return (
    <header className="workspace-topbar signal-topbar">
      <button
        type="button"
        className={
          home
            ? "profile-avatar"
            : `${iconButton} lg:hidden`
        }
        onClick={onOpenMenu}
        aria-label="Open navigation"
      >
        {home ? initials : <MenuIcon className="size-5" />}
      </button>
      {home ? (
        <div className="header-greeting">
          <span className="signal-topbar-kicker"><span aria-hidden="true">//</span> Signal room</span>
          <strong>{greeting}, {name}</strong>
        </div>
      ) : (
        <div className="signal-page-heading">
          <span className="signal-topbar-kicker"><span aria-hidden="true">//</span> Workspace</span>
          <p className="text-sm font-semibold">{calendar ? "Calendar" : pageTitleFor(pathname)}</p>
        </div>
      )}
      <div className="ml-auto flex items-center gap-1.5">
        <button
          type="button"
          className={`${iconButton} signal-topbar-search`}
          onClick={() => setCommandOpen(true)}
          aria-label="Search"
        >
          <Search className="size-5" />
          <span aria-hidden="true">Search meetings, decisions, actions</span>
          <kbd aria-hidden="true">⌘K</kbd>
        </button>
        <button
          type="button"
          className={`${iconButton} header-theme-toggle`}
          onClick={() => setPreference(resolved === "dark" ? "light" : "dark")}
          aria-label={
            resolved === "dark" ? "Switch to light mode" : "Switch to dark mode"
          }
        >
          {resolved === "dark" ? (
            <Sun className="size-4" />
          ) : (
            <Moon className="size-4" />
          )}
        </button>
        <NotificationBell />
      </div>
    </header>
  );
}
