import asyncio
import datetime as dt
import uuid
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
import json

import pytest
from sqlalchemy import select
from app.database.db import async_session
from app.database.models import CaptureRequest, FigJamConnection, FigJamDelivery, MeetingAgentJob, MeetingBoard
from app.services import meeting_agent as agent
from app.services.board_commands import BoardCommandPlan, BoardOperation
from tests.conftest import auth_headers
from tests.test_meeting_agent import capture_id, row


@pytest.fixture
async def paired_figjam(client, member_user, capture_id):
    response = await client.post(f'/api/figjam/captures/{capture_id}/pair', headers=auth_headers(member_user),
        json={'file_url': 'https://www.figma.com/board/ABCdef012345/My-board?node-id=1-2'})
    assert response.status_code == 200
    code = response.json()['code']
    response = await client.post('/api/figjam/bridge/pair', json={'code': code, 'file_key': 'ABCdef012345'})
    assert response.status_code == 200
    return {'headers': {'Authorization': 'Bridge '+response.json()['token']}, 'code': code, 'capture_id': capture_id}


async def test_pair_code_is_one_use_and_connection_is_scoped(client, paired_figjam, other_member_user):
    headers = paired_figjam['headers']
    assert (await client.post('/api/figjam/bridge/poll', headers=headers)).status_code == 200
    assert (await client.post('/api/figjam/bridge/poll')).status_code == 401
    assert (await client.post('/api/figjam/bridge/pair', json={'code':paired_figjam['code'], 'file_key':'ABCdef012345'})).status_code == 401
    assert (await client.post(f"/api/figjam/captures/{paired_figjam['capture_id']}/pair", headers=auth_headers(other_member_user),
        json={'file_url':'https://www.figma.com/board/ABCdef012345'})).status_code == 404
    assert (await client.post(f'/api/figjam/bridge/deliveries/{uuid.uuid4()}/ack', headers=headers, json={'state':'applied'})).status_code == 404


async def test_unpaired_native_request_asks_for_setup_without_drawing(client, capture_id):
    async with async_session() as db:
        job = await agent.submit(db, capture_id, uuid.uuid4(), {'tool':'edit_board','command':'Draw signup', 'board_provider':'figjam'})
    with patch.object(agent, 'provider') as provider:
        await agent.supervise(await agent.claim())
    provider.assert_not_called()
    assert (await row(job)).state == 'needs_input'
    async with async_session() as db:
        assert await db.scalar(select(MeetingBoard.id).where(MeetingBoard.capture_request_id == capture_id)) is None


async def test_native_success_requires_plugin_ack_and_replay_is_deduplicated(client, paired_figjam):
    async with async_session() as db:
        job = await agent.submit(db, paired_figjam['capture_id'], uuid.uuid4(),
            {'tool':'edit_board','command':'Draw signup','board_provider':'figjam'})
    plan = BoardCommandPlan(message='Ready', operations=[BoardOperation(op='create_node',title='Signup')])
    async def provider(*args, **kwargs): return plan, {}
    with patch.object(agent, 'provider', provider):
        task = asyncio.create_task(agent.supervise(await agent.claim()))
        try:
            async with asyncio.timeout(3):
                while True:
                    response = await client.post('/api/figjam/bridge/poll', headers=paired_figjam['headers'])
                    delivery = response.json()['delivery']
                    if delivery: break
                    await asyncio.sleep(.02)
            assert (await row(job)).state == 'running'
            assert delivery['snapshot']['nodes'][0]['title'] == 'Signup'
            path = f"/api/figjam/bridge/deliveries/{delivery['id']}/ack"
            for _ in range(2):
                assert (await client.post(path, headers=paired_figjam['headers'], json={'state':'applied'})).json()['state'] == 'applied'
            await asyncio.wait_for(task, 2)
            assert (await row(job)).state == 'succeeded'
            assert (await client.post('/api/figjam/bridge/poll', headers=paired_figjam['headers'])).json()['delivery'] is None
        finally:
            task.cancel(); await asyncio.gather(task, return_exceptions=True)


async def test_cancelled_delivery_is_not_offered_to_plugin(client, paired_figjam):
    async with async_session() as db:
        connection = await db.scalar(select(FigJamConnection).where(FigJamConnection.capture_request_id == paired_figjam['capture_id']))
        job = await agent.submit(db, paired_figjam['capture_id'], uuid.uuid4(), {'tool':'open_board','command':'Open'})
        db.add(FigJamDelivery(connection_id=connection.id, job_id=job.id, command_id=uuid.uuid4(), baseline={}, snapshot={}, expires_at=dt.datetime.now(dt.UTC)+dt.timedelta(seconds=20)))
        job.state = 'cancelled'
        await db.commit()
    assert (await client.post('/api/figjam/bridge/poll', headers=paired_figjam['headers'])).json()['delivery'] is None


async def test_bridge_cors_is_limited_to_bridge_endpoints(client):
    headers = {'Origin':'null','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization,content-type'}
    assert (await client.options('/api/figjam/bridge/poll', headers=headers)).headers.get('access-control-allow-origin') == 'null'
    assert (await client.options('/api/meetings', headers=headers)).headers.get('access-control-allow-origin') is None


async def test_shared_figjam_link_stays_with_finished_meeting(client, paired_figjam, member_user, make_meeting):
    meeting = await make_meeting(member_user, 'Native diagram review', None)
    async with async_session() as db:
        capture = await db.get(CaptureRequest, paired_figjam['capture_id'])
        capture.meeting_id, capture.status = meeting.id, 'stopped'
        await db.commit()
    result = await client.get(f'/api/boards/meetings/{meeting.id}', headers=auth_headers(member_user))
    assert result.status_code == 200
    assert result.json()['external_url'] == 'https://www.figma.com/board/ABCdef012345'


def test_downloaded_plugin_matches_sources_and_has_scoped_network_access():
    root = Path(__file__).resolve().parents[2]
    with ZipFile(root/'frontend/public/downloads/wilco-figjam.zip') as bundle:
        manifest = json.loads(bundle.read('manifest.json'))
        domains = manifest['networkAccess']['allowedDomains']
        assert len(domains) == 1 and domains[0].startswith('https://') and '*' not in domains[0]
        assert bundle.read('code.js').decode() == (root/'integrations/figjam/code.js').read_text().replace('__API_ORIGIN__', domains[0])
        assert bundle.read('ui.html').decode() == (root/'integrations/figjam/ui.html').read_text()
