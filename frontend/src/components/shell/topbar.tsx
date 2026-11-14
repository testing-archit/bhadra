"use client";

import { usePathname } from "next/navigation";
import { Menu as MenuIcon, Moon, Search, Sun } from "lucide-react";
import { NotificationBell } from "@/components/notification-bell";
import { useTheme } from "@/lib/theme";
import { pageTitleFor } from "./nav-config";
import { useShell } from "./shell-context";

const iconButton =
  "grid size-10 place-items-center rounded-lg text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring";

export function Topbar({ onOpenMenu }: { onOpenMenu: () => void }) {
  const pathname = usePathname();
  const { setCommandOpen } = useShell();
  const { resolved, setPreference } = useTheme();

  return (
    <header className="z-30 flex h-16 shrink-0 items-center gap-2 bg-background px-4 sm:px-8">
      <button
        type="button"
        className={`${iconButton} -ml-1 lg:hidden`}
        onClick={onOpenMenu}
        aria-label="Open navigation"
      >
        <MenuIcon className="size-5" />
      </button>
      <p
        className="truncate text-xs font-medium text-muted-foreground"
        aria-hidden="true"
      >
        {pageTitleFor(pathname)}
      </p>
      <div className="ml-auto flex items-center gap-1">
        <button
          type="button"
          className={`${iconButton} lg:hidden`}
          onClick={() => setCommandOpen(true)}
          aria-label="Search"
        >
          <Search className="size-4" />
        </button>
        <button
          type="button"
          className={iconButton}
          onClick={() => setPreference(resolved === "dark" ? "light" : "dark")}
          aria-label={
            resolved === "dark" ? "Switch to light mode" : "Switch to dark mode"
          }
          title={resolved === "dark" ? "Light mode" : "Dark mode"}
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
