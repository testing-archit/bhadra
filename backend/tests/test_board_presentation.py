"""In-call board visibility without opening accounts or joining Meet."""
from unittest.mock import AsyncMock

import pytest

from tests.test_bot_captions import meeting_session


@pytest.mark.parametrize('sharing', [True, False])
async def test_board_is_presented_or_shown_in_camera(tmp_path, monkeypatch, sharing):
    monkeypatch.setattr(meeting_session.config, 'SESSIONS_DIR', tmp_path)
    monkeypatch.setattr(meeting_session.config, 'PRESENT_BOARD', True)
    session = meeting_session.MeetingSession({'capture_request_id': 'cap'})
    session.avatar_camera = True
    page = AsyncMock()
    page.evaluate.return_value = {'cameraVisible': False}
    board = {'version': 1, 'nodes': [], 'title': 'Team board'}
    monkeypatch.setattr(meeting_session.uploader, 'board_state', lambda cid: board)
    start = AsyncMock(return_value=sharing)
    monkeypatch.setattr(meeting_session.board_presenter, 'start', start)
    reply = await session.present_board(page)
    start.assert_awaited_once_with(page, board)
    if sharing:
        assert 'as presenting' in reply
        assert 'hideCamera' in page.evaluate.await_args.args[0]
    else:
        assert 'camera tile' in reply
        assert 'showInCamera' in page.evaluate.await_args.args[0]
        assert page.evaluate.await_args.args[1] == board


async def test_native_canvas_unavailable_stops_previous_board_and_never_shares_login(tmp_path, monkeypatch):
    monkeypatch.setattr(meeting_session.config, 'SESSIONS_DIR', tmp_path)
    monkeypatch.setattr(meeting_session.config, 'PRESENT_BOARD', True)
    session = meeting_session.MeetingSession({'capture_request_id': 'cap'})
    session._figjam_browser = AsyncMock()
    session._figjam_browser.file_url = 'https://www.figma.com/board/ABCdef123456'
    session._figjam_browser.frame.return_value = None
    stop, start = AsyncMock(), AsyncMock()
    monkeypatch.setattr(meeting_session.board_presenter, 'stop', stop)
    monkeypatch.setattr(meeting_session.board_presenter, 'start', start)
    reply = await session.present_board(AsyncMock())
    assert "can't show" in reply
    stop.assert_awaited_once()
    start.assert_not_awaited()


async def test_board_edits_request_presentation_even_after_opening(tmp_path, monkeypatch):
    monkeypatch.setattr(meeting_session.config, 'SESSIONS_DIR', tmp_path)
    session = meeting_session.MeetingSession({'capture_request_id': 'cap'})
    session._board_active = True
    session.submit_agent_command = AsyncMock()
    command = meeting_session.Command('', 'draw a signup flow')
    await session.execute_command(None, command)
    assert command.follow_up == 'present_board'


async def test_updates_keep_camera_fallback_without_retrying_share_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(meeting_session.config, 'SESSIONS_DIR', tmp_path)
    monkeypatch.setattr(meeting_session.config, 'PRESENT_BOARD', True)
    session = meeting_session.MeetingSession({'capture_request_id': 'cap'})
    session.avatar_camera = True
    page = AsyncMock()
    page.evaluate.return_value = {'cameraVisible': True}
    monkeypatch.setattr(meeting_session.uploader, 'board_state', lambda cid: {'version': 2})
    start = AsyncMock()
    monkeypatch.setattr(meeting_session.board_presenter, 'start', start)
    assert 'camera tile' in await session.present_board(page)
    start.assert_not_awaited()
