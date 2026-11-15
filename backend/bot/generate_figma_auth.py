"""One-time Figma browser login. Never asks for passwords in a terminal or portal.

Run locally with a display, sign in to the bot's Figma account, then press
Enter here. Copy the session credential only to the bot's private state volume.
No board is created by this helper; no account/signup/consent flow is automated.
"""
import argparse
import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright


async def main(output):
    if output.exists():
        raise SystemExit('Output already exists. Choose a new private session path.')
    async with async_playwright() as p:
        options = {'headless': False, 'ignore_default_args': ['--enable-automation'],
                   'args': ['--disable-blink-features=AutomationControlled']}
        if os.environ.get('BROWSER_EXECUTABLE_PATH'):
            options['executable_path'] = os.environ['BROWSER_EXECUTABLE_PATH']
        browser = await p.chromium.launch(**options)
        context = await browser.new_context(locale='en-US')
        page = await context.new_page()
        await page.goto('https://www.figma.com/login')
        await asyncio.to_thread(input, 'Sign in to the bot Figma account in the browser. When its file browser is visible, press Enter here. ')
        if not page.url.startswith('https://www.figma.com/files/'):
            raise SystemExit('Sign-in was not confirmed; no session saved.')
        # Exclusive creation, private permissions from the first byte.
        output.parent.mkdir(parents=True, exist_ok=True)
        state = await context.storage_state(indexed_db=True)
        import json
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(state, stream)
        print('Saved private Figma browser session. Keep it out of Git and chat.')
        await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('data/figma-auth.json'))
    asyncio.run(main(parser.parse_args().output))
