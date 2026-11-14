"""Local voice embeddings for enrolled employees.

Prisma supplies anonymous speaker turns. This service compares those turns
against profiles recorded by employees themselves. An uncertain match keeps
its anonymous speaker label; a name is never invented from the invite list.
"""

import asyncio
import json
import math
import subprocess
import tempfile
import threading
import uuid
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import User, VoiceProfile
from app.services import secret_box

MODEL_ID = "wespeaker_en_voxceleb_resnet34"
_inference_lock = threading.Lock()


def _model_path() -> Path:
    path = Path(settings.speaker_embedding_model_path)
    return path if path.is_absolute() else Path(__file__).resolve().parents[2] / path


def available() -> bool:
    return _model_path().is_file()


@lru_cache(maxsize=1)
def _extractor():
    import sherpa_onnx

    path = str(_model_path())
    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=path, num_threads=1, provider="cpu"
    )
    if not config.validate():
        raise RuntimeError(f"Speaker embedding model is invalid: {path}")
    return sherpa_onnx.SpeakerEmbeddingExtractor(config)


def _pcm(path: str, start: float | None = None, duration: float | None = None) -> np.ndarray:
    command = ["ffmpeg", "-v", "error"]
    if start is not None:
        command += ["-ss", str(start)]
    command += ["-i", path]
    if duration is not None:
        command += ["-t", str(duration)]
    command += ["-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"]
    result = subprocess.run(command, capture_output=True, check=False, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(f"Could not read voice audio: {result.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(result.stdout, dtype=np.float32).copy()


def _embedding(samples: np.ndarray) -> list[float]:
    if len(samples) < 16000 * 5:
        raise ValueError("At least five seconds of clear speech are needed")
    with _inference_lock:
        extractor = _extractor()
        stream = extractor.create_stream()
        stream.accept_waveform(sample_rate=16000, waveform=np.ascontiguousarray(samples))
        stream.input_finished()
        if not extractor.is_ready(stream):
            raise ValueError("The voice sample was too short for recognition")
        vector = np.asarray(extractor.compute(stream), dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if norm <= 0 or not np.isfinite(norm):
        raise ValueError("Could not create a voice profile from this recording")
    return (vector / norm).tolist()


def embed_enrollment(audio: bytes) -> list[float]:
    if len(audio) > 8_000_000:
        raise ValueError("Voice sample is too large")
    with tempfile.NamedTemporaryFile(suffix=".webm") as source:
        source.write(audio)
        source.flush()
        samples = _pcm(source.name)
    seconds = len(samples) / 16000
    if seconds < 8 or seconds > 60:
        raise ValueError("Record between 8 and 60 seconds of your own voice")
    return _embedding(samples)


def _speaker_embedding(source_path: str, turns: list[dict]) -> list[float] | None:
    # Several clean, longer turns are more reliable than a single short reply.
    chosen = sorted(
        (turn for turn in turns if float(turn.get("end", 0)) - float(turn.get("start", 0)) >= 2.5),
        key=lambda turn: float(turn["end"]) - float(turn["start"]),
        reverse=True,
    )[:5]
    samples = []
    for turn in chosen:
        start = max(0.0, float(turn["start"]))
        duration = min(10.0, float(turn["end"]) - start)
        samples.append(_pcm(source_path, start, duration))
        if sum(len(part) for part in samples) >= 16000 * 20:
            break
    if not samples or sum(len(part) for part in samples) < 16000 * 8:
        return None
    return _embedding(np.concatenate(samples))


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return -1.0
    return float(np.dot(np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)))


def _match(audio: bytes, turns: list[dict], profiles: list[tuple[str, list[float]]]) -> dict[str, str]:
    by_speaker: dict[str, list[dict]] = defaultdict(list)
    for turn in turns:
        by_speaker[str(turn["speaker"])].append(turn)
    scores: list[tuple[float, str, str]] = []
    with tempfile.NamedTemporaryFile(suffix=".webm") as source:
        source.write(audio)
        source.flush()
        for speaker, speaker_turns in by_speaker.items():
            vector = _speaker_embedding(source.name, speaker_turns)
            if vector is None:
                continue
            ranked = sorted(
                ((_cosine(vector, enrolled), name) for name, enrolled in profiles),
                reverse=True,
            )
            if not ranked:
                continue
            best_score, best_name = ranked[0]
            runner_up = ranked[1][0] if len(ranked) > 1 else -1.0
            if best_score >= settings.speaker_match_threshold and best_score - runner_up >= settings.speaker_match_margin:
                scores.append((best_score, speaker, best_name))
    names: dict[str, str] = {}
    for _, speaker, name in sorted(scores, reverse=True):
        names[speaker] = name
    return names


async def match_known_voices(
    db: AsyncSession, audio: bytes, turns: list[dict], candidate_ids: set[uuid.UUID]
) -> dict[str, str]:
    if not available() or not candidate_ids or not turns:
        return {}
    rows = await db.execute(
        select(User, VoiceProfile)
        .join(VoiceProfile, VoiceProfile.user_id == User.id)
        .where(User.id.in_(candidate_ids), User.status == "active")
    )
    profiles = []
    for user, profile in rows.all():
        if profile.model != MODEL_ID:
            continue
        decoded = secret_box.decrypt(profile.embedding_encrypted)
        if decoded and user.name:
            profiles.append((user.name, json.loads(decoded)))
    if not profiles:
        return {}
    return await asyncio.to_thread(_match, audio, turns, profiles)


def blend_confirmed(old: list[float], new: list[float], count: int) -> list[float]:
    if len(old) != len(new):
        raise ValueError("Voice profile model changed")
    weight = min(count, 5)
    vector = np.asarray(old, dtype=np.float32) * weight + np.asarray(new, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("Could not update voice profile")
    return (vector / norm).tolist()


async def embed_confirmed_turns(audio_path: Path, turns: list[dict]) -> list[float] | None:
    if not available():
        return None
    return await asyncio.to_thread(_speaker_embedding, str(audio_path), turns)
