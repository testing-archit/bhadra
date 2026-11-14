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
      {/* The ink frame: the sidebar sits on it and every page is a sheet laid
          inside it. The sheet scrolls, not the window. */}
      <div className="flex h-dvh flex-1 overflow-hidden bg-sidebar">
        <a href="#main" className="sr-only z-50 rounded-lg bg-marigold px-3 py-2 text-sm font-semibold text-marigold-foreground focus:not-sr-only focus:absolute focus:top-3 focus:left-3">
          Skip to content
        </a>
        <aside className="hidden h-dvh w-60 shrink-0 lg:block">
          <Sidebar />
        </aside>

        {drawerOpen && (
          <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
            <button
              type="button"
              className="absolute inset-0 bg-black/50 animate-in fade-in-0"
              onClick={() => setDrawerOpen(false)}
              aria-label="Close navigation"
            />
            <div className="absolute inset-y-0 left-0 w-72 max-w-[85vw] shadow-2xl animate-in slide-in-from-left">
              <Sidebar onNavigate={() => setDrawerOpen(false)} />
            </div>
          </div>
        )}

        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background lg:my-2 lg:mr-2 lg:rounded-[1.4rem]">
          <Topbar onOpenMenu={() => setDrawerOpen(true)} />
          <main id="main" className={fullBleed ? "flex min-h-0 w-full flex-1" : "min-h-0 flex-1 overflow-y-auto"}>
            {fullBleed ? children : <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-8 sm:py-8">{children}</div>}
          </main>
        </div>
      </div>
      <CommandPalette />
      <SendNotetakerDialog />
    </ShellProvider>
  );
}
