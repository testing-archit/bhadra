"""One-time interactive login that saves a reusable Google session.

Run this locally (needs a real display — it opens a visible Chromium
window) and sign in as the NOTETAKER account (notetaker@example.com),
including any 2FA prompt; the script waits for the Meet home screen to
appear, then saves cookies + storage to auth.json. The bot
(meeting_session.py) loads that file so it never sees a password, and
rewrites it after every meeting to keep Google's rotating cookies fresh.

auth.json is a live session credential — never commit it, never send it
anywhere other than the VM it runs on.
"""

import asyncio

from playwright.async_api import async_playwright

LOGIN_URL = (
    "https://accounts.google.com/ServiceLogin"
    "?service=wise&passive=true&Email=charchanotetaker%40gmail.com"
    "&continue=https%3A%2F%2Fmeet.google.com%2F"
)


async def main() -> None:
    async with async_playwright() as p:
        # Without these Google's sign-in page often refuses the automated
        # browser ("This browser or app may not be secure").
        browser = await p.chromium.launch(
            headless=False,
            ignore_default_args=["--enable-automation"],
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context()
        page = await context.new_page()
        await page.bring_to_front()

        print("Opening Google sign-in — log in manually in the window that just opened.", flush=True)
        await page.goto(LOGIN_URL)
        await page.screenshot(path="debug_login_start.png")
        print("Saved debug_login_start.png", flush=True)

        print("Waiting for the Meet home screen (no timeout — take your time with 2FA)...", flush=True)

        # Poll instead of a single indefinite wait so progress can be
        # checked via screenshots rather than relying on someone watching
        # the actual screen the whole time.
        for i in range(120):  # up to 20 minutes
            if "meet.google.com" in page.url and "accounts.google.com" not in page.url:
                break
            if i % 3 == 0:
                await page.screenshot(path="debug_login_progress.png")
                print(f"[{i * 10}s] current URL: {page.url}", flush=True)
            await page.wait_for_timeout(10_000)
        else:
            raise TimeoutError("Login not completed within 20 minutes")

        await context.storage_state(path="auth.json")
        print("Saved logged-in session -> auth.json", flush=True)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
