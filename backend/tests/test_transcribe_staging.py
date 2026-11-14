from pathlib import Path

from app.config import settings
from app.routes.transcribe import _stage_chunk_for_later_assembly


def _staging_dir(client_meeting_id: str) -> Path:
    return Path(settings.recordings_dir).resolve() / "meeting_audio_staging" / client_meeting_id


def test_stages_a_valid_chunk_to_disk():
    client_meeting_id = "pytest_meeting_123_4"
    try:
        _stage_chunk_for_later_assembly(client_meeting_id, 2, "tab", b"fake-audio-bytes")
        expected = _staging_dir(client_meeting_id) / "000002_tab.webm"
        assert expected.exists()
        assert expected.read_bytes() == b"fake-audio-bytes"
    finally:
        import shutil
        shutil.rmtree(_staging_dir(client_meeting_id), ignore_errors=True)


def test_rejects_path_traversal_in_client_meeting_id():
    malicious_id = "../../etc"
    _stage_chunk_for_later_assembly(malicious_id, 0, "tab", b"data")
    # Nothing should be written anywhere reachable via that id — the regex
    # requires [A-Za-z0-9_] only, so a traversal string is silently ignored.
    assert not _staging_dir(malicious_id).exists()


def test_rejects_invalid_speaker_label():
    client_meeting_id = "pytest_meeting_invalid_label"
    try:
        _stage_chunk_for_later_assembly(client_meeting_id, 0, "../evil", b"data")
        assert not _staging_dir(client_meeting_id).exists()
    finally:
        import shutil
        shutil.rmtree(_staging_dir(client_meeting_id), ignore_errors=True)


def test_missing_fields_are_silently_ignored():
    # Best-effort persistence must never raise — a missing field just means
    # this particular call (e.g. from an older extension build) skips staging.
    _stage_chunk_for_later_assembly(None, 0, "tab", b"data")
    _stage_chunk_for_later_assembly("pytest_meeting_x", None, "tab", b"data")
    _stage_chunk_for_later_assembly("pytest_meeting_x", 0, None, b"data")
