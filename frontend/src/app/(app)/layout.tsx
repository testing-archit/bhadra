"use client";

import { Suspense, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { ShellProvider } from "@/components/shell/shell-context";
import { Sidebar } from "@/components/shell/sidebar";
import { MobileNavigation } from "@/components/shell/mobile-navigation";
import { Topbar } from "@/components/shell/topbar";
import { CommandPalette } from "@/components/shell/command-palette";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
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
    const onKey = (event: KeyboardEvent) =>
      event.key === "Escape" && setDrawerOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  if (loading || !user) return null;

  return (
    <ShellProvider>
      {/* The ink frame: the sidebar sits on it and every page is a sheet laid
          inside it. The sheet scrolls, not the window. */}
      <div className="flex h-dvh flex-1 overflow-hidden bg-sidebar">
        <a
          href="#main"
          className="sr-only z-50 rounded-lg bg-marigold px-3 py-2 text-sm font-semibold text-marigold-foreground focus:not-sr-only focus:absolute focus:top-3 focus:left-3"
        >
          Skip to content
        </a>
        <aside className="hidden h-dvh w-56 shrink-0 lg:block">
          <Sidebar />
        </aside>

        <Dialog open={drawerOpen} onOpenChange={setDrawerOpen}>
          <DialogContent
            className="top-0! left-0! h-dvh w-72! max-w-[85vw]! translate-x-0! translate-y-0! gap-0 rounded-none! p-0! sm:max-w-72!"
            showCloseButton={false}
          >
            <DialogTitle className="sr-only">Navigation</DialogTitle>
            <Sidebar onNavigate={() => setDrawerOpen(false)} />
          </DialogContent>
        </Dialog>

        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
          {user.email.toLowerCase().endsWith("@demo.wilco.invalid") && (
            <p className="shrink-0 bg-secondary px-4 py-2 text-center text-xs text-secondary-foreground sm:text-sm">
              You&apos;re exploring a demo workspace with sample meetings.{" "}
              <a href="/login" onClick={(event) => { event.preventDefault(); localStorage.removeItem("charchaToken"); window.location.href = "/login"; }} className="font-semibold underline underline-offset-2">
                Create a free account
              </a>{" "}
              to send Wilco to your own calls.
            </p>
          )}
          <Suspense fallback={<div className="h-22 shrink-0" />}><Topbar onOpenMenu={() => setDrawerOpen(true)} /></Suspense>
          <main
            id="main"
            className={
              fullBleed
                ? "flex min-h-0 w-full flex-1 pb-20 lg:pb-0"
                : "min-h-0 flex-1 overflow-y-auto pb-24 lg:pb-0"
            }
          >
            {fullBleed ? (
              children
            ) : (
              <div
                className={`mx-auto w-full max-w-6xl px-4 sm:px-8 ${pathname === "/dashboard" ? "py-4 sm:py-7" : "py-6 sm:py-8"}`}
              >
                {children}
              </div>
            )}
          </main>
          <Suspense fallback={null}>
            <MobileNavigation />
          </Suspense>
        </div>
      </div>
      <CommandPalette />
      <SendNotetakerDialog />
    </ShellProvider>
  );
}
