"""Synthetic Chromium outgoing-camera fallback check; never joins a real call."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bot'))
import board_presenter
from meeting_session import AVATAR_CAMERA_JS
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
        page = await browser.new_page()
        await page.route('https://board.test/**', lambda route: route.fulfill(
            content_type='text/html', body='<video autoplay muted></video>'))
        await page.goto('https://board.test/')
        red = await page.evaluate('''() => {const c=document.createElement('canvas');c.width=640;c.height=360;
            const ctx=c.getContext('2d');ctx.fillStyle='rgb(200,0,0)';ctx.fillRect(0,0,640,360);
            return c.toDataURL().split(',')[1];}''')
        await page.evaluate(AVATAR_CAMERA_JS.replace('__IDLE__', red).replace('__SPEAKING__', red))
        await page.evaluate(board_presenter.SCRIPT)
        # A blocked/missing share control produces a camera fallback, not a desktop stream.
        board = {'title': 'Synthetic board', 'version': 1, 'nodes': [], 'edges': []}
        assert not await board_presenter.start(page, board)
        print('Checking outgoing camera track', flush=True)
        await page.evaluate('''async () => {
            window.outgoing=await navigator.mediaDevices.getUserMedia({video:true});
            document.querySelector('video').srcObject=outgoing;
            window.pixel=()=>{const c=document.createElement('canvas');c.width=640;c.height=360;
                const ctx=c.getContext('2d');ctx.drawImage(document.querySelector('video'),0,0,640,360);
                return [...ctx.getImageData(10,10,1,1).data];};
        }''')
        await page.wait_for_function('document.querySelector("video").readyState>=2', timeout=10000)
        await page.wait_for_function('pixel()[0]>180 && pixel()[1]<15')
        for color, channel, version in [('rgb(0,0,200)', 2, 2), ('rgb(0,200,0)', 1, 3)]:
            await page.evaluate('''({color,version})=>{const c=document.createElement('canvas');c.width=1280;c.height=720;
                const ctx=c.getContext('2d');ctx.fillStyle=color;ctx.fillRect(0,0,1280,720);
                window.__wilcoBoard.showInCamera({version,frame_image:c.toDataURL()});}''', {'color': color, 'version': version})
            await page.wait_for_function('(channel)=>pixel()[channel]>180 && pixel()[0]<15', arg=channel)
        await page.locator('video').screenshot(path='/private/tmp/wilco-board-camera.png')
        await board_presenter.stop(page)
        await page.wait_for_function('pixel()[0]>180 && pixel()[1]<15')
        assert not (await page.evaluate('window.__wilcoBoard.state()'))['cameraVisible']
        await page.evaluate('outgoing.getTracks().forEach(t=>t.stop())')
        await browser.close()
        print('PASS: outgoing camera stream carried live board updates; stop restored avatar. Synthetic pages only.')


if __name__ == '__main__':
    asyncio.run(main())
