"""The notetaker's caption log (backend/bot/meeting_session.py)."""

import asyncio
import sys
import types
from pathlib import Path

if "playwright.async_api" not in sys.modules:
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:  # the bot's browser isn't needed to test its caption log
        stub = types.ModuleType("playwright.async_api")
        stub.BrowserContext = stub.Page = object
        stub.async_playwright = None
        sys.modules.setdefault("playwright", types.ModuleType("playwright"))
        sys.modules["playwright.async_api"] = stub

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))
import meeting_session  # noqa: E402

sys.path.pop(0)


def _feed(log, updates):
    """updates: (seconds since audio start, [(block id, speaker, visible text)])."""
    clock = {"now": 0.0}
    log._now = lambda: clock["now"]
    for at, batch in updates:
        clock["now"] = at
        asyncio.run(log.on_captions([{"id": i, "speaker": s, "text": t} for i, s, t in batch]))
    return log.export()


def test_words_scrolled_off_a_long_block_are_kept_with_their_own_times():
    # Production, 2026-10-12: Meet shows only a block's last lines, so a 60 s
    # block was stored as "Good morning." and the speaker matcher had nothing.
    captions = _feed(meeting_session.CaptionLog(), [
        (10, [(1, "Ravi", "Good morning everyone")]),
        (11, [(1, "Ravi", "Good morning everyone lets start with")]),
        (12, [(1, "Ravi", "everyone lets start with the release plan")]),
        (30, [(1, "Ravi", "the release plan. Astha can you take the")]),
        (31, [(1, "Ravi", "Astha can you take the testflight build")]),
    ])
    assert captions == [
        {"speaker": "Ravi", "text": "Good morning everyone lets start with the release plan.", "start": 10, "end": 12},
        {"speaker": "Ravi", "text": "Astha can you take the testflight build", "start": 30, "end": 31},
    ]


def test_revised_words_keep_their_time_and_blocks_interleave():
    captions = _feed(meeting_session.CaptionLog(), [
        (5, [(1, "Asha", "upload the a p k"), (2, "Ravi", "sure")]),
        (6, [(1, "Asha", "upload the APK tonight")]),
        (20, [(2, "Ravi", "sure I will check staging")]),
    ])
    assert [(c["speaker"], c["text"], c["start"]) for c in captions] == [
        ("Asha", "upload the APK tonight", 5),
        ("Ravi", "sure", 5),
        ("Ravi", "I will check staging", 20),
    ]


# --- Teams links in the session ------------------------------------------------------

TEAMS_JOIN = "https://teams.microsoft.com/l/meetup-join/19%3Ameeting_x%40thread.v2/0?context=%7B%22Tid%22%3A%22a%22%7D"


def test_the_link_picks_the_session(tmp_path, monkeypatch):
    monkeypatch.setattr(meeting_session.config, "SESSIONS_DIR", tmp_path)
    assert type(meeting_session.session_for({"meet_url": "https://meet.google.com/abc-defg-hij"})) is meeting_session.MeetingSession
    teams = meeting_session.session_for({"meet_url": TEAMS_JOIN})
    assert isinstance(teams, meeting_session.TeamsSession)
    # auth.json is a Google login: Teams neither gets it nor rewrites it.
    assert teams.USES_GOOGLE_LOGIN is False


def test_a_teams_url_cant_break_the_log_format():
    label = meeting_session.log_label({"meet_url": TEAMS_JOIN})
    assert "%" not in label and "{" not in label
    assert meeting_session.log_label({"meet_url": TEAMS_JOIN, "meeting_code": "teams-123"}) == "teams-123"
    assert meeting_session.log_label({"meet_url": "https://meet.google.com/abc-defg-hij"}) == "abc-defg-hij"


def test_passcodes_stay_out_of_logs():
    assert meeting_session.teams_dom.loggable_url("https://teams.live.com/meet/123?p=secret") == "https://teams.live.com/meet/123"


def test_the_logo_camera_is_opt_in_and_needs_its_image(tmp_path, monkeypatch):
    config = meeting_session.config
    monkeypatch.setattr(config, "SESSIONS_DIR", tmp_path)
    image = tmp_path / "logo.png"
    monkeypatch.setattr(config, "TEAMS_LOGO_IMAGE", image)
    image.touch()
    teams = {"meet_url": TEAMS_JOIN}

    monkeypatch.setattr(config, "TEAMS_LOGO_CAMERA", False)
    assert meeting_session.session_for(teams).logo_camera is False

    monkeypatch.setattr(config, "TEAMS_LOGO_CAMERA", True)
    session = meeting_session.session_for(teams)
    assert session.logo_camera is True
    # Meet never gets it: there the Google profile picture does this job.
    assert not hasattr(meeting_session.session_for({"meet_url": "https://meet.google.com/abc-defg-hij"}), "logo_camera")

    image.unlink()
    assert meeting_session.session_for(teams).logo_camera is False
