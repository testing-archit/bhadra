"""Meeting-owned native FigJam browser. Never accepts code or arbitrary URLs.

Uses documented quick actions and accessibility controls, not private Figma
endpoints. UI drift fails closed. A browser receipt is required before success.
"""
import asyncio
import base64
import datetime as dt
import logging
import re
import time

import config
from command_runtime import stage

log = logging.getLogger(__name__)
FILE = re.compile(r'https://(?:www\.)?figma\.com/board/([A-Za-z0-9]{6,100})(?:[/?#].*)?\Z')


def canonical(value):
    match = FILE.fullmatch(value or '')
    return 'https://www.figma.com/board/' + match[1] if match else None


class EditorUnavailable(Exception):
    pass


class FigJamBrowser:
    def __init__(self, playwright):
        self.playwright = playwright
        self.browser = self.context = self.page = None
        self.file_url = None
        self.snapshot = {'nodes': [], 'edges': []}
        self.positions = {}
        self.lock = asyncio.Lock()

    async def close(self):
        if self.browser:
            await self.browser.close()
        self.browser = self.context = self.page = None

    async def editor(self, destination, check):
        if destination and not canonical(destination):
            raise EditorUnavailable()
        if self.file_url and destination and self.file_url != canonical(destination):
            raise EditorUnavailable()
        await check()
        if not config.FIGMA_AUTH_STATE_PATH.is_file():
            return 'auth_required'
        if not self.page:
            # A distinct muted process cannot feed Figma audio into the call.
            self.browser = await self.playwright.chromium.launch(headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage', '--mute-audio'])
            self.context = await self.browser.new_context(storage_state=str(config.FIGMA_AUTH_STATE_PATH),
                viewport={'width': 1280, 'height': 800}, locale='en-US')
            self.page = await self.context.new_page()
            await self.page.goto(destination or 'https://figjam.new', wait_until='domcontentloaded', timeout=18000)
        for _ in range(30):
            await check()
            native = canonical(self.page.url)
            canvas = self.page.locator('canvas').first
            share = self.page.get_by_role('button', name=re.compile(r'^Share\b'))
            if native:
                if await self.page.get_by_role('button', name=re.compile(r'^(Log in|Sign in|Sign up)$', re.I)).count():
                    return 'auth_required'
                if await canvas.is_visible() and await share.first.is_visible():
                    self.file_url = native
                    return None
            if re.search(r'/(?:login|signup)(?:[/?#]|$)|accounts\.google\.com', self.page.url):
                return 'auth_required'
            await asyncio.sleep(.2)
        return 'editor_unavailable'

    async def quick_action(self, name):
        await self.page.keyboard.press('Escape')
        await self.page.keyboard.press('ControlOrMeta+/')
        await self.page.wait_for_function('''() => {
            const e=document.activeElement;
            return e && (e.tagName==='INPUT' || e.tagName==='TEXTAREA' || e.isContentEditable);
        }''', timeout=2000)
        # Never select all on the canvas. Type only into the focused search.
        await self.page.keyboard.insert_text(name)
        action = self.page.get_by_role('option', name=re.compile('^' + re.escape(name) + '$', re.I))
        if not await action.count():
            action = self.page.get_by_text(name, exact=True)
        await action.click(timeout=2000)

    async def accessibility(self):
        await self.quick_action('Accessibility settings')
        control = self.page.get_by_role('checkbox', name=re.compile(r'Adapt content', re.I))
        if not await control.count():
            control = self.page.get_by_role('switch', name=re.compile(r'Adapt content', re.I))
        await control.check(timeout=2000)
        include = self.page.get_by_role('checkbox', name=re.compile(r'Include everything', re.I))
        if await include.count():
            await include.check(timeout=2000)
        await self.page.keyboard.press('Escape')

    async def add_note(self, node, ordinal, check):
        await check()
        await self.page.keyboard.press('Escape')
        await self.page.keyboard.press('Shift+0')
        await self.quick_action('Create new sticky note')
        # Creating an object selects it. Enter starts its native text editor.
        await self.page.keyboard.press('Enter')
        await self.page.wait_for_function('''() => {
            const e=document.activeElement;
            return e && (e.tagName==='TEXTAREA' || e.isContentEditable);
        }''', timeout=2000)
        text = (str(node.get('title') or '') + ('\n' + str(node['text']) if node.get('text') else ''))[:500]
        if not text.strip():
            raise EditorUnavailable()
        await check()
        await self.page.keyboard.insert_text(text)
        await self.page.keyboard.press('Escape')
        # Accessibility must confirm the native object, not just a typed value.
        item = self.page.get_by_role('group', name=re.compile(re.escape(node['title'])))
        await item.wait_for(state='attached', timeout=2500)
        if await item.count() != 1:
            raise EditorUnavailable()
        # Quick create places at viewport center. Nudge only this selected node.
        await self.page.keyboard.press('Shift+0')  # documented zoom to 100%
        x, y = 240 + (ordinal % 3)*350, 240 + (ordinal // 3)*270
        for key, distance in [('ArrowLeft' if x < 640 else 'ArrowRight', abs(x-640)),
                              ('ArrowUp' if y < 400 else 'ArrowDown', abs(y-400))]:
            for _ in range(distance // 10):
                await check()
                await self.page.keyboard.press('Shift+' + key)
        self.positions[node['id']] = (x, y)
        await self.page.keyboard.press('Escape')

    async def draw(self, payload, check):
        snapshot, baseline = payload.get('snapshot') or {}, payload.get('baseline') or {}
        nodes, edges = snapshot.get('nodes') or [], snapshot.get('edges') or []
        if baseline != self.snapshot or not 1 <= len(nodes) <= 6:
            return 'unsupported_edit'
        old_nodes = {n['id']: n for n in baseline.get('nodes') or []}
        old_edges = baseline.get('edges') or []
        # Initial release appends native nodes/lines. Do not silently overwrite
        # collaborator changes or infer node identity from screen coordinates.
        if any(n not in nodes for n in old_nodes.values()) or any(e not in edges for e in old_edges):
            return 'unsupported_edit'
        titles = [str(n.get('title') or '') for n in nodes]
        if len(set(titles)) != len(titles) or any(not t for t in titles):
            return 'unsupported_edit'
        await self.accessibility()
        for index, node in enumerate(nodes):
            if node['id'] not in old_nodes:
                await self.add_note(node, index, check)
        # Native straight connectors follow FigJam's L shortcut. Refuse an
        # unverified connector rather than announcing a complete diagram.
        for edge in edges:
            if edge in old_edges:
                continue
            if edge['source'] not in self.positions or edge['target'] not in self.positions:
                return 'uncertain'
            await check()
            connectors = self.page.get_by_role('group', name=re.compile(r'connector', re.I))
            before = await connectors.count()
            a, b = self.positions[edge['source']], self.positions[edge['target']]
            await self.page.keyboard.press('Escape')
            await self.page.keyboard.press('l')
            await self.page.mouse.move(*a)
            await self.page.mouse.down()
            try:
                await self.page.mouse.move(*b, steps=5)
            finally:
                await self.page.mouse.up()
            await self.page.keyboard.press('Escape')
            await self.page.wait_for_function('''(before) => [...document.querySelectorAll('[role="group"]')]
                .filter(e => /connector/i.test(e.getAttribute('aria-label') || '')).length > before''', arg=before, timeout=2000)
        # Text is read back from the native accessible canvas before receipt.
        for title in titles:
            await self.page.get_by_role('group', name=re.compile(re.escape(title))).wait_for(state='attached', timeout=2000)
        self.snapshot = {'nodes': nodes, 'edges': edges}
        return 'applied'

    async def frame(self):
        """Only the verified board's canvas; never a desktop/login/account page."""
        if not self.page or not self.file_url or canonical(self.page.url) != self.file_url:
            return None
        canvas = self.page.locator('canvas').first
        if not await canvas.is_visible():
            return None
        data = await canvas.screenshot(type='jpeg', quality=65, timeout=1500)
        return {'frame_image': 'data:image/jpeg;base64,' + base64.b64encode(data).decode(), 'version': time.monotonic_ns()}

    async def execute(self, action, check):
        async with self.lock:
            if action['operation'] not in {'open_figjam', 'draw_figjam'}:
                return {'outcome': 'uncertain'}
            try:
                error = await self.editor(action['payload'].get('file_url'), check)
                if error:
                    return {'outcome': error, 'file_url': self.file_url}
                outcome = 'applied' if action['operation'] == 'open_figjam' else await self.draw(action['payload'], check)
                return {'outcome': outcome, 'file_url': self.file_url}
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # No URLs, page HTML, cookies, board text or screenshots in logs.
                log.warning('FigJam browser action unverified (%s)', type(error).__name__)
                return {'outcome': 'uncertain', 'file_url': self.file_url}


async def run_actions(client, browser, has_work=lambda: True, session_id='figjam'):
    delay = .3
    while True:
        try:
            if not has_work():
                await asyncio.sleep(.3)
                continue
            action = await client.claim_browser()
            delay = .3
            if action:
                last_check = 0
                async def check():
                    nonlocal last_check
                    if dt.datetime.now(dt.UTC) >= dt.datetime.fromisoformat(action['expires_at']):
                        raise TimeoutError()
                    if time.monotonic() - last_check < .15:
                        return
                    await client.check_browser(action)
                    last_check = time.monotonic()
                # Deadline and cancellation run independently of browser waits.
                async def execute():
                    with stage(session_id, action['command_id'], 'figjam_browser', operation=action['operation']):
                        return await browser.execute(action, check)
                task = asyncio.create_task(execute())
                try:
                    while not task.done():
                        await asyncio.wait({task}, timeout=.3)
                        await check()
                    await client.complete_browser(action, await task)
                finally:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.warning('FigJam browser transport unavailable (%s)', type(error).__name__)
            delay = min(3, delay*2)
        await asyncio.sleep(delay)
