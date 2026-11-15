"""Real Chromium canvas presentation safety check with intercepted synthetic pages.

No Figma account, network requests, native editor or Google Meet is exercised.
"""
import asyncio
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'bot'))
from figjam_browser import FigJamBrowser
import board_presenter


async def main():
    async with async_playwright() as p:
        options = {'headless': True}
        if os.environ.get('BROWSER_EXECUTABLE_PATH'):
            options['executable_path'] = os.environ['BROWSER_EXECUTABLE_PATH']
        browser = await p.chromium.launch(**options)
        context = await browser.new_context()
        async def fixture(route):
            await route.fulfill(content_type='text/html', body='''<p>PRIVATE ACCOUNT UI MUST NOT BE SHARED</p>
                <canvas width="640" height="360"></canvas><script>
                const c=document.querySelector('canvas').getContext('2d');
                c.fillStyle='rgb(0,100,200)';c.fillRect(0,0,640,360);
                c.fillStyle='white';c.font='32px sans-serif';c.fillText('Synthetic FigJam canvas',30,90);
                </script>''')
        await context.route('**/*', fixture)
        native = await context.new_page()
        await native.goto('https://www.figma.com/board/ABCdef123456')
        actor = FigJamBrowser(p)
        actor.page, actor.file_url = native, native.url
        frame = await actor.frame()
        assert frame and frame['frame_image'].startswith('data:image/jpeg;base64,')
        receiver = await context.new_page()
        await receiver.goto('https://meet.google.com/synthetic')
        await receiver.evaluate(board_presenter.SCRIPT)
        await receiver.evaluate('(frame) => window.__wilcoBoard.arm(frame)', frame)
        await receiver.wait_for_function("window.__wilcoBoard.preview().length > 10000")
        sample = await receiver.evaluate('''async () => {
          const i=new Image(); i.src=window.__wilcoBoard.preview(); await i.decode();
          const c=document.createElement('canvas');c.width=1280;c.height=720;
          const ctx=c.getContext('2d');ctx.drawImage(i,0,0);
          return [...ctx.getImageData(0,0,1,1).data];
        }''')
        assert abs(sample[0]) < 5 and abs(sample[1]-100) < 5 and abs(sample[2]-200) < 5, sample
        await native.goto('https://www.figma.com/login')
        assert await actor.frame() is None
        await browser.close()
        print('PASS: verified canvas pixels transferred; account DOM excluded; login navigation suppresses frames. Synthetic pages only.')


if __name__ == '__main__':
    asyncio.run(main())
