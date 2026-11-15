import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.config import settings
from app.database.db import async_session
from app.database.models import FigJamConnection, MeetingBrowserAction
from app.services import browser_actions
from app.services import meeting_agent as agent
from tests.test_meeting_agent import capture_id, row

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('command,expected', [
    ('Open Fig Jam', 'open_board'),
    ('I need you to open Jam boards', 'open_board'),
    ('Would you please open FigJam and draw signup', 'edit_board'),
    ('Open FigJam and create a signup flow', 'edit_board'),
    ('Do not open FigJam', None),
    ('Why did we open FigJam?', None),
])
async def test_server_corrects_stale_answer_route_without_model(command, expected):
    job = type('Job', (), {'payload': {'command': command, 'tool': 'answer'}})()
    with patch.object(agent, 'provider') as provider:
        plan = await agent.make_plan(job)
    provider.assert_not_called()
    assert plan[0]['tool'] == (expected or 'answer')


async def native_job(capture_id, tool='open_board'):
    async with async_session() as db:
        return await agent.submit(db, capture_id, uuid.uuid4(), {'command': 'Open Fig Jam',
            'tool': tool, 'board_provider': 'figjam', 'browser_executor': True})


async def pending_action(capture_id):
    for _ in range(60):
        async with async_session() as db:
            action = await browser_actions.claim(db, capture_id)
        if action:
            return action
        await asyncio.sleep(.01)
    raise AssertionError('Browser action was not queued')


async def test_open_requires_native_ack_and_never_calls_model(capture_id):
    job = await native_job(capture_id)
    claimed = await agent.claim()
    with patch.object(agent, 'provider') as provider:
        task = asyncio.create_task(agent.supervise(claimed))
        action = await pending_action(capture_id)
        assert (await row(job)).state == 'running'
        assert action['operation'] == 'open_figjam'
        async with async_session() as db:
            assert await browser_actions.claim(db, capture_id) is None  # no retry of an uncertain browser side effect
        async with async_session() as db:
            await browser_actions.complete(db, capture_id, uuid.UUID(action['id']), uuid.UUID(action['claim_token']),
                {'outcome': 'applied', 'file_url': 'https://www.figma.com/board/ABCdef123456/A-board?node-id=1'})
        await asyncio.wait_for(task, 2)
    provider.assert_not_called()
    saved = await row(job)
    assert saved.state == 'succeeded' and 'https://www.figma.com/board/ABCdef123456' in saved.result['message']
    async with async_session() as db:
        connection = await db.scalar(select(FigJamConnection).where(FigJamConnection.capture_request_id == capture_id))
        assert connection.transport == 'browser' and connection.token_hash is None


async def test_cancelled_browser_action_cannot_ack_or_register_file(capture_id):
    job = await native_job(capture_id)
    task = asyncio.create_task(agent.supervise(await agent.claim()))
    action = await pending_action(capture_id)
    async with async_session() as db:
        await agent.cancel(db, capture_id, job.command_id)
    async with async_session() as db:
        with pytest.raises(LookupError):
            await browser_actions.complete(db, capture_id, uuid.UUID(action['id']), uuid.UUID(action['claim_token']),
                {'outcome': 'applied', 'file_url': 'https://www.figma.com/board/ABCdef123456'})
    await asyncio.wait_for(task, 2)
    async with async_session() as db:
        assert await db.scalar(select(FigJamConnection.id).where(FigJamConnection.capture_request_id == capture_id)) is None


@pytest.mark.parametrize('tool', ['open_board', 'edit_board'])
async def test_auth_failure_is_explicit_and_does_not_offer_portal_pairing(capture_id, tool):
    job = await native_job(capture_id, tool)
    task = asyncio.create_task(agent.supervise(await agent.claim()))
    action = await pending_action(capture_id)
    async with async_session() as db:
        await browser_actions.complete(db, capture_id, uuid.UUID(action['id']), uuid.UUID(action['claim_token']), {'outcome': 'auth_required'})
    await asyncio.wait_for(task, 2)
    saved = await row(job)
    assert saved.state == 'needs_input' and 'one-time Figma browser sign-in' in saved.result['message']
    assert 'pairing' not in saved.result['message']


@pytest.mark.parametrize('outcome,expected_state', [('applied', 'succeeded'), ('uncertain', 'needs_input')])
async def test_draw_preflights_before_inference_and_requires_separate_native_ack(capture_id, outcome, expected_state):
    from app.services.board_commands import BoardCommandPlan, BoardOperation
    job = await native_job(capture_id, 'edit_board')
    provider = AsyncMock(return_value=(BoardCommandPlan(message='Ready', operations=[BoardOperation(op='create_node', title='Signup')]), {}))
    with patch.object(agent, 'provider', provider):
        task = asyncio.create_task(agent.supervise(await agent.claim()))
        opened = await pending_action(capture_id)
        provider.assert_not_called()
        async with async_session() as db:
            await browser_actions.complete(db, capture_id, uuid.UUID(opened['id']), uuid.UUID(opened['claim_token']),
                {'outcome': 'applied', 'file_url': 'https://www.figma.com/board/ABCdef123456'})
        drawing = await pending_action(capture_id)
        assert drawing['operation'] == 'draw_figjam'
        assert drawing['payload']['file_url'] == 'https://www.figma.com/board/ABCdef123456'
        assert drawing['payload']['baseline'] == {'nodes': [], 'edges': []}
        assert drawing['payload']['snapshot']['nodes'][0]['title'] == 'Signup'
        assert (await row(job)).state == 'running'
        async with async_session() as db:
            await browser_actions.complete(db, capture_id, uuid.UUID(drawing['id']), uuid.UUID(drawing['claim_token']),
                {'outcome': outcome, 'file_url': 'https://www.figma.com/board/ABCdef123456'})
        await asyncio.wait_for(task, 2)
    assert (await row(job)).state == expected_state
    provider.assert_awaited_once()


async def test_browser_endpoints_require_bot_auth_scope_token_and_native_url(client, capture_id, monkeypatch):
    monkeypatch.setattr(settings, 'bot_api_secret', 'browser-test')
    base = f'/api/bot/capture-requests/{capture_id}/browser-actions'
    headers = {'Authorization': 'Bot browser-test'}
    assert (await client.post(base + '/claim')).status_code == 401
    job = await native_job(capture_id)
    task = asyncio.create_task(agent.supervise(await agent.claim()))
    action = await pending_action(capture_id)
    try:
        path = base + '/' + action['id']
        body = {'claim_token': action['claim_token'], 'outcome': 'applied', 'file_url': 'https://evil.test/board/ABCdef123456'}
        assert (await client.post(path + '/complete', json=body, headers=headers)).status_code == 422
        body['file_url'] = 'https://www.figma.com/board/ABCdef123456'
        body['claim_token'] = str(uuid.uuid4())
        assert (await client.post(path + '/complete', json=body, headers=headers)).status_code == 409
        other = f'/api/bot/capture-requests/{uuid.uuid4()}/browser-actions/{action["id"]}/check'
        assert (await client.post(other, json={'claim_token': action['claim_token']}, headers=headers)).status_code == 409
    finally:
        async with async_session() as db:
            await agent.cancel(db, capture_id, job.command_id)
        await asyncio.wait_for(task, 2)
