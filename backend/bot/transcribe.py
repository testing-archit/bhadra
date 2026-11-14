"""Standalone Deepgram call for the bot prototype -- mirrors the params
backend/app/services/transcriber.py uses (nova-3, diarize=true) so results
are directly comparable to what the real ingest pipeline would produce.
Not wired into the backend; this is throwaway validation code.
"""

import json
import os
import sys

import httpx

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


def main(wav_path: str, out_path: str) -> None:
    api_key = os.environ["DEEPGRAM_API_KEY"]
    audio = open(wav_path, "rb").read()
    print(f"Sending {len(audio)} bytes to Deepgram...", flush=True)

    params = [
        ("model", "nova-3"),
        ("language", "multi"),
        ("smart_format", "true"),
        ("punctuate", "true"),
        ("diarize", "true"),
        ("utterances", "true"),
        ("utt_split", "0.8"),
    ]

    with httpx.Client(timeout=httpx.Timeout(300.0, connect=20.0)) as client:
        response = client.post(
            DEEPGRAM_URL,
            params=params,
            headers={"Authorization": f"Token {api_key}", "Content-Type": "audio/wav"},
            content=audio,
        )

    if not response.is_success:
        print(f"Deepgram error {response.status_code}: {response.text}", flush=True)
        sys.exit(1)

    payload = response.json()
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)

    results = payload.get("results") or {}
    utterances = results.get("utterances") or []
    print(f"Got {len(utterances)} utterances. Preview:", flush=True)
    for u in utterances[:20]:
        print(f"  speaker {u.get('speaker')}: {u.get('transcript')}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
