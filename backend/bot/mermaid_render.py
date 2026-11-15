"""Render a board's Mermaid diagram to an image for Meet presentation.

Rendering runs in its own headless Chromium, never the Meet tab: a hidden
page there could steal focus or be throttled, and the Meet page keeps only the
small presenter script. Mermaid is vendored (assets/mermaid.min.js, MIT) and
runs with securityLevel 'strict'. The backend has already validated the source.
"""
import asyncio
import base64
import hashlib
import logging
from pathlib import Path

log = logging.getLogger(__name__)

MERMAID = Path(__file__).with_name('assets') / 'mermaid.min.js'
PAGE = '''<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:#fff}#out{display:inline-block;padding:40px;background:#fff}
#out svg{max-width:none!important;height:auto}</style></head><body><div id="out"></div></body></html>'''


def latest_diagram(board: dict | None) -> dict | None:
    """The diagram Meet should show: the last diagram node on the board."""
    for node in reversed((board or {}).get('nodes') or []):
        if node.get('kind') == 'diagram' and str(node.get('text') or '').strip():
            return node
    return None


class MermaidRenderer:
    def __init__(self, playwright, cache_size: int = 8):
        self._playwright = playwright
        self._browser = None
        self._page = None
        self._cache: dict[str, str] = {}
        self._cache_size = cache_size
        self._lock = asyncio.Lock()

    async def _ready(self):
        if self._page and not self._page.is_closed():
            return self._page
        if self._browser is None:
            self._browser = await self._playwright.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        self._page = await self._browser.new_page(viewport={'width': 1600, 'height': 900}, device_scale_factor=2)
        await self._page.set_content(PAGE)
        await self._page.add_script_tag(path=str(MERMAID))
        await self._page.evaluate("""() => mermaid.initialize({startOnLoad: false, securityLevel: 'strict',
            theme: 'neutral', flowchart: {htmlLabels: false}, fontFamily: 'Inter, Helvetica, Arial, sans-serif'})""")
        return self._page

    async def image(self, source: str) -> str | None:
        """PNG data URL for the source, or None if Mermaid can't render it."""
        key = hashlib.sha256(source.encode()).hexdigest()
        if key in self._cache:
            return self._cache[key]
        async with self._lock:
            if key in self._cache:
                return self._cache[key]
            try:
                page = await self._ready()
                await page.evaluate("""async (source) => {
                    const out = document.getElementById('out');
                    out.innerHTML = '';
                    const {svg} = await mermaid.render('wilco' + Math.floor(performance.now()), source);
                    out.innerHTML = svg;
                }""", source)
                png = await page.locator('#out').screenshot(type='png', timeout=5000)
            except Exception as error:
                # No diagram text or page content in logs.
                log.warning('Mermaid diagram could not be rendered (%s)', type(error).__name__)
                return None
            url = 'data:image/png;base64,' + base64.b64encode(png).decode()
            if len(self._cache) >= self._cache_size:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = url
            return url

    async def present(self, board: dict | None) -> dict | None:
        """The board as the presenter should draw it: the latest diagram as an image when there is one."""
        diagram = latest_diagram(board)
        if not board or diagram is None:
            return board
        url = await self.image(str(diagram['text']))
        if not url:
            return board
        return {**board, 'frame_image': url}

    async def close(self):
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        self._browser = self._page = None
