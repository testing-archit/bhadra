"""Joins a Google Meet on a virtual display (Xvfb) so real WebRTC audio
actually renders, and stays in the call until it's told to leave, a banner
confirms it left, or a hard timeout hits. Audio capture itself is handled
outside this script by entrypoint.sh (ffmpeg tapping a PulseAudio null
sink) -- this script's only job is join/stay/leave automation.

Usage:
    python join_and_record.py "https://meet.google.com/xxx-yyyy-zzz" [minutes]
"""

import asyncio
import sys

from playwright.async_api import Page, async_playwright

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
            print(f'Clicked join-flow button: "{text}"', flush=True)
            if text == "Continue without microphone and camera":
                await page.wait_for_timeout(1000)
                continue
            return
    print("No known join button matched — pressing Enter as a fallback", flush=True)
    await page.keyboard.press("Enter")


async def wait_until_admitted(page: Page, timeout_ms: int = 60_000) -> None:
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


async def run(meet_url: str, max_minutes: int) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
        )
        context = await browser.new_context(storage_state="auth.json")
        page = await context.new_page()
        page.on("console", lambda msg: print(f"[page:{msg.type}] {msg.text}", flush=True))

        await page.goto(meet_url, wait_until="domcontentloaded")
        await page.screenshot(path="/output/debug_01_loaded.png")

        await click_if_visible(page, 'button[aria-label*="Turn off microphone"]')
        await click_if_visible(page, 'button[aria-label*="Turn off camera"]')
        await click_if_visible(page, 'button:has-text("Got it")')
        # Meet's "hear you" / "see you" permission modals -- dismiss via
        # Escape (joins muted+cameraless) rather than a selector, since both
        # dialog elements can be present in the DOM at once.
        for _ in range(3):
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
        await page.screenshot(path="/output/debug_02_precheck.png")

        await click_join(page)
        await page.screenshot(path="/output/debug_03_after_join.png")

        await wait_until_admitted(page)
        print("Joined the meeting.", flush=True)
        await page.screenshot(path="/output/debug_04_admitted.png")

        leave_banner = asyncio.create_task(page.wait_for_selector(LEAVE_BANNER_SELECTOR, timeout=0))
        timeout_task = asyncio.create_task(asyncio.sleep(max_minutes * 60))
        done, pending = await asyncio.wait([leave_banner, timeout_task], return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()

        if timeout_task in done:
            hang_up = page.locator('button[aria-label*="Leave call"], button[aria-label*="Leave meeting"]')
            if await hang_up.count():
                await hang_up.first.click()
            else:
                await page.keyboard.press("Control+Alt+q")

        await page.screenshot(path="/output/debug_05_end.png")
        await browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <meet_url> [max_minutes]")
        sys.exit(1)
    url = sys.argv[1]
    minutes = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    asyncio.run(run(url, minutes))
