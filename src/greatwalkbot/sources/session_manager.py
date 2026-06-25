"""Playwright browser session lifecycle management."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from playwright.sync_api import Browser, Page, Playwright, Route, sync_playwright

from greatwalkbot.constants import DEFAULT_USER_AGENT, GW_FACILITY_PATH
from greatwalkbot.infra.errors import FetchError, SessionError

logger = logging.getLogger(__name__)


class SessionManager:
    """Owns Playwright browser lifecycle for long-running watch mode."""

    def __init__(self, *, headless: bool = True, timeout_ms: int = 120_000) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None
        self._current_request_body: dict[str, Any] | None = None
        self._captured_payload: dict | None = None

    @property
    def page(self) -> Page:
        self._ensure_started()
        assert self._page is not None
        return self._page

    def start(self) -> None:
        if self._browser is not None:
            return
        logger.info("Starting Playwright browser session (headless=%s)", self.headless)
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page(
            viewport={"width": 1400, "height": 900},
            user_agent=DEFAULT_USER_AGENT,
        )
        self._wire_page_handlers()

    def restart(self) -> None:
        logger.warning("Restarting Playwright browser session")
        self.close()
        self.start()

    def close(self) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                logger.exception("Error closing browser")
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                logger.exception("Error stopping Playwright")
        self._browser = None
        self._playwright = None
        self._page = None
        self._captured_payload = None
        self._current_request_body = None

    def is_healthy(self) -> bool:
        if self._browser is None or self._page is None:
            return False
        try:
            return self._browser.is_connected()
        except Exception:
            return False

    def prepare_fetch(self, request_body: dict[str, Any]) -> None:
        self._ensure_started()
        self._current_request_body = request_body
        self._captured_payload = None

    def captured_payload(self) -> dict | None:
        return self._captured_payload

    def wait_for_capture(self, timeout_ms: int) -> dict:
        """Wait up to timeout_ms for a greatwalkplacefacility JSON response."""
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            payload = self._captured_payload
            if payload is not None:
                return payload
            if self._page is not None:
                self._page.wait_for_timeout(100)
            else:
                time.sleep(0.1)
        raise FetchError(
            "No availability data captured within "
            f"{timeout_ms}ms. AWS WAF may have blocked the session; retry with --headed."
        )

    def _ensure_started(self) -> None:
        if not self.is_healthy():
            raise SessionError("Browser session is not available")

    def _wire_page_handlers(self) -> None:
        assert self._page is not None
        page = self._page
        page._gwbot_console_messages = []  # type: ignore[attr-defined]
        page._gwbot_page_errors = []  # type: ignore[attr-defined]

        def on_console(msg) -> None:
            page._gwbot_console_messages.append(  # type: ignore[attr-defined]
                f"{msg.type}: {msg.text}"[:500]
            )

        def on_page_error(exc) -> None:
            page._gwbot_page_errors.append(str(exc)[:500])  # type: ignore[attr-defined]

        def on_response(response) -> None:
            if GW_FACILITY_PATH not in response.url or response.status != 200:
                return
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                return
            try:
                self._captured_payload = response.json()
            except json.JSONDecodeError:
                return

        def rewrite_facility_post(route: Route) -> None:
            if route.request.method != "POST":
                route.continue_()
                return
            if self._current_request_body is None:
                route.continue_()
                return
            headers = {
                **route.request.headers,
                "content-type": "application/json; charset=utf-8",
            }
            route.continue_(
                headers=headers,
                post_data=json.dumps(self._current_request_body),
            )

        self._page.route(f"**/{GW_FACILITY_PATH}", rewrite_facility_post)
        page.on("console", on_console)
        page.on("pageerror", on_page_error)
        self._page.on("response", on_response)
