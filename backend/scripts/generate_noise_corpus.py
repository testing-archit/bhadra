"""Generate synthetic ElevenLabs speech/noise, then controlled G.711 mixtures.

Credentials come only from the environment (ELEVEN_LABS_API_KEY or
ELEVENLABS_API_KEY). Use --generate to authorize generation; existing assets
are reused. Audio stays in --output, outside git. This is not real-call data.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess

import httpx
import numpy as np

from app.services.audio_preparation import wav_bytes

SPEECH = [
    {"id": "invoice_en", "voice": "EXAVITQu4vr4xnSDxMaL", "language": "en",
     "text": "Maya, please send the revised invoice by Friday. The total is fifteen hundred rupees. Do not cancel the customer account. Confirm the delivery address before sending the package.",
     "entities": ["Maya", "Friday", "do not cancel"]},
    {"id": "release_en", "voice": "JBFqnCBsd6RMkjVDRZzb", "language": "en",
     "text": "Rohan, roll back the payment service if the error rate rises. Keep the database running. Schedule the security review for Tuesday. The support ticket ends in seven four two nine.",
     "entities": ["Rohan", "Tuesday", "keep the database running"]},
    {"id": "invoice_hi", "voice": "EXAVITQu4vr4xnSDxMaL", "language": "hinglish",
     "text": "माया, revised invoice शुक्रवार तक भेज देना। कुल रकम पंद्रह सौ रुपये है। Customer account बंद मत करना। Package भेजने से पहले delivery address confirm कर लेना।",
     "entities": ["माया", "शुक्रवार", "बंद मत करना"]},
    {"id": "release_hi", "voice": "JBFqnCBsd6RMkjVDRZzb", "language": "hinglish",
     "text": "रोहन, error rate बढ़े तो payment service rollback कर देना। Database चालू रखना। Security review मंगलवार को रखो। Support ticket के आखिरी अंक सात चार दो नौ हैं।",
     "entities": ["रोहन", "मंगलवार", "चालू रखना"]},
]
NOISE = {
    "street": "Continuous busy Indian city street ambience: engines, passing motorcycles, irregular car horns, wind rumble. No intelligible words, no music, no foreground voice.",
    "cafe": "Busy cafe ambience: clattering dishes, espresso machine hiss, chairs scraping, distant indistinct crowd babble. No intelligible words, no foreground speaker, no music.",
}
VALIDATION_SPEECH = [
    {"id": "handoff_en", "voice": "CwhRBWXzGAHq8TQ4Fs17", "language": "en",
     "text": "Neha, do not delete the backup. Move the customer interview to Thursday afternoon. Ask Dev to check the failed refund before closing the ticket. The meeting room is on the second floor.",
     "entities": ["Neha", "do not delete", "Thursday", "Dev", "failed refund"]},
    {"id": "handoff_hi", "voice": "SAz9YHcvj6GT2YYXdXww", "language": "hinglish",
     "text": "नेहा, backup delete मत करना। Customer interview गुरुवार दोपहर को रखो। Ticket बंद करने से पहले देव से failed refund check करवाना। Meeting room दूसरी मंजिल पर है।",
     "entities": ["नेहा", "मत करना", "गुरुवार", "देव", "failed refund"]},
]
VALIDATION_NOISE = {
    "construction": "Continuous roadside construction noise, jackhammer rattling, truck engines and metallic bangs. No voices, no words, no music.",
    "office": "Office noise bed with a loud ventilation fan, intermittent keyboard typing, paper rustling, telephone ringing in the distance. No voices, no words, no music.",
}


def decode(path):
    result = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000",
                             "-af", "highpass=f=300,lowpass=f=3400", "-f", "f32le", "pipe:1"],
                            capture_output=True, check=True, timeout=60)
    return np.frombuffer(result.stdout, dtype="<f4").copy()


def mix(speech, noise, snr_db, offset=0):
    noise = np.resize(np.roll(noise, offset), speech.shape)
    # SNR referenced to active 20 ms speech frames, not long silence regions.
    usable = speech[:len(speech)//320*320].reshape(-1, 320)
    energy = np.mean(usable ** 2, axis=1)
    active = usable[energy > max(float(energy.max()) * .01, 1e-10)]
    speech_rms = float(np.sqrt(np.mean(active ** 2)))
    noise_rms = float(np.sqrt(np.mean(noise ** 2)))
    scaled = noise * (speech_rms / max(noise_rms, 1e-10) / 10 ** (snr_db/20))
    result = speech + scaled
    result *= min(1.0, .95 / max(float(np.abs(result).max()), 1e-10))
    return (result * 32767).astype("<i2")


async def generate(args):
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    key = os.environ.get("ELEVEN_LABS_API_KEY") or os.environ.get("ELEVENLABS_API_KEY")
    receipts = []
    speech_items = VALIDATION_SPEECH if args.validation else SPEECH
    noise_prompts = VALIDATION_NOISE if args.validation else NOISE
    async with httpx.AsyncClient(timeout=120) as client:
        async def asset(name, endpoint, payload):
            path = output / name
            if not path.exists():
                if not args.generate or not key:
                    raise RuntimeError("Missing audio assets; provide a key and --generate")
                response = await client.post("https://api.elevenlabs.io/v1/" + endpoint,
                    headers={"xi-api-key": key}, json=payload, params={"output_format": "mp3_44100_128"})
                if not response.is_success:
                    raise RuntimeError(f"ElevenLabs generation failed: HTTP {response.status_code}")
                path.write_bytes(response.content)
                receipts.append({"asset": name, "character_cost": response.headers.get("character-cost"),
                                 "request_id": response.headers.get("request-id"), "model": payload["model_id"]})
            return path
        for item in speech_items:
            await asset(item["id"] + ".mp3", "text-to-speech/" + item["voice"],
                        {"model_id": "eleven_v3", "text": item["text"], "seed": 42,
                         "voice_settings": {"stability": .5, "similarity_boost": .75}})
        for name, prompt in noise_prompts.items():
            await asset(name + ".mp3", "sound-generation", {"text": prompt,
                "model_id": "eleven_text_to_sound_v3", "duration_seconds": 15, "loop": True})
    manifest = []
    noise = {name: decode(output / (name + ".mp3")) for name in noise_prompts}
    for item in speech_items:
        speech = decode(output / (item["id"] + ".mp3"))
        variants = [("clean", (speech * 32767).astype("<i2"), None)]
        for kind in noise_prompts:
            for snr in (10, 0, -5):
                variants.append((f"{kind}_{snr}db", mix(speech, noise[kind], snr), snr))
        if args.validation:
            clipped = np.clip(speech * 6, -.8, .8)
            dropout = speech.copy()
            for position in range(8000, len(dropout), 32000):
                dropout[position:position+1600] = 0  # deterministic 100 ms loss
            variants += [("clipped", (clipped * 32767).astype("<i2"), None),
                         ("packet_loss", (dropout * 32767).astype("<i2"), None)]
        for condition, samples, snr in variants:
            clip_id = item["id"] + "_" + condition
            intermediate, target = output / "mixture.wav", output / (clip_id + ".wav")
            intermediate.write_bytes(wav_bytes(samples, 16000))
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(intermediate),
                            "-ar", "8000", "-c:a", "pcm_mulaw", str(target)], check=True, timeout=60)
            manifest.append({"id": clip_id, "audio": target.name, "reference": item["text"],
                             "language": item["language"], "entities": item["entities"],
                             "condition": condition, "snr_db_before_codec": snr, "split": "validation" if args.validation else ("development" if "invoice" in item["id"] else "heldout"),
                             "source": "ElevenLabs synthetic speech and generated noise; G.711 mu-law 8kHz",
                             "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    (output / "silence.wav").write_bytes(wav_bytes(np.zeros(3*8000, dtype="<i2"), 8000))
    manifest.append({"id": "silence", "audio": "silence.wav", "reference": "", "condition": "silence"})
    if args.validation:
        for kind, samples in noise.items():
            name = kind + "_noise_only.wav"
            (output / name).write_bytes(wav_bytes((samples * 32767).astype("<i2"), 16000))
            manifest.append({"id": kind+"_noise_only", "audio": name, "reference": "", "condition": "noise_only", "split": "validation"})
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
    receipt_path = output / "generation-receipts.json"
    old_receipts = json.loads(receipt_path.read_text()) if receipt_path.exists() else []
    receipt_path.write_text(json.dumps(old_receipts + receipts, indent=2)+"\n")
    print(json.dumps({"clips": len(manifest), "manifest": str(output / "manifest.json"), "new_generations": len(receipts)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--validation", action="store_true", help="Fresh scripts, voices, noise, clipping and packet loss")
    asyncio.run(generate(parser.parse_args()))
