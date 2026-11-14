"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { ShellProvider } from "@/components/shell/shell-context";
import { Sidebar } from "@/components/shell/sidebar";
import { Topbar } from "@/components/shell/topbar";
import { CommandPalette } from "@/components/shell/command-palette";
import { SendNotetakerDialog } from "@/components/shell/send-notetaker-dialog";

/** Chat pages own the full height below the top bar; everything else is a
 * centred, scrolling document. */
const FULL_BLEED = ["/policy", "/memory", "/live"];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const fullBleed = FULL_BLEED.includes(pathname);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setDrawerOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  if (loading || !user) return null;

  return (
    <ShellProvider>
      <div className={fullBleed ? "flex h-dvh flex-1 overflow-hidden" : "flex min-h-dvh flex-1"}>
        <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 border-r border-sidebar-border lg:block">
          <Sidebar />
        </aside>

        {drawerOpen && (
          <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
            <button
              type="button"
              className="absolute inset-0 bg-black/30 animate-in fade-in-0"
              onClick={() => setDrawerOpen(false)}
              aria-label="Close navigation"
            />
            <div className="absolute inset-y-0 left-0 w-72 max-w-[85vw] border-r border-sidebar-border shadow-xl animate-in slide-in-from-left">
              <Sidebar onNavigate={() => setDrawerOpen(false)} />
            </div>
          </div>
        )}

        <div className={fullBleed ? "flex min-h-0 min-w-0 flex-1 flex-col" : "flex min-w-0 flex-1 flex-col"}>
          <Topbar onOpenMenu={() => setDrawerOpen(true)} />
          <main className={fullBleed ? "flex min-h-0 w-full flex-1" : "mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-8 sm:py-8"}>
            {children}
          </main>
        </div>
      </div>
      <CommandPalette />
      <SendNotetakerDialog />
    </ShellProvider>
  );
}
