import asyncio
import datetime as dt
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select, update

from app.config import settings
from app.database.db import async_session
from app.database.models import CaptureRequest, MeetingAgentJob as Job, MeetingBoard
from app.services import meeting_agent as agent
from app.services.board_commands import BoardCommandPlan, BoardOperation


@pytest.fixture
async def capture_id(member_user):
    async with async_session() as db:
        capture = CaptureRequest(user_id=member_user.id, platform='google_meet',
            meeting_url='https://meet.google.com/aaa-bbbb-ccc', meeting_code=uuid.uuid4().hex[:12],
            title='Agent test', status='capturing', consent_acknowledged_at=dt.datetime.now(dt.UTC))
        db.add(capture); await db.commit(); identifier=capture.id
    yield identifier
    async with async_session() as db:
        row = await db.get(CaptureRequest, identifier)
        if row:
            await db.delete(row); await db.commit()


async def submit(capture_id, tool='open_board', command='Open board', command_id=None):
    async with async_session() as db:
        return await agent.submit(db, capture_id, command_id or uuid.uuid4(),
                                  {'command': command, 'tool': tool, 'captions': []})


async def row(job):
    async with async_session() as db:
        return await db.get(Job, job.id)


@pytest.mark.asyncio
async def test_receipts_are_durable_and_duplicate_submission_does_not_execute_twice(capture_id):
    job = await submit(capture_id)
    same = await submit(capture_id, command_id=job.command_id)
    assert same.id == job.id
    claimed = await agent.claim()
    assert claimed.id == job.id
    await agent.supervise(claimed)
    saved = await row(job)
    assert saved.state == 'succeeded'
    assert len(saved.receipts) == 1
    assert saved.receipts[0]['board_id']
    with pytest.raises(ValueError, match='different request'):
        await submit(capture_id, command='Different', command_id=job.command_id)


@pytest.mark.asyncio
async def test_queue_admission_and_per_capture_serial_execution(capture_id, monkeypatch):
    monkeypatch.setattr(settings, 'meeting_agent_queue_per_capture', 2)
    first, second = await submit(capture_id), await submit(capture_id)
    with pytest.raises(agent.QueueFull):
        await submit(capture_id)
    claimed = await agent.claim()
    assert claimed.id == first.id
    assert await agent.claim() is None
    await agent.supervise(claimed)
    assert (await agent.claim()).id == second.id
    async with async_session() as db:
        await agent.cancel(db, capture_id, second.command_id)


@pytest.mark.asyncio
async def test_cancel_during_model_call_fences_board_write(capture_id):
    job = await submit(capture_id, 'edit_board', 'Add signup')
    claimed = await agent.claim()
    started, release = asyncio.Event(), asyncio.Event()
    async def slow_provider(*args, **kwargs):
        started.set()
        await release.wait()
        return BoardCommandPlan(message='Ready', operations=[BoardOperation(op='create_node', title='Signup')]), {}
    with patch.object(agent, 'provider', slow_provider):
        running = asyncio.create_task(agent.run_claimed(claimed))
        await asyncio.wait_for(started.wait(), 1)
        async with async_session() as db:
            await agent.cancel(db, capture_id, job.command_id)
        release.set()
        with pytest.raises(agent.LostLease):
            await running
    async with async_session() as db:
        board = await db.scalar(select(MeetingBoard).where(MeetingBoard.capture_request_id == capture_id))
        assert board.nodes == []
    assert (await row(job)).state == 'cancelled'


@pytest.mark.asyncio
async def test_expired_lease_recovery_cannot_be_overwritten_by_old_worker(capture_id):
    job = await submit(capture_id)
    old = await agent.claim()
    async with async_session() as db:
        await db.execute(update(Job).where(Job.id == job.id).values(lease_until=dt.datetime.now(dt.UTC)-dt.timedelta(seconds=1)))
        await db.commit()
    replacement = await agent.claim()
    assert replacement.id == job.id and replacement.lease_token != old.lease_token
    with pytest.raises(agent.LostLease):
        await agent.run_claimed(old)
    await agent.supervise(replacement)
    assert (await row(job)).state == 'succeeded'


@pytest.mark.asyncio
async def test_compound_plan_resumes_from_committed_receipt(capture_id):
    job = await submit(capture_id, tool='auto', command='Open a board and add signup')
    claimed = await agent.claim()
    plan = [agent.Step(tool='open_board', instruction='Open board').model_dump(),
            agent.Step(tool='edit_board', instruction='Add signup').model_dump()]
    async with async_session() as db:
        saved = await db.get(Job, job.id); saved.plan=plan; await db.commit()
    claimed.plan = plan
    await agent.execute_step(claimed, 0, plan[0])
    async with async_session() as db:
        await db.execute(update(Job).where(Job.id == job.id).values(lease_until=dt.datetime.now(dt.UTC)-dt.timedelta(seconds=1)))
        await db.commit()
    recovered = await agent.claim()
    result = BoardCommandPlan(message='Ready', operations=[BoardOperation(op='create_node', title='Signup')])
    with patch('app.services.gemini_service.generate_structured', return_value=(result, {})):
        await agent.supervise(recovered)
    saved=await row(job)
    assert saved.state == 'succeeded' and len(saved.receipts) == 2
    async with async_session() as db:
        board=await db.scalar(select(MeetingBoard).where(MeetingBoard.capture_request_id==capture_id))
        assert len(board.nodes) == 1 and board.version == 2


