"""Tests for SessionManager lifecycle."""

from unittest.mock import MagicMock, patch

import pytest

from greatwalkbot.infra.errors import SessionError
from greatwalkbot.sources.session_manager import SessionManager


@pytest.fixture
def mock_playwright():
    browser = MagicMock()
    browser.is_connected.return_value = True
    page = MagicMock()
    browser.new_page.return_value = page

    playwright = MagicMock()
    playwright.chromium.launch.return_value = browser

    manager = MagicMock()
    manager.start.return_value = playwright
    return manager, playwright, browser, page


def test_session_manager_start_and_close(mock_playwright):
    manager_ctx, playwright, browser, page = mock_playwright

    with patch("greatwalkbot.sources.session_manager.sync_playwright", return_value=manager_ctx):
        session = SessionManager(headless=True)
        session.start()

        assert session.is_healthy()
        assert session.page is page

        session.close()
        browser.close.assert_called_once()
        playwright.stop.assert_called_once()


def test_session_manager_restart(mock_playwright):
    manager_ctx, playwright, browser, page = mock_playwright

    with patch("greatwalkbot.sources.session_manager.sync_playwright", return_value=manager_ctx):
        session = SessionManager(headless=True)
        session.start()
        session.restart()

        assert browser.close.call_count == 1
        assert playwright.chromium.launch.call_count == 2


def test_page_raises_when_not_started():
    session = SessionManager()
    with pytest.raises(SessionError, match="not available"):
        _ = session.page


def test_prepare_fetch_clears_payload(mock_playwright):
    manager_ctx, _playwright, _browser, page = mock_playwright

    with patch("greatwalkbot.sources.session_manager.sync_playwright", return_value=manager_ctx):
        session = SessionManager()
        session.start()
        session._captured_payload = {"old": True}
        session.prepare_fetch({"placeId": 1})

        assert session._captured_payload is None
        assert session._current_request_body == {"placeId": 1}
        page.route.assert_called_once()
