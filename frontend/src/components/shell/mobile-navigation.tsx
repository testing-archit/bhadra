"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AudioLines, House, ListChecks, Plus, Video } from "lucide-react";
import { useShell } from "./shell-context";
import { cn } from "@/lib/utils";

export function MobileNavigation() {
  const pathname = usePathname();
  const { openNotetaker } = useShell();
  // Keep core meeting and follow-up work one tap away on phones.
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
      href: "/tasks",
      label: "Tasks",
      icon: ListChecks,
      active: pathname.startsWith("/tasks"),
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
