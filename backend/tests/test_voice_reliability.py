import pytest
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


async def test_cancel_reports_once_and_marks_the_cancelled_job_delivered(tmp_path, monkeypatch):
    monkeypatch.setattr(meeting_session.config, 'SESSIONS_DIR', tmp_path)
    session = meeting_session.MeetingSession({'capture_request_id': 'test'})
    sent = []
    async def send(page, message):
        sent.append(message)
        return True
    session.send_agent_message = send
    job = '11111111-1111-1111-1111-111111111111'
    session._pending_commands[job] = meeting_session.Command('', 'draw the flow', id=job)
    agent = AsyncMock()
    agent.cancel.return_value = {'command_id': job, 'state': 'cancelled'}
    session._agent = agent
    assert await session.handle_control(None, meeting_session.Command('', 'cancel that'))
    assert sent == ['Stopped the request. Completed changes were kept.']
    agent.delivered.assert_awaited_once_with(job)
    assert job not in session._pending_commands


@pytest.mark.parametrize('text,language', [
    ('முக்கிய முடிவுகள்: விலை மாற்றம் இல்லை.', 'ta-IN'),
    ('ముఖ్య నిర్ణయాలు ఇవి.', 'te-IN'),
    ('ಮುಖ್ಯ ನಿರ್ಧಾರಗಳು.', 'kn-IN'),
    ('പ്രധാന തീരുമാനങ്ങൾ.', 'ml-IN'),
    ('মূল সিদ্ধান্ত: দাম একই থাকবে।', 'bn-IN'),
    ('મુખ્ય નિર્ણયો.', 'gu-IN'),
    ('ਮੁੱਖ ਫੈਸਲੇ.', 'pa-IN'),
    ('किंमत बदलणार नाही आणि लॉन्च शुक्रवारी आहे.', 'mr-IN'),
    ('कीमत नहीं बदलेगी, लॉन्च शुक्रवार को है.', 'hi-en'),
    ('Recap: Vedant ships the flow by Friday.', 'en-IN'),
])
def test_spoken_language_follows_the_script_of_the_answer(text, language):
    assert tts_service.language_for_text(text) == language


def test_off_the_record_words_never_leave_the_bot(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(meeting_session.time, 'monotonic', lambda: clock[0])
    log = meeting_session.CaptionLog()
    log.audio_started_at = 100.0
    async def say(text, at, block=1):
        clock[0] = at
        await log.on_captions([{'id': block, 'speaker': 'Ravi', 'text': text}])
    asyncio.run(say('launch is Friday', 101))
    clock[0] = 105
    assert log.pause()
    asyncio.run(say('salary of Asha is twelve lakh', 106, block=2))
    clock[0] = 110
    assert log.resume()
    asyncio.run(say('next we review pricing', 112, block=3))
    text = ' '.join(item['text'] for item in log.export())
    assert 'launch is Friday' in text and 'next we review pricing' in text
    assert 'salary' not in text and 'lakh' not in text


async def test_spoken_pause_mutes_the_recording_and_resume_unmutes(tmp_path, monkeypatch):
    monkeypatch.setattr(meeting_session.config, 'SESSIONS_DIR', tmp_path)
    calls = []
    monkeypatch.setattr(meeting_session, '_pactl', lambda *args: calls.append(args) or '')
    session = meeting_session.MeetingSession({'capture_request_id': 'test'})
    sent = []
    async def send(page, message):
        sent.append(message)
        return True
    session.send_agent_message = send
    assert await session.handle_control(None, meeting_session.Command('', 'pause recording'))
    assert session.captions.paused and calls[-1] == ('set-sink-mute', session.sink, '1')
    assert sent[-1].startswith('Paused.')
    assert await session.handle_control(None, meeting_session.Command('', 'pause'))
    assert sent[-1].startswith("I'm already paused")
    assert await session.handle_control(None, meeting_session.Command('', 'resume'))
    assert not session.captions.paused and calls[-1] == ('set-sink-mute', session.sink, '0')
    assert sent[-1].startswith('Recording again')


async def test_voice_updates_are_announced_as_ai_then_played_and_marked(tmp_path, monkeypatch):
    monkeypatch.setattr(meeting_session.config, 'SESSIONS_DIR', tmp_path)
    monkeypatch.setattr(meeting_session.config, 'SPEAK_IN_CALL', True)
    session = meeting_session.MeetingSession({'capture_request_id': 'cap'})
    session.USES_GOOGLE_LOGIN = True
    order = []
    monkeypatch.setattr(meeting_session.uploader, 'voice_updates', lambda cid: [{'id': 'u1', 'name': 'Vedant', 'text': 'KYC is blocked.'}])
    monkeypatch.setattr(meeting_session.uploader, 'voice_update_audio', lambda cid, uid: b'ID3clone')
    monkeypatch.setattr(meeting_session.uploader, 'voice_update_delivered', lambda cid, uid: order.append(('delivered', uid)))
    async def speak(page, text):
        order.append(('speak', text))
    async def play(page, audio, max_seconds=46):
        order.append(('play', audio))
    async def send(page, message):
        order.append(('chat', message))
        return True
    session.speak, session.play_browser_audio, session.send_agent_message = speak, play, send
    assert await session.handle_control(None, meeting_session.Command('', 'play updates'))
    await session._voice_update_task
    assert order[0] == ('speak', "Here's an update from Vedant, read in an AI copy of their voice.")
    assert order[1] == ('play', b'ID3clone')
    assert order[2][0] == 'chat' and 'AI copy' in order[2][1] and 'KYC is blocked.' in order[2][1]
    assert order[3] == ('delivered', 'u1')


def test_standin_questions_are_recognised_in_english_and_hinglish():
    assert meeting_session.standin_question("ask Vedant, is KYC done") == ("Vedant", "is KYC done")
    assert meeting_session.standin_question("Vedant se poocho KYC kab tak hoga") == ("Vedant", "KYC kab tak hoga")
    assert meeting_session.standin_question("what did we decide") is None


async def test_standin_answer_is_labelled_ai_and_spoken_in_the_cloned_voice(tmp_path, monkeypatch):
    monkeypatch.setattr(meeting_session.config, 'SESSIONS_DIR', tmp_path)
    monkeypatch.setattr(meeting_session.config, 'SPEAK_IN_CALL', True)
    session = meeting_session.MeetingSession({'capture_request_id': 'cap'})
    session.USES_GOOGLE_LOGIN = True
    events = []
    monkeypatch.setattr(meeting_session.uploader, 'standins', lambda cid: [{'id': 's1', 'name': 'Vedant Moghe'}])
    monkeypatch.setattr(meeting_session.uploader, 'ask_standin', lambda *a: {'answer': 'Waiting on sandbox keys.', 'known': True, 'audio': 'SUQz'})
    async def send(page, message):
        events.append(('chat', message)); return True
    async def speak(page, text):
        events.append(('speak', text))
    async def play(page, audio, max_seconds=46):
        events.append(('play', audio))
    session.send_agent_message, session.speak, session.play_browser_audio = send, speak, play
    assert await session.execute_command(None, meeting_session.Command('asked aloud by Ravi', 'ask Vedant, is KYC done')) is None
    assert events[0][0] == 'chat' and "AI stand-in (AI voice, not Vedant live)" in events[0][1]
    assert events[1] == ('speak', "Vedant's AI stand-in will answer, in an AI copy of Vedant's voice.")
    assert events[2] == ('play', b'ID3')
