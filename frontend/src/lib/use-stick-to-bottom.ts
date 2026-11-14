"use client";

import { useCallback, useRef } from "react";

/** Keeps a chat panel scrolled to its newest message while the reader is at
 * the bottom — including content that grows after it renders (answers,
 * sources, a reloaded conversation) — and stops following once they scroll
 * up to read. Scrolls only the panel itself, never the page.
 *
 * Returns a callback ref for the scrolling panel (so it re-attaches if React
 * swaps the element) and `pin()` to jump back to the bottom, e.g. on send. */
export function useStickToBottom() {
  const atBottom = useRef(true);
  const panel = useRef<HTMLElement | null>(null);
  const cleanup = useRef<(() => void) | null>(null);

  const follow = useCallback(() => {
    const el = panel.current;
    if (el && atBottom.current) el.scrollTop = el.scrollHeight;
  }, []);

  const panelRef = useCallback(
    (el: HTMLElement | null) => {
      cleanup.current?.();
      cleanup.current = null;
      panel.current = el;
      if (!el) return;
      const onScroll = () => {
        atBottom.current = el.scrollHeight - el.clientHeight - el.scrollTop < 48;
      };
      // Any change inside the panel (new message, sources expanding, a
      // conversation reloading) and any size change of what it holds.
      const resize = new ResizeObserver(follow);
      const watchChildren = () => {
        resize.disconnect();
        for (const child of Array.from(el.children)) resize.observe(child);
      };
      const mutations = new MutationObserver(() => {
        watchChildren();
        follow();
      });
      el.addEventListener("scroll", onScroll, { passive: true });
      mutations.observe(el, { childList: true, subtree: true, characterData: true });
      watchChildren();
      follow();
      cleanup.current = () => {
        el.removeEventListener("scroll", onScroll);
        mutations.disconnect();
        resize.disconnect();
      };
    },
    [follow],
  );

  const pin = useCallback(() => {
    atBottom.current = true;
    follow();
  }, [follow]);

  return { panelRef, pin };
}
