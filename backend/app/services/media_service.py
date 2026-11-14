"""Inspecting and normalizing uploaded meeting media.

An upload is judged by what ffprobe decodes from its bytes — never by its
file extension or the browser's content type — and every ffmpeg/ffprobe call
runs with an argument array (no shell), a timeout, and a bounded output.
"""

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

PROBE_TIMEOUT_SECONDS = 60
NORMALIZE_TIMEOUT_SECONDS = 1800

# ffprobe `format_name` values we accept, mapped to what the file is. These
# are the containers Prisma decodes for MP3, WAV, M4A, MP4 and WebM.
ACCEPTED_FORMATS = {
    "mp3": "mp3",
    "wav": "wav",
    "mov,mp4,m4a,3gp,3g2,mj2": "mp4",
    "matroska,webm": "webm",
    "ogg": "ogg",
}
SUPPORTED_LABEL = "MP3, WAV, M4A, MP4 or WebM"


class MediaRejected(ValueError):
    """The file is not usable meeting media; the message is user-facing."""


@dataclass
class MediaInfo:
    container: str
    duration_seconds: float | None
    has_audio: bool
    has_video: bool
    audio_codec: str | None


def tools_available() -> bool:
    return shutil.which("ffprobe") is not None and shutil.which("ffmpeg") is not None


def probe(path: Path) -> MediaInfo:
    if shutil.which("ffprobe") is None:
        raise MediaRejected("Media inspection is unavailable on this server (ffprobe is not installed)")
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", str(path),
            ],
            capture_output=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise MediaRejected("The file took too long to inspect") from error
    if result.returncode != 0:
        raise MediaRejected(f"This file could not be decoded as audio or video. Supported: {SUPPORTED_LABEL}")
    try:
        payload = json.loads(result.stdout[:2_000_000] or b"{}")
    except ValueError as error:
        raise MediaRejected("This file could not be inspected") from error

    format_name = (payload.get("format") or {}).get("format_name") or ""
    container = ACCEPTED_FORMATS.get(format_name)
    if container is None:
        raise MediaRejected(f"Unsupported media format ({format_name or 'unknown'}). Supported: {SUPPORTED_LABEL}")
    streams = payload.get("streams") or []
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    video = [s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")]
    if not audio:
        raise MediaRejected("This file has no audio track, so there is nothing to transcribe")
    raw_duration = (payload.get("format") or {}).get("duration")
    try:
        duration = float(raw_duration) if raw_duration not in (None, "N/A") else None
    except ValueError:
        duration = None
    return MediaInfo(
        container=container,
        duration_seconds=duration,
        has_audio=True,
        has_video=bool(video),
        audio_codec=audio[0].get("codec_name"),
    )


def extract_audio(source: Path, output: Path) -> None:
    """Re-encode the audio track to mono Opus/WebM — small to store, plays in
    every browser, and decodes cleanly for transcription. Drops any video."""
    try:
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source),
                "-vn", "-ac", "1", "-ar", "48000", "-c:a", "libopus", "-b:a", "48k",
                str(output),
            ],
            capture_output=True,
            timeout=NORMALIZE_TIMEOUT_SECONDS,
            check=True,
        )
    except subprocess.TimeoutExpired as error:
        raise MediaRejected("Converting the recording took too long") from error
    except subprocess.CalledProcessError as error:
        raise MediaRejected("The recording's audio could not be converted") from error
