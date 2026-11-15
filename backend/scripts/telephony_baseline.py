"""Frozen pre-improvement audio preparation from d184828, benchmark only."""
import asyncio
import logging
import os
import subprocess
import tempfile
logger = logging.getLogger(__name__)

# Prisma accepts only these containers (UNSUPPORTED_AUDIO_FORMAT otherwise).
# Everything Wilco records is WebM (Opus), so it is repackaged as Ogg:
# the same Opus audio in a container Prisma takes, copied, not re-encoded.
_SUPPORTED_UPLOADS = {
    "audio/ogg": "ogg", "audio/opus": "ogg", "audio/mpeg": "mp3", "audio/mp3": "mp3",
    "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/flac": "flac",
    "audio/x-flac": "flac", "audio/aac": "aac", "audio/mp4": "m4a", "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
}
_CONVERT_TIMEOUT_SECONDS = 300


def _ffmpeg_to_ogg(audio_bytes: bytes, reencode: bool) -> bytes:
    codec = ["-c:a", "libopus", "-b:a", "48k", "-ac", "1"] if reencode else ["-c:a", "copy"]
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", "pipe:0", "-vn", *codec, "-f", "ogg", "pipe:1"],
        input=audio_bytes, capture_output=True, timeout=_CONVERT_TIMEOUT_SECONDS, check=True,
    )
    if not result.stdout:
        raise RuntimeError("ffmpeg produced no audio")
    return result.stdout


_CHUNK_SECONDS = 25.0
_MAX_SINGLE_SECONDS = 28.0

def _probe_seconds(path: str) -> float | None:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=60, check=True,
        )
        return float(result.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _segment_to_ogg(path: str, out_dir: str) -> list[str]:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "libopus", "-b:a", "32k", "-f", "segment", "-segment_time", str(_CHUNK_SECONDS),
         "-reset_timestamps", "1", os.path.join(out_dir, "chunk_%04d.ogg")],
        capture_output=True, timeout=_CONVERT_TIMEOUT_SECONDS, check=True,
    )
    return sorted(os.path.join(out_dir, name) for name in os.listdir(out_dir) if name.startswith("chunk_"))


async def _split_for_prisma(audio_bytes: bytes, mime_type: str) -> list[tuple[float, float, tuple[str, bytes, str]]]:
    """(offset seconds, length seconds, upload) pieces of at most ~25 s each.
    Audio ffprobe can't read, or that is short enough, goes up whole."""
    with tempfile.TemporaryDirectory(prefix="prisma-") as work:
        source = os.path.join(work, "source")
        with open(source, "wb") as handle:
            handle.write(audio_bytes)
        seconds = await asyncio.to_thread(_probe_seconds, source)
        if seconds is None or seconds <= _MAX_SINGLE_SECONDS:
            return [(0.0, seconds or 0.0, await _prisma_upload(audio_bytes, mime_type))]
        files = await asyncio.to_thread(_segment_to_ogg, source, work)
        pieces = []
        for index, path in enumerate(files):
            offset = index * _CHUNK_SECONDS
            with open(path, "rb") as handle:
                pieces.append((offset, min(_CHUNK_SECONDS, max(seconds - offset, 0.0)), (f"meeting_{index:04d}.ogg", handle.read(), "audio/ogg")))
        logger.info("Split %.0f s of audio into %d Prisma chunks", seconds, len(pieces))
        return pieces


async def _prisma_upload(audio_bytes: bytes, mime_type: str) -> tuple[str, bytes, str]:
    """(filename, bytes, content type) in a container Prisma accepts. WebM and
    anything unknown become Ogg: a stream copy first (milliseconds, lossless),
    then a re-encode to Opus if the codec can't go into Ogg as-is. If ffmpeg
    can't read the audio at all, the original is sent and Prisma's own error
    explains the problem."""
    base = (mime_type or "").split(";")[0].strip().lower()
    extension = _SUPPORTED_UPLOADS.get(base)
    if extension:
        return f"meeting.{extension}", audio_bytes, base
    for reencode in (False, True):
        try:
            converted = await asyncio.to_thread(_ffmpeg_to_ogg, audio_bytes, reencode)
            return "meeting.ogg", converted, "audio/ogg"
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            logger.info("Converting %s audio to Ogg (reencode=%s) failed: %s", base or "unknown", reencode, error)
    logger.warning("Sending %s audio to Prisma unconverted", base or "unknown")
    return "meeting.webm", audio_bytes, mime_type or "audio/webm"
