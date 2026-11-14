import {
  AudioLines,
  FileAudio,
  BookOpenCheck,
  SpellCheck,
  FolderKanban,
  House,
  ListChecks,
  Scale,
  ShieldCheck,
  Sparkles,
  Video,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Only an exact path match marks this item active (used by Home). */
  exact?: boolean;
  adminOnly?: boolean;
}

export interface NavGroup {
  label: string | null;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: null,
    items: [
      { href: "/dashboard", label: "Home", icon: House, exact: true },
      { href: "/meetings", label: "Meetings", icon: Video },
      { href: "/tasks", label: "Tasks", icon: ListChecks },
      { href: "/memory", label: "Memory", icon: Sparkles },
      { href: "/live", label: "Talk to Wilco", icon: AudioLines },
    ],
  },
  {
    label: "More",
    items: [
      { href: "/recap", label: "Call & voice recap", icon: FileAudio },
      { href: "/decisions", label: "Decisions", icon: Scale },
      { href: "/projects", label: "Projects", icon: FolderKanban },
      { href: "/policy", label: "Policies", icon: BookOpenCheck },
      { href: "/vocabulary", label: "Vocabulary", icon: SpellCheck },
      { href: "/admin", label: "Admin", icon: ShieldCheck, adminOnly: true },
    ],
  },
];

export function isNavActive(item: NavItem, pathname: string) {
  if (item.exact) return pathname === item.href;
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

/** Title shown in the top bar for the current route. */
export function pageTitleFor(pathname: string): string {
  if (pathname === "/meetings/new") return "New meeting";
  if (pathname === "/meetings/prep") return "Meeting prep";
  if (pathname === "/record") return "Record in person";
  if (pathname === "/settings") return "Settings";
  for (const group of NAV_GROUPS) {
    for (const item of group.items) {
      if (isNavActive(item, pathname)) return item.label;
    }
  }
  return "Wilco";
}
