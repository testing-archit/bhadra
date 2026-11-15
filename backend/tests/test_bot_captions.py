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


def test_chat_watcher_picks_up_command_sent_before_panel_opened():
    class Page:
        async def evaluate(self, _script):
            return ["Yesterday's note", "Charcha, make a whiteboard"]

    watcher = meeting_session.meet_chat.ChatWatcher()
    assert asyncio.run(watcher.new_questions(Page())) == ["make a whiteboard"]
    assert asyncio.run(watcher.new_questions(Page())) == []


def test_chat_recovers_when_join_notice_could_not_open_panel(monkeypatch):
    class Chat:
        async def new_questions(self, _page):
            return []

    session = object.__new__(meeting_session.MeetingSession)
    session.chat_ready = False
    session.chat = Chat()
    session.captions = meeting_session.CaptionLog()
    async def open_later(_page):
        return True
    monkeypatch.setattr(meeting_session.meet_chat, "open_panel", open_later)
    monkeypatch.setattr(meeting_session.config, "ANSWER_IN_CHAT", True)
    asyncio.run(session.answer_chat(object()))
    assert session.chat_ready is True


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


def test_identical_caption_updates_do_not_restart_settling(monkeypatch):
    clock = {"now": 10.0}
    monkeypatch.setattr(meeting_session.time, "monotonic", lambda: clock["now"])
    captions = meeting_session.CaptionLog()
    batch = [{"id": 1, "speaker": "Ravi", "text": "Charcha, recap please"}]
    asyncio.run(captions.on_captions(batch))
    captions.changed.clear()
    clock["now"] = 12.0
    asyncio.run(captions.on_captions(batch))
    assert captions.latest[1][2] == 10.0
    assert not captions.changed.is_set()
    batch[0]["text"] += " now"
    asyncio.run(captions.on_captions(batch))
    assert captions.latest[1][2] == 12.0
    assert captions.changed.is_set()


def test_lifecycle_can_exit_during_a_slow_command(tmp_path, monkeypatch):
    monkeypatch.setattr(meeting_session.config, "SESSIONS_DIR", tmp_path)

    async def scenario():
        session = meeting_session.MeetingSession({"meet_url": "https://meet.google.com/abc-defg-hij"})
        started = asyncio.Event()
        cancelled = asyncio.Event()
        incoming = [meeting_session.Command("", "recap")]

        async def discover(_page):
            result = incoming[:]
            incoming.clear()
            return result

        async def execute(_page, _command):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        async def lifecycle(_page):
            await asyncio.wait_for(started.wait(), 1)
            return "asked to leave"

        session.discover_commands = discover
        session.execute_command = execute
        session._stay = lifecycle
        assert await asyncio.wait_for(session.stay(object()), 1) == "asked to leave"
        assert cancelled.is_set()
    asyncio.run(scenario())


def test_caption_commands_wait_for_revisions_and_do_not_repeat(tmp_path, monkeypatch):
    monkeypatch.setattr(meeting_session.config, "SESSIONS_DIR", tmp_path)
    clock = {"now": 10.0}
    monkeypatch.setattr(meeting_session.time, "monotonic", lambda: clock["now"])
    session = meeting_session.MeetingSession({"meet_url": "https://meet.google.com/abc-defg-hij"})
    session.captions.latest[1] = ("Ravi", "Charcha, recap please", 9.0)
    assert session.spoken_questions() == []
    session.captions.latest[1] = ("Ravi", "Charcha, recap the pricing discussion", 10.0)
    clock["now"] = 12.6
    assert session.spoken_questions() == [("Ravi", "recap the pricing discussion")]
    assert session.spoken_questions() == []


def test_shutdown_terminates_playback_and_removes_audio(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(meeting_session.config, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(meeting_session.config, "SPEAK_IN_CALL", True)
    monkeypatch.setattr(meeting_session.uploader, "speech", lambda _text: b"audio")

    async def scenario():
        started = asyncio.Event()
        class Process:
            returncode = None
            terminated = False

            async def wait(self):
                started.set()
                if not self.terminated:
                    await asyncio.Event().wait()
                self.returncode = -15
                return self.returncode

            def terminate(self):
                self.terminated = True

        process = Process()
        async def spawn(*_args, **_kwargs):
            return process

        async def click(*_args, **_kwargs):
            return True

        monkeypatch.setattr(meeting_session.asyncio, "create_subprocess_exec", spawn)
        monkeypatch.setattr(meeting_session, "_click_if_visible", click)
        session = meeting_session.MeetingSession({"meet_url": "https://meet.google.com/abc-defg-hij"})
        session.voice_modules = ["test"]
        page = type("Page", (), {"evaluate": AsyncMock(), "wait_for_timeout": AsyncMock(), "is_closed": lambda self: False})()
        task = asyncio.create_task(session.speak(page, "hello"))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert process.terminated
        assert not list(session.dir.glob("speech_*.mp3"))
        page.evaluate.assert_any_await("window.__charchaSpeaking = false")
    asyncio.run(scenario())


def test_wilco_wake_name_and_exit_work_alongside_legacy_name(tmp_path, monkeypatch):
    monkeypatch.setattr(meeting_session.config, 'SESSIONS_DIR', tmp_path)
    session = meeting_session.MeetingSession({'meet_url': 'https://meet.google.com/abc-defg-hij'})
    session.captions.latest[1] = ('Ravi', 'Wilco, open a whiteboard', meeting_session.time.monotonic() - 3)
    assert session.spoken_questions() == [('Ravi', 'open a whiteboard')]
    assert meeting_session.wants_exit('Wilco please leave')


def test_stop_speaking_bypasses_settling_but_edits_do_not(tmp_path,monkeypatch):
    monkeypatch.setattr(meeting_session.config,'SESSIONS_DIR',tmp_path)
    session=meeting_session.MeetingSession({'meet_url':'https://meet.google.com/abc-defg-hij'})
    now=meeting_session.time.monotonic()
    session.captions.latest[1]=('Ravi','Wilco, stop speaking',now)
    session.captions.latest[2]=('Ravi','Wilco, delete that point',now)
    assert session.spoken_questions()==[('Ravi','stop speaking')]


def test_stop_presenting_is_a_priority_control(tmp_path,monkeypatch):
    monkeypatch.setattr(meeting_session.config,'SESSIONS_DIR',tmp_path)
    session=meeting_session.MeetingSession({'meet_url':'https://meet.google.com/abc-defg-hij'})
    session.captions.latest[1]=('Ravi','Wilco, stop presenting',meeting_session.time.monotonic())
    assert session.spoken_questions()==[('Ravi','stop presenting')]


def test_unsupported_mutations_use_action_planner_instead_of_answer_tool(tmp_path,monkeypatch):
    monkeypatch.setattr(meeting_session.config,'SESSIONS_DIR',tmp_path)
    session=meeting_session.MeetingSession({'capture_request_id':'00000000-0000-0000-0000-000000000001'})
    tools=[]
    async def submit(page,command,tool):
        tools.append(tool)
    session.submit_agent_command=submit
    asyncio.run(session.execute_command(object(),meeting_session.Command('','Can you please mark Ravi’s task done?')))
    assert tools==['auto']
