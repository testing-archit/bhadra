import asyncio
from unittest.mock import AsyncMock

from app.services.speech_admission import SpeechAdmission
from app.services import tts_service
from tests.test_bot_captions import meeting_session


async def test_live_speech_gets_the_next_slot_before_another_batch_chunk():
    gate = SpeechAdmission()
    order = []
    first_ready, release = asyncio.Event(), asyncio.Event()
    async def first():
        async with gate.slot():
            first_ready.set(); await release.wait()
    async def waiting(name, live=False):
        async with gate.slot(live): order.append(name)
    current = asyncio.create_task(first())
    await first_ready.wait()
    batch = asyncio.create_task(waiting('batch'))
    await asyncio.sleep(0)
    live = asyncio.create_task(waiting('live', True))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(current, batch, live)
    assert order == ['live', 'batch']


def test_second_wake_word_in_one_unpunctuated_caption_is_not_lost(tmp_path, monkeypatch):
    monkeypatch.setattr(meeting_session.config, 'SESSIONS_DIR', tmp_path)
    monkeypatch.setattr(meeting_session.time, 'monotonic', lambda: 10)
    session = meeting_session.MeetingSession({})
    session.captions.latest[1] = ('Ravi', 'Wilco open the whiteboard Wilco draw signup and payment', 8)
    assert session.spoken_questions() == [('Ravi', 'open the whiteboard'), ('Ravi', 'draw signup and payment')]
    assert session.spoken_questions() == []


async def test_open_and_draw_keeps_the_instruction_and_skips_the_extra_planner(tmp_path, monkeypatch):
    monkeypatch.setattr(meeting_session.config, 'SESSIONS_DIR', tmp_path)
    session = meeting_session.MeetingSession({'capture_request_id':'test'})
    session.submit_agent_command = AsyncMock()
    command = meeting_session.Command('', 'Open a whiteboard and draw signup, payment and activation')
    await session.execute_command(object(), command)
    assert session.submit_agent_command.await_args.args[-1] == 'edit_board'
    assert 'draw signup' in session.submit_agent_command.await_args.args[1].question


def test_speech_never_reads_a_board_url_or_opaque_identifier():
    result = meeting_session.spoken_summary('Updated the board: https://example.com/meetings/550e8400-e29b-41d4-a716-446655440000')
    assert result == 'Updated the board:'
    assert tts_service.language_for_text('Added the signup flow.') == 'en-IN'
    assert tts_service.language_for_text('Theek hai, flow bana diya.') == 'hi-en'


async def test_browser_playback_cancellation_stops_the_isolated_microphone(tmp_path, monkeypatch):
    monkeypatch.setattr(meeting_session.config, 'SESSIONS_DIR', tmp_path)
    monkeypatch.setattr(meeting_session.config, 'SPEAK_IN_CALL', True)
    monkeypatch.setattr(meeting_session.uploader, 'speech', lambda text: b'synthetic')
    ready = asyncio.Event()
    class Control:
        first = None
        def __init__(self): self.first = self
        async def is_visible(self): return True
        async def click(self, **kwargs): pass
    class Page:
        def __init__(self): self.calls = []
        async def evaluate(self, code, *args): self.calls.append(code); return True
        def locator(self, *args): return Control()
        async def wait_for_function(self, *args, **kwargs): ready.set(); await asyncio.Event().wait()
        def is_closed(self): return False
    page = Page()
    session = meeting_session.MeetingSession({})
    task = asyncio.create_task(session.speak(page, 'Hello team.'))
    await asyncio.wait_for(ready.wait(), 1)
    task.cancel(); await asyncio.gather(task, return_exceptions=True)
    assert 'window.__wilcoMic?.stop()' in page.calls


def test_command_is_not_repeated_when_meet_trims_the_caption_block(tmp_path, monkeypatch):
    monkeypatch.setattr(meeting_session.config, 'SESSIONS_DIR', tmp_path)
    monkeypatch.setattr(meeting_session.time, 'monotonic', lambda: 10)
    session = meeting_session.MeetingSession({})
    session.captions.latest[1] = ('Ravi', 'so as I said Wilco draw signup and payment', 8)
    assert session.spoken_questions() == [('Ravi', 'draw signup and payment')]
    # Meet scrolls the start of a long block away: the offset changes, the words don't.
    session.captions.latest[1] = ('Ravi', 'said Wilco draw signup and payment', 8)
    assert session.spoken_questions() == []
    # The same request continuing after a pause is not a second command.
    session.captions.latest[1] = ('Ravi', 'said Wilco draw signup and payment flow', 8)
    assert session.spoken_questions() == []
