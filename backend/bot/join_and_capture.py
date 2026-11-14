"""Feasibility prototype: join a Google Meet headlessly and capture the
live-caption transcript (speaker + text), no audio pipeline involved.

Usage:
    python join_and_capture.py "https://meet.google.com/xxx-yyyy-zzz" [minutes]

Requires auth.json in this directory (see generate_auth.py). Writes the
captured transcript to transcript_<timestamp>.json when the meeting ends,
the bot is told to leave, or the timeout is hit.

This is a standalone script, not wired into the Charcha backend yet — the
point is to prove the join + caption-capture technique actually works
against the current Google Meet UI before investing in the full pipeline.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

from playwright.async_api import Page, async_playwright

EXIT_PHRASES = [
    "notetaker please leave",
    "note taker please leave",
    "charcha please leave",
]

LEAVE_BANNER_SELECTOR = (
    'div[role="heading"]:has-text("You left the meeting"), '
    'div[role="heading"]:has-text("You’ve left the call")'
)

JOIN_BUTTON_TEXTS = [
    "Continue without microphone and camera",
    "Join now",
    "Ask to join",
    "Join meeting",
    "Join call",
    "Join",
]


async def click_if_visible(page: Page, selector: str, timeout_ms: int = 3000) -> bool:
    locator = page.locator(selector)
    try:
        await locator.first.wait_for(state="visible", timeout=timeout_ms)
        await locator.first.click()
        return True
    except Exception:
        return False


async def click_join(page: Page) -> None:
    for text in JOIN_BUTTON_TEXTS:
        if await click_if_visible(page, f'button:has-text("{text}")', timeout_ms=3000):
            print(f'Clicked join-flow button: "{text}"')
            if text == "Continue without microphone and camera":
                await page.wait_for_timeout(1000)
                continue
            return
    print("No known join button matched — pressing Enter as a fallback")
    await page.keyboard.press("Enter")


async def wait_until_admitted(page: Page, timeout_ms: int = 60_000) -> None:
    # asyncio has no built-in "first success of several" helper — race manually.
    tasks = [
        asyncio.create_task(page.wait_for_selector('button[aria-label*="Leave call"]', timeout=timeout_ms)),
        asyncio.create_task(page.wait_for_selector("text=You've been admitted", timeout=timeout_ms)),
        asyncio.create_task(page.wait_for_selector("text=You're the only one here", timeout=timeout_ms)),
    ]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED, timeout=timeout_ms / 1000)
    for t in pending:
        t.cancel()
    if not done or all(t.exception() for t in done):
        raise TimeoutError("Not admitted into the meeting within the timeout")


async def ensure_captions_on(page: Page) -> None:
    await page.wait_for_timeout(4000)

    for attempt in range(10):
        await page.keyboard.down("Shift")
        await page.keyboard.press("c")
        await page.keyboard.up("Shift")
        region = page.locator('[role="region"][aria-label*="Captions"]')
        try:
            await region.wait_for(timeout=800)
            print(f"Captions on (Shift+C, attempt {attempt + 1})")
            return
        except Exception:
            pass
        if await page.locator('button[aria-label*="Turn off captions"]').is_visible():
            print("Captions were already on")
            return
        await page.wait_for_timeout(500)

    if await click_if_visible(page, 'button[aria-label*="Turn on captions"]', timeout_ms=4000):
        print("Captions on (fallback button)")
        return

    raise RuntimeError("Could not enable captions via Shift+C or the CC button")


CAPTION_WATCHER_JS = """
() => {
  const badgeSel = ".NWpY1d, .xoMHSc";
  let lastSpeaker = "Unknown Speaker";

  const getSpeaker = (node) => {
    const badge = node.querySelector(badgeSel);
    const speaker = badge?.textContent?.trim();
    return speaker || lastSpeaker;
  };

  const getText = (node) => {
    const clone = node.cloneNode(true);
    clone.querySelectorAll(badgeSel).forEach((el) => el.remove());
    return clone.textContent?.trim() ?? "";
  };

  const send = (node) => {
    const txt = getText(node);
    const spk = getSpeaker(node);
    if (txt && txt.toLowerCase() !== spk.toLowerCase()) {
      window.onCaption(spk, txt);
      lastSpeaker = spk;
    }
  };

  new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const n of m.addedNodes) {
        if (n instanceof HTMLElement) send(n);
      }
      if (m.type === "characterData" && m.target?.parentElement instanceof HTMLElement) {
        send(m.target.parentElement);
      }
    }
  }).observe(document.body, { childList: true, characterData: true, subtree: true });
}
"""


async def run(meet_url: str, max_minutes: int) -> None:
    segments: dict[str, dict] = {}
    order: list[str] = []
    exit_requested = asyncio.Event()

    async def on_caption(speaker: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if any(p in text.lower() for p in EXIT_PHRASES):
            exit_requested.set()
        existing = segments.get(speaker)
        if existing is None:
            segments[speaker] = {"speaker": speaker, "text": text}
            order.append(speaker)
        elif text.startswith(existing["text"]) or len(text) > len(existing["text"]) + 5:
            existing["text"] = text

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
        )
        context = await browser.new_context(storage_state="auth.json")
        page = await context.new_page()
        page.on("console", lambda msg: print(f"[page:{msg.type}] {msg.text}"))

        await page.goto(meet_url, wait_until="domcontentloaded")
        await page.screenshot(path="debug_01_loaded.png")
        print("Loaded meeting page -> debug_01_loaded.png", flush=True)

        await click_if_visible(page, 'button[aria-label*="Turn off microphone"]')
        await click_if_visible(page, 'button[aria-label*="Turn off camera"]')
        await click_if_visible(page, 'button:has-text("Got it")')
        # Current Meet UI asks two sequential modals -- "hear you" (mic) then
        # "see you" (camera) -- instead of exposing mic/cam toggles directly.
        # Both dialog elements can exist in the DOM at once (only one
        # visible), which makes a locator-based visibility check ambiguous,
        # so just press Escape blindly a few times (joins muted+cameraless).
        for _ in range(3):
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
        await page.screenshot(path="debug_02_precheck.png")
        print("Pre-join checks done -> debug_02_precheck.png", flush=True)

        await click_join(page)
        await page.screenshot(path="debug_03_after_join_click.png")
        print("Clicked join -> debug_03_after_join_click.png", flush=True)

        try:
            await wait_until_admitted(page)
        except Exception as exc:
            await page.screenshot(path="debug_04_admit_failed.png")
            print(f"Admission wait failed: {exc} -> debug_04_admit_failed.png", flush=True)
            raise
        print("Joined the meeting.", flush=True)
        await page.screenshot(path="debug_05_admitted.png")

        try:
            await ensure_captions_on(page)
        except Exception as exc:
            await page.screenshot(path="debug_06_captions_failed.png")
            print(f"Captions failed: {exc} -> debug_06_captions_failed.png", flush=True)
            raise
        await page.screenshot(path="debug_07_captions_on.png")
        print("Captions confirmed on -> debug_07_captions_on.png", flush=True)

        await page.expose_function("onCaption", on_caption)
        await page.evaluate(CAPTION_WATCHER_JS)

        leave_banner = asyncio.create_task(page.wait_for_selector(LEAVE_BANNER_SELECTOR, timeout=0))
        timeout_task = asyncio.create_task(asyncio.sleep(max_minutes * 60))
        exit_task = asyncio.create_task(exit_requested.wait())

        done, pending = await asyncio.wait(
            [leave_banner, timeout_task, exit_task], return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()

        if exit_task in done or timeout_task in done:
            hang_up = page.locator('button[aria-label*="Leave call"], button[aria-label*="Leave meeting"]')
            if await hang_up.count():
                await hang_up.first.click()
            else:
                await page.keyboard.press("Control+Alt+q")

        out_path = Path(f"transcript_{int(time.time())}.json")
        transcript = [segments[spk] for spk in order]
        out_path.write_text(json.dumps(transcript, indent=2))
        print(f"Saved {len(transcript)} speaker segments -> {out_path}")

        await browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <meet_url> [max_minutes]")
        sys.exit(1)
    url = sys.argv[1]
    minutes = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    asyncio.run(run(url, minutes))
