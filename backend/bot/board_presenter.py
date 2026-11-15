"""Experimental Meet presentation adapter. A live track is not proof of remote delivery."""
import asyncio
from pathlib import Path

SCRIPT = Path(__file__).with_name('board_presenter.js').read_text()


async def start(page, board: dict) -> bool:
    state = await page.evaluate('() => window.__wilcoBoard.state()')
    if state.get('active'):
        await page.evaluate('(board) => window.__wilcoBoard.draw(board)', board)
        return bool(await page.get_by_role('button', name='Stop presenting', exact=False).count())
    await page.evaluate('(board) => window.__wilcoBoard.arm(board)', board)
    try:
        button = page.get_by_role('button', name='Present now', exact=False)
        if await button.count() == 0:
            await page.evaluate('() => window.__wilcoBoard.stop()')
            return False
        await button.first.click(timeout=3000)
        # Some Meet versions open a sharing-source menu before getDisplayMedia.
        for label in ('A tab', 'Your entire screen', 'Entire screen'):
            item = page.get_by_role('menuitem', name=label, exact=False)
            if await item.count():
                await item.first.click(timeout=2000)
                break
        for _ in range(20):
            state = await page.evaluate('() => window.__wilcoBoard.state()')
            if state['active']:
                # Also require Meet's own local presenting indicator.
                stop = page.get_by_role('button', name='Stop presenting', exact=False)
                if await stop.count():
                    return True
            await asyncio.sleep(0.25)
    except Exception:
        pass
    await page.evaluate('() => window.__wilcoBoard.stop()')
    return False


async def stop(page):
    await page.evaluate('() => window.__wilcoBoard?.stop()')
    button = page.get_by_role('button', name='Stop presenting', exact=False)
    if await button.count():
        await button.first.click(timeout=2000)
