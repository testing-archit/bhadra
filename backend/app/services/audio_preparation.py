"""Bounded, lossless ASR input preparation. Originals are never overwritten.

Quiet-window detection chooses cuts; it is NOT a speech detector and never
discards quiet speech. Only exactly zero PCM chunks skip the recognizer.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import io
import logging
from pathlib import Path
import shutil
import tempfile
import wave

import numpy as np

logger = logging.getLogger(__name__)
MAX_SECONDS = 4 * 3600
MAX_PCM_BYTES = 1536 * 1024 * 1024


class InvalidAudio(ValueError):
    pass


async def _ffmpeg(arguments: list[str], *, timeout: float = 300, cwd=None) -> None:
    """Kill/reap on timeout or request cancellation; never log media/paths."""
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-v", "error", "-y", "-threads", "1",
        *arguments, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL, cwd=cwd,
    )
    try:
        async with asyncio.timeout(timeout):
            await process.communicate()
        if process.returncode:
            raise InvalidAudio("Audio could not be decoded")
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()


def wav_bytes(samples: np.ndarray, rate: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1 if samples.ndim == 1 else samples.shape[1])
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.astype("<i2", copy=False).tobytes())
    return output.getvalue()


def cut_frame(samples: np.ndarray, rate: int) -> int:
    """Prefer a >=200 ms quiet valley between 22 and 27 s, else 25 s.

    Require both low absolute energy and a valley relative to this clip.
    No overlap, removal, or text deduplication: every sample occurs once.
    """
    if len(samples) <= 28 * rate:
        return len(samples)
    hop = max(1, rate // 50)  # 20 ms
    frames = samples[:(28 * rate // hop) * hop].astype(np.float32)
    if frames.ndim == 1:
        frames = frames[:, None]
    levels = np.sqrt(np.mean(frames.reshape(-1, hop, frames.shape[1]) ** 2, axis=1)).max(axis=1)
    threshold = min(32768 * 10 ** (-35 / 20), float(np.percentile(levels, 80)) * 0.2)
    quiet = levels <= threshold
    candidates = [i for i in range(1100, min(1350, len(quiet) - 5))
                  if quiet[i - 5:i + 5].all()]
    return min(candidates, key=lambda i: abs(i - 1250)) * hop if candidates else 25 * rate


@dataclass
class AudioPiece:
    offset: float
    duration: float
    channel: int | None
    samples: np.ndarray
    rate: int

    @property
    def silent(self) -> bool:
        return not np.any(self.samples)

    def upload(self) -> tuple[str, bytes, str]:
        return "meeting.wav", wav_bytes(self.samples, self.rate), "audio/wav"


class PreparedAudio:
    def __init__(self, path: Path, channel_mode: str):
        self.path = path
        self.channel_mode = channel_mode
        with wave.open(str(path), "rb") as wav:
            self.rate = wav.getframerate()
            self.channels = wav.getnchannels()
            self.frames = wav.getnframes()
            if wav.getsampwidth() != 2 or not 8000 <= self.rate <= 48000 or not 1 <= self.channels <= 2:
                raise InvalidAudio("Use mono or stereo audio between 8 and 48 kHz")
            self.duration = self.frames / self.rate
            if not self.frames or self.duration > MAX_SECONDS or path.stat().st_size >= MAX_PCM_BYTES:
                raise InvalidAudio("Audio is empty or exceeds the four-hour processing limit")

    def pieces(self):
        # Read only 28 seconds plus one frame, even for multi-hour meetings.
        with wave.open(str(self.path), "rb") as wav:
            position = 0
            while position < self.frames:
                wav.setpos(position)
                samples = np.frombuffer(wav.readframes(28 * self.rate + 1), dtype="<i2").reshape(-1, self.channels)
                if not len(samples):
                    raise InvalidAudio("Decoded audio ended before its declared duration")
                count = cut_frame(samples, self.rate)
                samples = samples[:count]
                channels = range(self.channels) if self.channel_mode == "separate" else [None]
                for channel in channels:
                    yield AudioPiece(position / self.rate, count / self.rate, channel,
                                     samples if channel is None else samples[:, channel], self.rate)
                position += count


@asynccontextmanager
async def prepare_audio(audio: bytes, channel_mode: str = "preserve"):
    if channel_mode not in {"preserve", "separate"}:
        raise ValueError("Unknown audio channel mode")
    with tempfile.TemporaryDirectory(prefix="wilco-asr-") as directory:
        source, decoded = Path(directory) / "source", Path(directory) / "decoded.wav"
        source.write_bytes(audio)
        # Decode once without resampling, downmixing, gain or another lossy
        # codec. Protocol restriction prevents uploaded playlists fetching URLs.
        await _ffmpeg(["-protocol_whitelist", "file,pipe",
                       "-format_whitelist", "wav,mp3,ogg,flac,aac,mov,matroska,webm,aiff",
                       "-i", str(source),
                       "-map", "0:a:0", "-vn", "-t", str(MAX_SECONDS + 1),
                       "-fs", str(MAX_PCM_BYTES), "-c:a", "pcm_s16le", str(decoded)])
        try:
            yield PreparedAudio(decoded, channel_mode)
        except (wave.Error, EOFError) as error:
            raise InvalidAudio("Audio could not be decoded") from error


async def enhanced_upload(piece: AudioPiece, mode: str, model_path: str = ""):
    """Opt-in enhancement, with an original-PCM fallback on local failure.

    Never triggers a second ASR request. Cancellation always propagates.
    RNNoise needs a locally provisioned FFmpeg-compatible .rnnn model.
    """
    original = piece.upload()
    if mode == "off" or piece.silent:
        return original, "off"
    if mode not in {"spectral", "rnnoise"}:
        raise ValueError("Unknown audio enhancement mode")
    try:
        with tempfile.TemporaryDirectory(prefix="wilco-enhance-") as directory:
            work = Path(directory)
            (work / "input.wav").write_bytes(original[1])
            if mode == "rnnoise":
                # A fixed local filename avoids filter-expression injection.
                shutil.copyfile(model_path, work / "model.rnnn")
                filters = f"aresample=48000,arnndn=m=model.rnnn:mix=0.65,aresample={piece.rate}"
            else:
                filters = "afftdn=nr=6:nf=-50:tn=1:gs=5"
            await _ffmpeg(["-i", "input.wav", "-af", filters,
                           "-c:a", "pcm_s16le", "output.wav"], timeout=15, cwd=directory)
            with wave.open(str(work / "output.wav"), "rb") as wav:
                if wav.getframerate() != piece.rate or wav.getnchannels() != (1 if piece.samples.ndim == 1 else piece.samples.shape[1]):
                    raise InvalidAudio("Enhancer changed the audio layout")
                enhanced = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").reshape(piece.samples.shape)
            # Catch catastrophic muting, clipping, or unexpected time changes.
            raw_rms = float(np.sqrt(np.mean(piece.samples.astype(np.float32) ** 2)))
            new_rms = float(np.sqrt(np.mean(enhanced.astype(np.float32) ** 2)))
            if new_rms < raw_rms * 0.1 or new_rms > raw_rms * 2:
                raise InvalidAudio("Enhancer changed signal level excessively")
            return ("meeting.wav", wav_bytes(enhanced, piece.rate), "audio/wav"), mode
    except (OSError, ValueError, wave.Error, EOFError, TimeoutError):
        logger.warning("Audio enhancement unavailable; using original PCM (%s)", mode)
        return original, "fallback"
