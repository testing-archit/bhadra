"""Evaluate a private JSON manifest; network calls require --transcribe.

Run from backend: python -m scripts.evaluate_telephony manifest.json --output report.json
For offline scoring supply each item's `hypothesis`; references/audio are never
written to the report. --transcribe sends audio to the configured Gnani account.
"""
import argparse
import asyncio
from collections import defaultdict
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import time
import unicodedata


def normalize(text):
    text = unicodedata.normalize("NFC", text).casefold()
    # Preserve Indic combining marks; \w-based tokenizers lose vowel signs.
    return " ".join("".join(" " if unicodedata.category(c)[0] in {"P", "S"} else c for c in text).split())


def edit_counts(reference, hypothesis):
    # Levenshtein with deterministic substitution/deletion/insertion counts.
    previous = [(j, 0, 0, j) for j in range(len(hypothesis) + 1)]
    for i, left in enumerate(reference, 1):
        current = [(i, 0, i, 0)]
        for j, right in enumerate(hypothesis, 1):
            if left == right:
                current.append(previous[j - 1])
            else:
                sub, delete, insert = previous[j - 1], previous[j], current[j - 1]
                current.append(min((sub[0]+1, sub[1]+1, sub[2], sub[3]),
                                   (delete[0]+1, delete[1], delete[2]+1, delete[3]),
                                   (insert[0]+1, insert[1], insert[2], insert[3]+1), key=lambda x: x[0]))
        previous = current
    return previous[-1]


def score(reference, hypothesis, entities=()):
    ref, hyp = normalize(reference), normalize(hypothesis)
    errors, substitutions, deletions, insertions = edit_counts(ref.split(), hyp.split())
    chars = edit_counts(list(ref.replace(" ", "")), list(hyp.replace(" ", "")))[0]
    entity_hits = sum(f" {normalize(entity)} " in f" {hyp} " for entity in entities)
    return {"reference_words": len(ref.split()), "word_errors": errors,
            "substitutions": substitutions, "deletions": deletions, "insertions": insertions,
            "wer": errors / len(ref.split()) if ref else None,
            "reference_characters": len(ref.replace(" ", "")), "character_errors": chars,
            "cer": chars / len(ref.replace(" ", "")) if ref else None,
            "entity_hits": entity_hits, "entity_total": len(entities),
            "silence_hallucinated_words": len(hyp.split()) if not ref else 0}


def aggregate(rows):
    totals = {key: sum(row.get(key, 0) for row in rows) for key in (
        "reference_words", "word_errors", "reference_characters", "character_errors",
        "entity_hits", "entity_total", "silence_hallucinated_words")}
    totals["wer"] = totals["word_errors"] / totals["reference_words"] if totals["reference_words"] else None
    totals["cer"] = totals["character_errors"] / totals["reference_characters"] if totals["reference_characters"] else None
    totals["entity_recall"] = totals["entity_hits"] / totals["entity_total"] if totals["entity_total"] else None
    times = sorted(row["elapsed_seconds"] for row in rows if "elapsed_seconds" in row)
    totals["latency_p95_seconds"] = times[max(0, int(len(times) * .95 + .999) - 1)] if times else None
    totals["clips"] = len(rows)
    return totals


