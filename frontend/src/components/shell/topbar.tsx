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
  const calendar =
    pathname === "/meetings" && params.get("view") === "calendar";
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
        className={`${iconButton} md:hidden`}
        onClick={onOpenMenu}
        aria-label="Open navigation"
      >
        <MenuIcon className="size-5" />
      </button>
      <p className="tray-breadcrumb">
        {calendar ? "Calendar" : pageTitleFor(pathname)}
      </p>
      <div className="ml-auto flex items-center gap-1.5">
        <button
          type="button"
          className={`${iconButton} signal-topbar-search`}
          onClick={() => setCommandOpen(true)}
          aria-label="Search"
        >
          <Search className="size-5" />
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
        <button
          type="button"
          className="profile-avatar md:hidden"
          onClick={onOpenMenu}
          aria-label="Open profile and navigation"
        >
          {initials}
        </button>
      </div>
    </header>
  );
}
