from unittest.mock import AsyncMock, Mock

import pytest

from tests.test_bot_captions import meeting_session  # initializes the bot import path
from figjam_browser import FigJamBrowser, canonical


@pytest.mark.asyncio
async def test_missing_auth_does_not_open_browser_or_report_success(monkeypatch, tmp_path):
    monkeypatch.setattr(meeting_session.config, 'FIGMA_AUTH_STATE_PATH', tmp_path/'absent.json')
    playwright = Mock()
    browser = FigJamBrowser(playwright)
    result = await browser.execute({'operation': 'open_figjam', 'payload': {}}, AsyncMock())
    assert result == {'outcome': 'auth_required', 'file_url': None}
    playwright.chromium.launch.assert_not_called()


@pytest.mark.asyncio
async def test_arbitrary_destinations_and_scripts_are_never_executed():
    playwright = Mock()
    browser = FigJamBrowser(playwright)
    for action in [{'operation': 'open_figjam', 'payload': {'file_url': 'https://www.figma.com.evil.test/board/ABCdef123456'}},
                   {'operation': 'run_javascript', 'payload': {'script': 'doSomething()'}}]:
        assert (await browser.execute(action, AsyncMock()))['outcome'] == 'uncertain'
    playwright.chromium.launch.assert_not_called()


@pytest.mark.asyncio
async def test_changed_baseline_refuses_mutations():
    browser = FigJamBrowser(Mock())
    browser.page = Mock()
    outcome = await browser.draw({'baseline': {'nodes': [{'id': 'human'}], 'edges': []},
        'snapshot': {'nodes': [{'id': 'new', 'title': 'Signup'}], 'edges': []}}, AsyncMock())
    assert outcome == 'unsupported_edit'
    browser.page.keyboard.press.assert_not_called()


@pytest.mark.asyncio
async def test_navigation_to_login_disables_presentation():
    browser = FigJamBrowser(Mock())
    browser.file_url = 'https://www.figma.com/board/ABCdef123456'
    browser.page = Mock(url='https://www.figma.com/login')
    assert await browser.frame() is None
    browser.page.locator.assert_not_called()


def test_canonical_url_rejects_other_products_credentials_and_hosts():
    assert canonical('https://www.figma.com/board/ABCdef123456/name?node-id=1') == 'https://www.figma.com/board/ABCdef123456'
    for url in ['https://www.figma.com/design/ABCdef123456', 'https://user@www.figma.com/board/ABCdef123456',
                'https://www.figma.com.evil.test/board/ABCdef123456', 'javascript:alert(1)']:
        assert canonical(url) is None
