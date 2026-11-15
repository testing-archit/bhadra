import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.config import settings
from app.database.db import async_session
from app.database.models import MeetingAgentJob as Job
from app.main import app
from tests.test_meeting_agent import capture_id
from tests.test_figjam import paired_figjam
from tests.test_bot_captions import meeting_session
from agent_client import AgentClient, AgentBusy, compact_captions
from command_runtime import Command


@pytest.mark.asyncio
async def test_lost_acceptance_response_retries_same_command_and_recovers_status(capture_id,monkeypatch):
    monkeypatch.setattr(settings,'bot_api_secret','agent-client-test')
    monkeypatch.setenv('BOT_API_SECRET','agent-client-test')
    monkeypatch.setattr(meeting_session.config,'BACKEND_URL','http://test')
    class LoseFirstResponse(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner=httpx.ASGITransport(app=app)
            self.lost=False
        async def handle_async_request(self,request):
            response=await self.inner.handle_async_request(request)
            if request.method=='POST' and request.url.path.endswith('/commands') and not self.lost:
                self.lost=True
                raise httpx.ReadError('response lost',request=request)
            return response
    client=AgentClient(capture_id,transport=LoseFirstResponse())
    command=Command('','Open board')
    try:
        saved=await client.submit(command,'open_board',[],False)
        assert saved['state']=='accepted'
        async with async_session() as db:
            assert await db.scalar(select(func.count()).select_from(Job).where(Job.capture_request_id==capture_id))==1
        assert len(await client.outstanding())==1
        assert (await client.cancel(command.id))['state']=='cancelled'
        await client.delivered(command.id)
        assert await client.outstanding()==[]
    finally:
        await client.close()


def test_client_limits_transcript_payload():
    rows=compact_captions([{'text':'x'*5000,'speaker':'Someone','start':1} for _ in range(500)])
    assert len(rows)<=120
    assert sum(len(row['text']) for row in rows)<=12000
    assert all(len(row['text'])<=1500 for row in rows)


@pytest.mark.asyncio
async def test_bot_ack_worker_result_and_delivery_receipt_form_one_workflow(capture_id,monkeypatch,tmp_path,paired_figjam,client):
    from app.services import meeting_agent as agent
    from app.services.board_commands import BoardCommandPlan, BoardOperation
    from unittest.mock import patch
    monkeypatch.setattr(settings,'bot_api_secret','agent-client-test')
    monkeypatch.setenv('BOT_API_SECRET','agent-client-test')
    monkeypatch.setattr(meeting_session.config,'BACKEND_URL','http://test')
    monkeypatch.setattr(meeting_session.config,'SESSIONS_DIR',tmp_path)
    session=meeting_session.MeetingSession({'capture_request_id':str(capture_id)})
    session._agent=AgentClient(capture_id,transport=httpx.ASGITransport(app=app))
    messages=[]; spoken=[]; done=asyncio.Event()
    async def send(page,message):
        messages.append(message); return True
    async def enqueue(command,message):
        spoken.append(message); done.set()
    session.send_agent_message=send
    runtime=type('Runtime',(),{'enqueue_reply':staticmethod(enqueue)})()
    async def fake_provider(*a,**kw):
        await asyncio.sleep(.01)
        return BoardCommandPlan(message='Ready',operations=[BoardOperation(op='create_node',title='Signup')]),{}
    with patch.object(agent,'provider',fake_provider):
        async def plugin():
            while True:
                result = await client.post('/api/figjam/bridge/poll', headers=paired_figjam['headers'])
                delivery = result.json()['delivery']
                if delivery:
                    assert delivery['snapshot']['nodes'][0]['title'] == 'Signup'
                    await client.post(f"/api/figjam/bridge/deliveries/{delivery['id']}/ack", headers=paired_figjam['headers'], json={'state':'applied'})
                await asyncio.sleep(.02)
        bridge = asyncio.create_task(plugin())
        worker=asyncio.create_task(agent.run_forever())
        monitor=asyncio.create_task(session.agent_results_loop(object(),runtime))
        try:
            result=await session.submit_agent_command(object(),Command('','Add signup'),'edit_board')
            assert result is None
            assert messages[0].startswith('Working on that')
            await asyncio.wait_for(done.wait(),3)
            assert 'Updated your shared FigJam board' in spoken[0]
            # Speech intentionally arrives before chat/delivery acknowledgment.
            # Verify eventual delivery without coupling that faster path to chat.
            async with asyncio.timeout(3):
                while await session._agent.outstanding():
                    await asyncio.sleep(.02)
            assert await session._agent.outstanding()==[]
        finally:
            worker.cancel(); monitor.cancel(); bridge.cancel()
            await asyncio.gather(worker,monitor,bridge,return_exceptions=True)
            await session._agent.close()
