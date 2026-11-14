"""Local browser/WebRTC proof for the canvas adapter, not a real Meet acceptance test.

Requires playwright and a Chromium installation. Never joins a meeting.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bot'))
from board_presenter import SCRIPT, start, stop
from playwright.async_api import async_playwright


async def main(args):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=args.chromium, args=['--autoplay-policy=no-user-gesture-required'])
        page = await browser.new_page(viewport={'width': 1280, 'height': 720})
        # Real media APIs require a secure origin, fulfilled locally without network.
        await page.route('https://board.test/**', lambda route: route.fulfill(
            content_type='text/html', body='''<style>body{margin:0}video{width:1280px;height:720px}</style>
            <button id="present">Present now</button><video autoplay muted></video>
            <script>document.querySelector('button').onclick=async()=>{
              window.outgoing=await navigator.mediaDevices.getDisplayMedia({video:true});
              document.querySelector('button').textContent='Stop presenting';
            }</script>'''))
        await page.add_init_script(SCRIPT)
        await page.goto('https://board.test/')
        board = {'title': 'Customer onboarding', 'version': 1, 'nodes': [
            {'id': str(i), 'kind': 'idea', 'title': title, 'text': text, 'x': 80+i*370, 'y': 100,
             'origin': 'ai'} for i, (title, text) in enumerate([
                 ('Signup', 'Create an account'), ('Verification', 'Confirm identity'), ('Activation', 'Welcome the customer')])
        ], 'edges': [{'source': '0', 'target': '1'}, {'source': '1', 'target': '2'}]}
        assert await start(page, board), 'Local presenting indicator missing'
        assert await start(page, board), 'Repeated presentation should preserve the live stream'
        # Transmit the actual canvas track through two real local WebRTC peers.
        await page.evaluate('''async () => {
            const sender = window.sender = new RTCPeerConnection();
            const receiver = window.receiver = new RTCPeerConnection();
            const gather = pc => pc.iceGatheringState === 'complete' ? Promise.resolve() :
              new Promise(resolve => pc.addEventListener('icegatheringstatechange', () => {
                if (pc.iceGatheringState === 'complete') resolve();
              }));
            receiver.ontrack = e => { document.querySelector('video').srcObject = e.streams[0]; };
            window.outgoing.getTracks().forEach(t => sender.addTrack(t, window.outgoing));
            await sender.setLocalDescription(await sender.createOffer());
            await gather(sender);
            await receiver.setRemoteDescription(sender.localDescription);
            await receiver.setLocalDescription(await receiver.createAnswer());
            await gather(receiver);
            await sender.setRemoteDescription(receiver.localDescription);
        }''')
        await page.wait_for_function('document.querySelector("video").readyState >= 2', timeout=10000)
        board['version'] = 2
        board['nodes'][1]['title'] = 'Verification before activation'
        await page.evaluate('(board) => window.__wilcoBoard.draw(board)', board)
        await page.wait_for_timeout(300)
        await page.locator('video').screenshot(path=args.screenshot)
        state = await page.evaluate('() => window.__wilcoBoard.state()')
        assert state['version'] == 2 and state['active']
        await stop(page)
        assert not (await page.evaluate('() => window.__wilcoBoard.state()'))['active']
        await page.evaluate('() => { sender.close(); receiver.close(); }')
        await browser.close()
        print('Verified: canvas stream, local presentation indicator, WebRTC video delivery, live update, and stop.')
        print('Screenshot:', args.screenshot)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chromium')
    parser.add_argument('--screenshot', default='/tmp/wilco-board-presentation.png')
    asyncio.run(main(parser.parse_args()))
