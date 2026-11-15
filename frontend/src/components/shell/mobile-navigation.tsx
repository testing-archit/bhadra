"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AudioLines, House, NotebookPen, Plus, Video } from "lucide-react";
import { useShell } from "./shell-context";
import { cn } from "@/lib/utils";

export function MobileNavigation() {
  const pathname = usePathname();
  const { openNotetaker } = useShell();
  // Voice first on phones: Talk to Wilco and the khata are one tap away;
  // Calendar is a view on Meetings and Settings lives in the menu.
  const items = [
    {
      href: "/dashboard",
      label: "Home",
      icon: House,
      active: pathname === "/dashboard",
    },
    {
      href: "/meetings",
      label: "Meetings",
      icon: Video,
      active: pathname.startsWith("/meetings"),
    },
    {
      href: "/live",
      label: "Talk",
      icon: AudioLines,
      active: pathname === "/live",
    },
    {
      href: "/khata",
      label: "Khata",
      icon: NotebookPen,
      active: pathname === "/khata",
    },
  ];
  return (
    <nav className="mobile-bottom-nav" aria-label="Mobile navigation">
      {items.slice(0, 2).map((item) => (
        <Link
          key={item.label}
          href={item.href}
          className={cn("bottom-nav-item", item.active && "is-active")}
          aria-current={item.active ? "page" : undefined}
        >
          <item.icon aria-hidden="true" />
          <span>{item.label}</span>
        </Link>
      ))}
      <button
        type="button"
        className="mobile-create"
        aria-label="Invite Wilco to a meeting"
        onClick={() => openNotetaker()}
      >
        <Plus aria-hidden="true" />
      </button>
      {items.slice(2).map((item) => (
        <Link
          key={item.label}
          href={item.href}
          className={cn("bottom-nav-item", item.active && "is-active")}
          aria-current={item.active ? "page" : undefined}
        >
          <item.icon aria-hidden="true" />
          <span>{item.label}</span>
        </Link>
      ))}
    </nav>
  );
}