@pytest.mark.asyncio
async def test_task_effect_and_receipt_commit_once(capture_id):
    job=await submit(capture_id, 'add_task', 'Ravi to review Friday')
    with patch('app.services.live_assist.parse_task', return_value={'owner':'Ravi','description':'Review','deadline':'Friday'}):
        await agent.supervise(await agent.claim())
    assert (await row(job)).state=='succeeded'
    async with async_session() as db:
        capture=await db.get(CaptureRequest,capture_id)
        assert len(capture.live_tasks)==1 and capture.live_tasks[0]['command_id']


@pytest.mark.asyncio
async def test_api_ack_is_immediate_and_scope_and_auth_are_checked(client,capture_id,monkeypatch):
    monkeypatch.setattr(settings,'bot_api_secret','agent-test')
    url=f'/api/bot/capture-requests/{capture_id}/commands'
    body={'command_id':str(uuid.uuid4()),'command':'Open board','tool':'open_board'}
    assert (await client.post(url,json=body)).status_code==401
    response=await client.post(url,json=body,headers={'Authorization':'Bot agent-test'})
    assert response.status_code==202 and response.json()['state']=='accepted'
    other=f'/api/bot/capture-requests/{uuid.uuid4()}/commands/{body["command_id"]}'
    assert (await client.get(other,headers={'Authorization':'Bot agent-test'})).status_code==404
    cancelled=await client.post(url+f'/{body["command_id"]}/cancel',headers={'Authorization':'Bot agent-test'})
    assert cancelled.json()['state']=='cancelled'


def test_context_has_a_hard_budget_and_keeps_latest_text():
    captions=[{'text':str(i)*1000,'speaker':'Someone','start':i} for i in range(120)]
    clipped=agent.compact_captions(captions)
    assert sum(len(c['text']) for c in clipped)<=12000
    assert clipped[-1]['start']==119


@pytest.mark.asyncio
async def test_cancellation_before_acceptance_cannot_be_resurrected(capture_id):
    identifier=uuid.uuid4()
    async with async_session() as db:
        cancelled=await agent.cancel(db,capture_id,identifier)
        assert cancelled.state=='cancelled'
    delayed=await submit(capture_id,command_id=identifier)
    assert delayed.id==cancelled.id and delayed.state=='cancelled'
    assert await agent.claim() is None


@pytest.mark.asyncio
async def test_concurrent_claims_do_not_run_two_commands_in_one_meeting(capture_id):
    await submit(capture_id); await submit(capture_id)
    results=await asyncio.gather(agent.claim(),agent.claim())
    assert sum(job is not None for job in results)==1


@pytest.mark.asyncio
async def test_deadline_expiration_is_terminal_and_old_worker_cannot_write(capture_id):
    job=await submit(capture_id)
    claimed=await agent.claim()
    async with async_session() as db:
        await db.execute(update(Job).where(Job.id==job.id).values(deadline_at=dt.datetime.now(dt.UTC)-dt.timedelta(seconds=1)))
        await db.commit()
    assert await agent.claim() is None
    assert (await row(job)).state=='failed'
    with pytest.raises(agent.LostLease):
        await agent.run_claimed(claimed)
    async with async_session() as db:
        assert await db.scalar(select(MeetingBoard).where(MeetingBoard.capture_request_id==capture_id)) is None


@pytest.mark.asyncio
async def test_failure_after_first_step_keeps_and_reports_its_receipt(capture_id):
    job=await submit(capture_id,tool='auto')
    claimed=await agent.claim()
    plan=[agent.Step(tool='open_board',instruction='Open').model_dump(),agent.Step(tool='edit_board',instruction='Add signup').model_dump()]
    async with async_session() as db:
        saved=await db.get(Job,job.id); saved.plan=plan; await db.commit()
    claimed.plan=plan
    async def fail(*args,**kwargs):
        raise RuntimeError('private provider response')
    with patch.object(agent,'provider',fail):
        await agent.supervise(claimed)
    saved=await row(job)
    assert saved.state=='failed' and len(saved.receipts)==1
    assert 'Opened the meeting board' in agent.serialize(saved)['result']['message']
    assert 'private provider response' not in agent.serialize(saved)['result']['message']


@pytest.mark.asyncio
async def test_status_enforces_deadline_even_without_running_workers(client,capture_id,monkeypatch):
    monkeypatch.setattr(settings,'bot_api_secret','agent-test')
    job=await submit(capture_id)
    async with async_session() as db:
        await db.execute(update(Job).where(Job.id==job.id).values(deadline_at=dt.datetime.now(dt.UTC)-dt.timedelta(seconds=1)))
        await db.commit()
    result=await client.get(f'/api/bot/capture-requests/{capture_id}/commands/{job.command_id}',headers={'Authorization':'Bot agent-test'})
    assert result.status_code==200 and result.json()['state']=='failed'
    assert (await row(job)).phase=='deadline'