async def recognize(item, audio, profile):
    # Only imported in explicitly enabled network mode; offline scoring needs
    # neither application settings, database, credentials nor NumPy.
    from unittest.mock import AsyncMock, patch
    import httpx
    from app.config import settings
    from app.services import transcriber, vocabulary_service
    from scripts.telephony_baseline import _split_for_prisma

    if profile == "scribe_v3":
        key = os.environ.get("ELEVEN_LABS_API_KEY") or os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            raise RuntimeError("ElevenLabs key is required for the Scribe baseline")
        data = {"model_id": "scribe_v3", "tag_audio_events": "false", "diarize": "false", "numbers_format": "words"}
        if item.get("language") == "en":
            data["language_code"] = "en"
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post("https://api.elevenlabs.io/v1/speech-to-text",
                headers={"xi-api-key": key}, files={"file": ("telephone.wav", audio, "audio/wav")}, data=data)
        if not response.is_success:
            raise RuntimeError(f"Scribe provider failure ({response.status_code})")
        return response.json()["text"], {"requests": 1, "model": "scribe_v3"}
    if not settings.gnani_api_key or settings.fixture_mode_active:
        raise RuntimeError("A real Gnani key and disabled development fixtures are required")
    mime = mimetypes.guess_type(item["audio"])[0] or "audio/wav"
    # Benchmark deliberately excludes database vocabulary/corrections to avoid
    # held-out reference leakage. Capture usage in the report, never fake DB rows.
    usage = []
    if profile == "legacy":
        parts = await _split_for_prisma(audio, mime)
        texts = []
        async with httpx.AsyncClient(timeout=60) as client:
            for _, duration, upload in parts:
                response = await client.post(settings.gnani_stt_url,
                    headers={"X-API-Key-ID": settings.gnani_api_key}, files={"audio_file": upload},
                    data={"model": settings.gnani_stt_model, "mode": "codemix", "format": "transcribe",
                          "language_code": {"en": "en-IN", "hi": "hi-IN"}.get(item.get("language"), "indic-auto")})
                if not response.is_success or response.json().get("success") is False:
                    raise RuntimeError(f"Baseline provider failure ({response.status_code})")
                texts.extend(t["text"] for t in transcriber._turns_from_prisma(response.json()))
        return " ".join(texts), {"requests": len(parts), "submitted_seconds": sum(p[1] for p in parts)}
    with patch.object(settings, "stt_enhancement", "off" if profile in {"raw", "robust"} else profile), \
         patch.object(settings, "gnani_stt_mode", "codemix"), \
         patch.object(vocabulary_service, "active_vocabulary", AsyncMock(return_value=vocabulary_service.Vocabulary())), \
         patch.object(vocabulary_service, "record_applied", AsyncMock()), \
         patch.object(transcriber.usage_ledger, "record_audio", side_effect=lambda *args: usage.append(args[-1])):
        result = await transcriber.transcribe_audio_detailed(audio, mime, item.get("language", "auto"),
            channel_mode=item.get("channel_mode", "preserve"), profile="robust" if profile == "robust" else "standard")
    return " ".join(t["text"] for t in result["turns"]), result["metadata"]["audio"]


async def evaluate(args):
    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("Manifest must be a non-empty list")
    results = []
    for item in manifest:
        for profile in args.profiles if args.transcribe else ["offline"]:
            row = {"id": item["id"], "condition": item.get("condition", "unspecified"), "profile": profile,
                   "split": item.get("split", "unspecified"), "language": item.get("language", "unspecified")}
            started = time.monotonic()
            try:
                if args.transcribe:
                    audio = (manifest_path.parent / item["audio"]).read_bytes()
                    row["audio_sha256"] = hashlib.sha256(audio).hexdigest()
                    hypothesis, metadata = await recognize(item, audio, profile)
                    row["audio"] = metadata
                    row["elapsed_seconds"] = round(time.monotonic() - started, 3)
                else:
                    hypothesis = item["hypothesis"]
                row.update(score(item["reference"], hypothesis, item.get("entities", [])))
                if args.save_hypotheses:
                    row["hypothesis"] = hypothesis
                row["status"] = "ok"
            except Exception as error:
                row.update(status="error", error=type(error).__name__)
                if isinstance(error, RuntimeError):
                    row["reason"] = str(error)
            results.append(row)
            # Persist partial evidence if a later provider request fails.
            groups = defaultdict(list)
            for entry in results:
                if entry["status"] == "ok":
                    groups[entry["profile"]].append(entry)
            report = {"normalization": "NFC, casefold, punctuation/symbols to spaces; no number/script rewriting",
                      "failed_clips": sum(r["status"] == "error" for r in results),
                      "summary": {k: aggregate(v) for k, v in groups.items()}, "clips": results}
            Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
            print(json.dumps({"id": item["id"], "profile": profile, "status": row["status"], "wer": row.get("wer")}), flush=True)
    print(json.dumps({"report": args.output, "failed_clips": report["failed_clips"], "summary": report["summary"]}, indent=2))
    return 1 if report["failed_clips"] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--output", required=True)
    parser.add_argument("--transcribe", action="store_true", help="Send manifest audio to the configured Gnani account")
    parser.add_argument("--profiles", nargs="+", choices=["legacy", "raw", "spectral", "rnnoise", "scribe_v3", "robust"], default=["legacy", "raw"])
    parser.add_argument("--save-hypotheses", action="store_true", help="Include transcripts in the private report for error analysis")
    raise SystemExit(asyncio.run(evaluate(parser.parse_args())))


if __name__ == "__main__":
    main()
