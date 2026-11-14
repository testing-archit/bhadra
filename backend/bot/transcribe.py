"""Send one WAV file to Gnani Prisma for a quick credential/audio check.

The production service owns normal ingestion. This is only a small manual
diagnostic for the notetaker image.
"""

import json
import os
import sys

import httpx

GNANI_STT_URL = os.getenv("GNANI_STT_URL", "https://api.vachana.ai/stt/v3")


def main(wav_path: str, out_path: str) -> None:
    api_key = os.environ["GNANI_API_KEY"]
    audio = open(wav_path, "rb").read()
    print(f"Sending {len(audio)} bytes to Gnani Prisma...", flush=True)

    with httpx.Client(timeout=httpx.Timeout(300.0, connect=20.0)) as client:
        response = client.post(
            GNANI_STT_URL,
            headers={"X-API-Key-ID": api_key},
            files={"audio_file": ("meeting.wav", audio, "audio/wav")},
            data={
                "model": "prisma-v3.0",
                "mode": "codemix",
                "format": "transcribe",
                "language_code": "auto",
                "preferred_language": "auto",
            },
        )

    if not response.is_success:
        print(f"Gnani Prisma error {response.status_code}: {response.text}", flush=True)
        sys.exit(1)

    payload = response.json()
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)

    print("Transcript preview:", flush=True)
    print(f"  {payload.get('transcript') or (payload.get('results') or {}).get('transcript') or ''}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
