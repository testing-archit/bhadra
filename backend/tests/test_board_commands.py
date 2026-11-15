import uuid
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.config import settings
from app.database.db import async_session
from app.database.models import CaptureRequest
from app.services import board_service
from app.services.board_commands import BoardOperation, BoardCommandPlan, apply_operations


def node(identifier='a', **kwargs):
    return dict(id=identifier, kind='idea', title=identifier, text='', x=80, y=100,
                origin='manual', locked=False, source_id='turn:1', source_start_ms=1000, **kwargs)


def test_edits_are_atomic_and_keep_source_and_human_origin():
    original = [node()]
    result, _ = apply_operations(original, [], [BoardOperation(op='update_node', node_id='a', title='Signup')], uuid.uuid4())
    assert original[0]['title'] == 'a'
    assert result[0]['source_id'] == 'turn:1'
    assert result[0]['origin'] == 'manual'
    with pytest.raises(ValueError, match='existing'):
        apply_operations(original, [], [BoardOperation(op='update_node', node_id='a', title='Changed'),
                                        BoardOperation(op='move_node', node_id='missing', x=1, y=1)], uuid.uuid4())
    assert original[0]['title'] == 'a'


def test_locked_points_and_invalid_coordinates_cannot_be_modified():
    locked = node(); locked['locked'] = True
    with pytest.raises(ValueError, match='Unlock'):
        apply_operations([locked], [], [BoardOperation(op='remove_node', node_id='a')], uuid.uuid4())
    with pytest.raises(ValidationError):
        BoardOperation(op='move_node', node_id='a', x=float('nan'), y=0)


def test_connect_delete_and_retries_have_stable_ids():
    identifier = uuid.uuid4()
    operations = [BoardOperation(op='create_node', title='Verification')]
    first, _ = apply_operations([], [], operations, identifier)
    second, _ = apply_operations([], [], operations, identifier)
    assert first == second
    nodes, edges = apply_operations([node('a'), node('b')], [],
        [BoardOperation(op='connect_nodes', source='a', target='b')], identifier)
    assert edges[0]['source'] == 'a'
    _, edges = apply_operations(nodes, edges, [BoardOperation(op='remove_node', node_id='a')], uuid.uuid4())
    assert not edges


@pytest.mark.asyncio
async def test_bot_board_commands_are_authenticated_idempotent_and_undoable(client, member_user, monkeypatch):
    monkeypatch.setattr(settings, 'bot_api_secret', 'board-test-secret')
    from datetime import datetime, UTC
    async with async_session() as db:
        capture = CaptureRequest(user_id=member_user.id, platform='google_meet',
            meeting_url='https://meet.google.com/xyz-abcd-efg', meeting_code='xyz-abcd-efg',
            title='Voice board', status='capturing', consent_acknowledged_at=datetime.now(UTC))
        db.add(capture); await db.commit(); capture_id = capture.id
    headers = {'Authorization': 'Bot board-test-secret'}
    url = f'/api/bot/capture-requests/{capture_id}/board'
    try:
        assert (await client.get(url)).status_code == 401
        board = (await client.get(url, headers=headers)).json()
        command_id = str(uuid.uuid4())
        plan = BoardCommandPlan(message='Ready', operations=[BoardOperation(op='create_node', title='Signup')])
        with patch('app.services.gemini_service.generate_structured', return_value=(plan, {})) as model:
            for index in range(2):
                result = await client.post(url+'/commands', headers=headers,
                    json={'command_id': command_id, 'command': 'Add signup to the board'})
                assert result.status_code == 200, result.text
                assert result.json()['board']['version'] == 2
                assert len(result.json()['board']['nodes']) == 1
                assert result.json()['duplicate'] == bool(index)
            assert model.call_count == 1
        undone = await client.post(url+'/commands', headers=headers,
            json={'command_id': str(uuid.uuid4()), 'command': 'please undo that'})
        assert undone.status_code == 200, undone.text
        assert undone.json()['board']['nodes'] == []
        assert undone.json()['board']['version'] == 3
        assert undone.json()['board']['paused'] is True
        # Human changes saved after a voice operation must survive an undo request.
        with patch('app.services.gemini_service.generate_structured', return_value=(plan, {})):
            created = (await client.post(url+'/commands', headers=headers,
                json={'command_id': str(uuid.uuid4()), 'command': 'Add signup'})).json()['board']
        from tests.conftest import auth_headers
        changed = await client.put(f"/api/boards/{created['id']}", headers=auth_headers(member_user), json={
            'expected_version': created['version'], 'title': created['title'],
            'nodes': [{**created['nodes'][0], 'title': 'Human correction'}], 'edges': [],
        })
        assert changed.status_code == 200, changed.text
        refused = await client.post(url+'/commands', headers=headers,
            json={'command_id': str(uuid.uuid4()), 'command': 'undo that'})
        assert refused.status_code == 409
        assert (await client.get(url, headers=headers)).json()['nodes'][0]['title'] == 'Human correction'
    finally:
        async with async_session() as db:
            await db.delete(await db.get(CaptureRequest, capture_id)); await db.commit()


@pytest.mark.asyncio
async def test_voice_plan_cannot_overwrite_an_intervening_human_edit(member_user):
    from datetime import datetime, UTC
    async with async_session() as db:
        capture = CaptureRequest(user_id=member_user.id, platform='google_meet',
            meeting_url='https://meet.google.com/mno-pqrs-tuv', meeting_code='mno-pqrs-tuv',
            title='Conflict board', status='capturing', consent_acknowledged_at=datetime.now(UTC))
        db.add(capture); await db.commit(); capture_id = capture.id
        board = await board_service.ensure_for_capture(db, capture)
        board_id = board.id; await db.commit()
    # A separate connection writes while the generation callback is in flight.
    import asyncio
    loop = asyncio.get_running_loop()
    async def human_edit():
        async with async_session() as db:
            from app.database.models import MeetingBoard
            board = await db.get(MeetingBoard, board_id)
            await board_service.save_snapshot(db, board, expected_version=1, nodes=[node('human')], edges=[],
                                              actor_id=member_user.id, source='manual')
            await db.commit()
    def generate(*_args, **_kwargs):
        asyncio.run_coroutine_threadsafe(human_edit(), loop).result(timeout=5)
        return BoardCommandPlan(message='Ready', operations=[BoardOperation(op='create_node', title='AI')]), {}
    try:
        with patch('app.services.gemini_service.generate_structured', side_effect=generate):
            async with async_session() as db:
                with pytest.raises(board_service.BoardCommandConflict):
                    await board_service.command_capture_board(db, capture_id, uuid.uuid4(), 'Add AI')
                await db.rollback()
        async with async_session() as db:
            from app.database.models import MeetingBoard
            board = await db.get(MeetingBoard, board_id)
            assert [n['id'] for n in board.nodes] == ['human']
    finally:
        async with async_session() as db:
            await db.delete(await db.get(CaptureRequest, capture_id)); await db.commit()


def test_a_complete_flow_can_be_created_in_one_voice_request():
    nodes, edges = apply_operations([], [], [
        BoardOperation(op='create_node', node_id='new:signup', title='Signup', x=80, y=100),
        BoardOperation(op='create_node', node_id='new:verify', title='Verification', x=450, y=100),
        BoardOperation(op='connect_nodes', source='new:signup', target='new:verify'),
    ], uuid.uuid4())
    assert [n['title'] for n in nodes] == ['Signup', 'Verification']
    assert edges[0]['source'] == nodes[0]['id']
    assert edges[0]['target'] == nodes[1]['id']
    assert all(n['id'].startswith('voice:') for n in nodes)
