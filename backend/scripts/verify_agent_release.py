"""Production release smoke check. Uses and removes only its own synthetic records.

The optional model canary makes one synthetic board-generation request. No real
meeting is joined, no audio is sent, and no Jira/email action is requested.
"""
import argparse
import asyncio
import datetime as dt
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from httpx import AsyncClient, TransportError
from sqlalchemy import select, text
from app.config import settings
from app.database.db import async_session
from app.database.models import CaptureRequest, MeetingAgentJob, MeetingBoard, User


async def verify_voice():
    """Exercise Gnani -> fast model -> Gnani with synthetic speech only."""
    from app.services import live_conversation, transcriber, tts_service, usage_ledger
    if not settings.gnani_api_key:
        raise RuntimeError('Gnani voice is not configured')
    report = {'speech_provider': 'gnani', 'reply_model': settings.gemini_fast_model}
    started = time.perf_counter()
    async with asyncio.timeout(12):
        clip = await tts_service.synthesize('Hello Wilco. Are you ready for the meeting?', 'en-IN')
    report['input_tts_ms'] = round((time.perf_counter()-started)*1000, 2)
    started = time.perf_counter()
    async with asyncio.timeout(12):
        heard = await transcriber.transcribe_audio_detailed(clip, 'audio/mpeg', 'en', timeout_seconds=8, interactive=True)
    text_heard = ' '.join(turn['text'] for turn in heard['turns']).strip()
    assert text_heard, 'Synthetic speech was not transcribed'
    report['stt_ms'] = round((time.perf_counter()-started)*1000, 2)
    started = time.perf_counter()
    # This standalone probe can use the synchronous wrapper directly, so all
    # paid usage is scheduled on this running loop and flushed below.
    answer = live_conversation.reply([], text_heard, 'No meetings yet.', 'Release check', 'en-IN')
    assert answer, 'Voice reply was empty'
    report['reply_ms'] = round((time.perf_counter()-started)*1000, 2)
    started = time.perf_counter()
    async with asyncio.timeout(10):
        spoken = await tts_service.synthesize(answer, 'en-IN')
    assert len(spoken) > 100, 'Speech audio was empty'
    report.update(tts_ms=round((time.perf_counter()-started)*1000, 2),
                  speech_model=tts_service.voice_for('en-IN')[0], speech_voice=tts_service.voice_for('en-IN')[1])
    report['pipeline_ms'] = round(report['stt_ms']+report['reply_ms']+report['tts_ms'], 2)
    pending = list(usage_ledger._pending)
    if pending:
        await asyncio.gather(*pending)
    return report


async def verify(args):
    if not settings.bot_api_secret:
        raise RuntimeError('Bot authentication is not configured')
    report = {'model_canary_requested': args.model_canary}
    # Container startup runs schema initialization before Uvicorn binds its port.
    # A started container is not proof that its HTTP listener is ready.
    async with AsyncClient(base_url=args.base_url, timeout=5) as client:
        async with asyncio.timeout(90):
            while True:
                try:
                    if (await client.get('/health')).status_code == 200:
                        break
                except TransportError:
                    pass
                await asyncio.sleep(1)
    report['http_ready'] = True
    async with async_session() as db:
        report['agent_table'] = bool(await db.scalar(text("SELECT to_regclass('public.meeting_agent_jobs') IS NOT NULL")))
        report['running_job_index'] = bool(await db.scalar(text("SELECT to_regclass('public.uq_agent_running_capture') IS NOT NULL")))
    assert report['agent_table'] and report['running_job_index']
    identifier = uuid.uuid4()
    user_id = capture_id = None
    try:
        async with async_session() as db:
            user = User(email=f'release-check-{identifier}@example.invalid', name='Synthetic release check', status='inactive')
            db.add(user); await db.flush(); user_id=user.id
            capture = CaptureRequest(user_id=user.id, platform='google_meet',
                meeting_url='https://meet.google.com/aaa-bbbb-ccc', meeting_code=f'release-check-{identifier}',
                title='Synthetic release check', status='capturing', consent_acknowledged_at=dt.datetime.now(dt.UTC))
            db.add(capture); await db.flush(); capture_id=capture.id; await db.commit()
        headers={'Authorization':f'Bot {settings.bot_api_secret}'}
        async with AsyncClient(base_url=args.base_url, timeout=10) as client:
            assert (await client.get('/health')).status_code == 200
            url=f'/api/bot/capture-requests/{capture_id}/commands'
            assert (await client.get(url)).status_code == 401
            started=time.perf_counter()
            result=await client.post(url,headers=headers,json={
                'command_id':str(identifier),
                'command':'Add exactly one idea named Release check to the board.' if args.model_canary else 'Open the meeting board.',
                'tool':'edit_board' if args.model_canary else 'open_board',
            })
            assert result.status_code == 202, f'Admission status {result.status_code}'
            report['admission_ms']=round((time.perf_counter()-started)*1000,2)
            async with asyncio.timeout(settings.meeting_agent_timeout_seconds+5):
                while True:
                    response=await client.get(url+f'/{identifier}',headers=headers)
                    assert response.status_code==200
                    state=response.json()
                    if state['state'] in {'succeeded','failed','cancelled','needs_input'}:
                        report['agent_state']=state['state']; report['phase']=state['phase']
                        assert state['state']=='succeeded',f"Agent state {state['state']} in phase {state['phase']}"
                        break
                    await asyncio.sleep(.25)
            report['completion_ms']=round((time.perf_counter()-started)*1000,2)
            async with async_session() as db:
                job=await db.get(MeetingAgentJob,uuid.UUID(state['id']))
                assert job.receipts
                board=await db.scalar(select(MeetingBoard).where(MeetingBoard.capture_request_id==capture_id))
                assert board is not None
                if args.model_canary:
                    assert any(node.get('title','').strip().lower()=='release check' for node in board.nodes)
            assert (await client.post(url+f'/{identifier}/delivered',headers=headers)).status_code==200
            report['authenticated_api_and_delivery']='ok'
    finally:
        async with async_session() as db:
            if capture_id:
                capture=await db.get(CaptureRequest,capture_id)
                if capture:
                    await db.delete(capture)
            if user_id:
                user=await db.get(User,user_id)
                if user:
                    await db.delete(user)
            await db.commit()
    report['synthetic_records_removed']=True
    if args.voice_canary:
        report['synthetic_voice_canary'] = await verify_voice()
    print(json.dumps(report,sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8080')
    parser.add_argument('--model-canary',action='store_true')
    parser.add_argument('--voice-canary',action='store_true')
    try:
        asyncio.run(verify(parser.parse_args()))
    except Exception as error:
        # Never emit connection strings, API keys, or provider response bodies.
        print('Agent release smoke failed:',type(error).__name__)
        if isinstance(error, AssertionError):
            print(str(error)[:200])
        sys.exit(1)
