"""Alternative to generate_auth.py: reuse an already-logged-in real Chrome
profile instead of typing credentials into a fresh Playwright browser.

Points Playwright at your actual Chrome user-data directory + profile,
opens meet.google.com (should already be signed in), and saves the
session to auth.json for the headless bot to reuse.

Your regular Chrome must be fully quit first — Chrome locks a profile
directory to one running process at a time.
"""

import asyncio
import sys

from playwright.async_api import async_playwright

CHROME_USER_DATA_DIR = "/Users/archit/Library/Application Support/Google/Chrome"
PROFILE_DIRECTORY = "Profile 15"  # tech-intern@example.com / archit@example.com


async def main() -> None:
    async with async_playwright() as p:
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=CHROME_USER_DATA_DIR,
                channel="chrome",
                headless=False,
                args=[f"--profile-directory={PROFILE_DIRECTORY}"],
            )
        except Exception as exc:
            print(f"Failed to launch against the real profile: {exc}")
            print("Most likely cause: your regular Chrome is still open. Quit it fully (Cmd+Q) and retry.")
            sys.exit(1)

        # Restored session tabs (Gmail, old Google tab, etc.) also attach as
        # context.pages entries in unpredictable order — always open a fresh
        # tab instead of guessing which restored one to reuse.
        page = await context.new_page()
        await page.bring_to_front()
        print(f"New page created. Pages open: {len(context.pages)}")
        await page.goto("https://meet.google.com/", wait_until="domcontentloaded")
        print(f"Navigated. Current URL: {page.url}")
        await page.screenshot(path="debug_after_goto.png")
        print("Saved debug_after_goto.png")

        print("Waiting for the Meet home screen to confirm you're logged in...")
        try:
            await page.wait_for_selector(
                "text=/New meeting|Start an instant meeting|Your meetings/i", timeout=20_000
            )
            print("Confirmed logged in as the expected account.")
        except Exception as exc:
            await page.screenshot(path="debug_timeout.png")
            print(f"Selector wait failed: {exc}")
            print(f"URL at failure: {page.url}")
            print("Saved debug_timeout.png -- inspect this to see what's actually rendered.")
            raise

        await context.storage_state(path="auth.json")
        print("Saved session -> auth.json")

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
