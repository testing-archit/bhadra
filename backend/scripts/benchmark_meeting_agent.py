"""Measure queue/admission overhead on LOCAL test Postgres, with simulated inference.

This is a workflow load test, not an LLM quality evaluation or production benchmark.
No meeting, model, email, or Jira call is made. The actual durable queue is used.
"""
import argparse
import asyncio
import datetime as dt
import json
import math
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from app.config import settings
from app.database.db import async_session
from app.database.models import User, CaptureRequest, MeetingAgentJob
from app.main import app
from app.services import meeting_agent as agent


def percentile(values, fraction):
    values=sorted(values)
    return round(values[max(0, math.ceil(len(values)*fraction)-1)],2)


async def main(args):
    parsed=urlparse(settings.database_url)
    if parsed.hostname not in {'127.0.0.1','localhost'} or not parsed.path.endswith('_test'):
        raise SystemExit('Use a local database whose name ends in _test.')
    if args.requests < 1 or args.sessions < 1 or args.provider_ms < 0:
        raise SystemExit('Use positive request/session counts and a nonnegative provider delay.')
    if args.requests>settings.meeting_agent_queue_global or math.ceil(args.requests/args.sessions)>settings.meeting_agent_queue_per_capture:
        raise SystemExit('Requested load exceeds the configured admission budget.')
    identifier=uuid.uuid4()
    captures=[]; started={}; admission=[]; completion=[]; peak=0
    settings.bot_api_secret='local-synthetic-benchmark'
    async with async_session() as db:
        user=User(email=f'agent-bench-{identifier}@example.com',name='Synthetic benchmark')
        db.add(user); await db.flush(); user_id=user.id
        for index in range(args.sessions):
            capture=CaptureRequest(user_id=user_id,platform='google_meet',meeting_url='https://meet.google.com/aaa-bbbb-ccc',
                meeting_code=f'bench-{identifier}-{index}',title='Synthetic benchmark',status='capturing',consent_acknowledged_at=dt.datetime.now(dt.UTC))
            db.add(capture); await db.flush(); captures.append(capture.id)
        await db.commit()
    active=0
    async def simulated_provider(fn,*a,**kw):
        nonlocal active,peak
        active+=1; peak=max(peak,active)
        try:
            await asyncio.sleep(args.provider_ms/1000)
            return 'Synthetic answer.'
        finally:
            active-=1
    worker=None
    try:
        with patch.object(agent,'provider',simulated_provider):
            worker=asyncio.create_task(agent.run_forever())
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test',headers={'Authorization':'Bot local-synthetic-benchmark'}) as client:
                async def send(index):
                    command_id=uuid.uuid4(); capture_id=captures[index%len(captures)]
                    begin=time.perf_counter()
                    result=await client.post(f'/api/bot/capture-requests/{capture_id}/commands',json={
                        'command_id':str(command_id),'command':'Recap the call','tool':'answer',
                        'captions':[{'speaker':'Someone','text':'Synthetic discussion.','start':1}]})
                    assert result.status_code==202,result.text
                    admission.append((time.perf_counter()-begin)*1000)
                    started[uuid.UUID(result.json()['id'])]=begin
                await asyncio.gather(*(send(index) for index in range(args.requests)))
                pending=set(started)
                async with asyncio.timeout(settings.meeting_agent_timeout_seconds+5):
                    while pending:
                        async with async_session() as db:
                            rows=(await db.scalars(select(MeetingAgentJob).where(MeetingAgentJob.id.in_(pending)))).all()
                        for row in rows:
                            if row.state in agent.TERMINAL:
                                assert row.state=='succeeded',row.state
                                completion.append((time.perf_counter()-started[row.id])*1000)
                                pending.remove(row.id)
                        await asyncio.sleep(0.02)
            assert peak<=settings.meeting_agent_workers
    finally:
        if worker:
            worker.cancel(); await asyncio.gather(worker,return_exceptions=True)
        async with async_session() as db:
            for capture_id in captures:
                await db.delete(await db.get(CaptureRequest,capture_id))
            await db.delete(await db.get(User,user_id)); await db.commit()
    report={'kind':'local queue benchmark; simulated model; excludes real network/audio',
            'requests':args.requests,'sessions':args.sessions,'simulated_provider_ms':args.provider_ms,
            'max_parallel_inference':peak,
            'admission_ms':{'p50':percentile(admission,.5),'p95':percentile(admission,.95)},
            'completion_ms':{'p50':percentile(completion,.5),'p95':percentile(completion,.95)}}
    print(json.dumps(report,indent=2))
    if args.output:
        Path(args.output).write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requests',type=int,default=20)
    parser.add_argument('--sessions',type=int,default=5)
    parser.add_argument('--provider-ms',type=int,default=100)
    parser.add_argument('--output')
    asyncio.run(main(parser.parse_args()))
