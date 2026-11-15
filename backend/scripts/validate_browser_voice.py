"""Synthetic WebRTC audio proof. No account, meeting, or real microphone."""
import argparse
import asyncio
import base64
import io
import json
import math
import struct
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'bot'))
from browser_voice import SCRIPT
from playwright.async_api import async_playwright


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
        self.wfile.write(b'<title>Synthetic microphone proof</title>')
    def log_message(self, *args): pass


async def validate(args):
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with io.BytesIO() as output:
        with wave.open(output, 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
            wav.writeframes(b''.join(struct.pack('<h', int(9000*math.sin(2*math.pi*440*i/24000))) for i in range(48000)))
        encoded = base64.b64encode(output.getvalue()).decode()
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path=args.chromium, args=['--autoplay-policy=no-user-gesture-required', '--mute-audio'])
            page = await browser.new_page()
            await page.add_init_script(SCRIPT)
            await page.goto(f'http://127.0.0.1:{server.server_port}')
            await page.evaluate('''async () => {
              const stream = await navigator.mediaDevices.getUserMedia({audio:true});
              window.a = new RTCPeerConnection(); window.b = new RTCPeerConnection();
              a.onicecandidate=e=>e.candidate&&b.addIceCandidate(e.candidate);
              b.onicecandidate=e=>e.candidate&&a.addIceCandidate(e.candidate);
              window.received = new Promise(resolve => b.ontrack=async e=>{
                const playback = document.createElement('audio');
                playback.srcObject = new MediaStream([e.track]);
                playback.autoplay = true; playback.volume = 0;
                document.body.appendChild(playback); await playback.play();
                const context = new AudioContext();
                window.analyser=context.createAnalyser(); analyser.fftSize=4096;
                context.createMediaStreamSource(new MediaStream([e.track])).connect(analyser);
                const silent=context.createGain(); silent.gain.value=0;
                analyser.connect(silent); silent.connect(context.destination);
                await context.resume(); resolve();
              });
              stream.getTracks().forEach(track=>a.addTrack(track,stream));
              await a.setLocalDescription(await a.createOffer());
              await b.setRemoteDescription(a.localDescription);
              await b.setLocalDescription(await b.createAnswer());
              await a.setRemoteDescription(b.localDescription); await received;
              // A separate browser speaker source must never reach the mic.
              const context=new AudioContext(); const tone=context.createOscillator();
              tone.frequency.value=880; tone.connect(context.destination); tone.start(); await context.resume();
              window.energy=()=>{const samples=new Float32Array(analyser.fftSize);analyser.getFloatTimeDomainData(samples);return Math.sqrt(samples.reduce((sum,v)=>sum+v*v,0)/samples.length)};
            }''')
            await page.wait_for_function('a.connectionState === "connected" && b.connectionState === "connected"', timeout=10000)
            await asyncio.sleep(.3)
            quiet = await page.evaluate('energy()')
            metadata = await page.evaluate('(encoded)=>__wilcoMic.play(encoded)', encoded)
            await asyncio.sleep(.5)
            speaking = await page.evaluate('energy()')
            peak = await page.evaluate('''() => {const bins=new Float32Array(analyser.frequencyBinCount);analyser.getFloatFrequencyData(bins);let max=0;for(let i=1;i<bins.length;i++)if(bins[i]>bins[max])max=i;return max*analyser.context.sampleRate/analyser.fftSize}''')
            await page.evaluate('__wilcoMic.stop()')
            await asyncio.sleep(.5)
            stopped = await page.evaluate('energy()')
            malformed = await page.evaluate('''async()=>{try{await __wilcoMic.play(btoa('invalid audio'));return false}catch{return !__wilcoMic.playing}}''')
            assert quiet < .005 and speaking > .05 and stopped < .005
            assert 425 < peak < 455 and malformed
            await browser.close()
            print(json.dumps({'unrelated_speaker_rms':round(quiet,5),'received_speech_rms':round(speaking,5),
                'received_peak_hz':round(peak,2),'stopped_rms':round(stopped,5),'malformed_audio_rejected':malformed,**metadata}))
    finally:
        server.shutdown(); server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chromium', required=True)
    asyncio.run(validate(parser.parse_args()))
