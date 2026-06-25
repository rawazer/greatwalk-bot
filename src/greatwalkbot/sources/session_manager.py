"""Playwright browser session lifecycle management."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from playwright.sync_api import Browser, Page, Playwright, Route, sync_playwright

from greatwalkbot.constants import DEFAULT_USER_AGENT, GW_FACILITY_PATH
from greatwalkbot.infra.errors import SessionError
from greatwalkbot.models import Track
from greatwalkbot.sources.availability_capture import (
    CaptureLifecycle,
    classify_capture_failure,
    wait_for_availability_response,
)
from greatwalkbot.sources.network_recorder import (
    NetworkRecorder,
    response_body_is_availability_payload,
)
from greatwalkbot.sources.search_form import (
    dispatch_great_walk_search_click,
    prepare_great_walk_search,
)

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
        self._network = NetworkRecorder()
        self._selection_committed = False
        self._search_submitted = False
        self._last_form_state: dict[str, Any] | None = None
        self._console_handler: Any | None = None
        self._page_error_handler: Any | None = None
        self._facility_response_handler: Any | None = None

    @property
    def page(self) -> Page:
        self._ensure_started()
        assert self._page is not None
        return self._page

    @property
    def network(self) -> NetworkRecorder:
        return self._network

    @property
    def last_form_state(self) -> dict[str, Any] | None:
        return self._last_form_state

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
        if self._page is not None:
            self._detach_page_handlers(self._page)
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
        self._network = NetworkRecorder()
        self._selection_committed = False
        self._search_submitted = False
        self._last_form_state = None
        self._console_handler = None
        self._page_error_handler = None
        self._facility_response_handler = None

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
        self._selection_committed = False
        self._search_submitted = False
        self._last_form_state = None

    def begin_capture_cycle(self, *, place_id: int) -> None:
        """Reset per-track capture state before selection/search actions."""
        self._captured_payload = None
        self._selection_committed = False
        self._search_submitted = False
        self._last_form_state = None
        self._network.begin_cycle(place_id=place_id)

    def mark_selection_committed(self) -> None:
        self._selection_committed = True

    def captured_payload(self) -> dict | None:
        return self._captured_payload

    def capture_availability_after_search(
        self,
        *,
        track: Track,
        start_date: date,
        nights: int,
        people_size: int,
        timeout_ms: int,
        attempt: int = 1,
        session_restarted: bool = False,
    ) -> dict:
        """Prepare form, register response waiter, click Search, capture availability."""
        assert self._page is not None
        lifecycle: CaptureLifecycle | None = None
        try:
            self._last_form_state = prepare_great_walk_search(
                self._page,
                track,
                start_date=start_date,
                nights=nights,
                people_size=people_size,
            )
            payload, lifecycle = wait_for_availability_response(
                self._page,
                click_search=lambda: self._dispatch_search_click(track),
                timeout_ms=timeout_ms,
                recorder=self._network,
                attempt=attempt,
                session_restarted=session_restarted,
            )
            self._captured_payload = payload
            return payload
        except Exception as exc:
            page_html = None
            try:
                page_html = self._page.content()
            except Exception:
                pass
            from greatwalkbot.infra.errors import (
                AvailabilityRequestFailedError,
                SearchFormValidationError,
            )

            if isinstance(exc, (AvailabilityRequestFailedError, SearchFormValidationError)):
                if lifecycle is not None:
                    lifecycle.session_restarted = session_restarted
                if isinstance(exc, AvailabilityRequestFailedError) and exc.capture_lifecycle is None:
                    exc.capture_lifecycle = (
                        lifecycle.to_dict() if lifecycle is not None else None
                    )
                raise
            raise classify_capture_failure(
                self._network,
                selection_committed=self._selection_committed,
                search_submitted=self._search_submitted,
                place_id=self._current_request_body.get("placeId")
                if self._current_request_body
                else 0,
                timeout_ms=timeout_ms,
                page_html=page_html,
                form_state=self._last_form_state,
                capture_lifecycle=lifecycle,
                attempt=attempt,
            ) from exc

    def _dispatch_search_click(self, track: Track) -> None:
        assert self._page is not None
        transition = dispatch_great_walk_search_click(
            self._page,
            self._network,
            track,
        )
        self._search_submitted = True
        if self._last_form_state is not None:
            self._last_form_state = {
                **self._last_form_state,
                "search_click_transition": transition,
            }

    def _ensure_started(self) -> None:
        if not self.is_healthy():
            raise SessionError("Browser session is not available")

    def _detach_page_handlers(self, page: Page) -> None:
        self._network.detach(page)
        if self._console_handler is not None:
            try:
                page.remove_listener("console", self._console_handler)
            except Exception:
                pass
        if self._page_error_handler is not None:
            try:
                page.remove_listener("pageerror", self._page_error_handler)
            except Exception:
                pass
        if self._facility_response_handler is not None:
            try:
                page.remove_listener("response", self._facility_response_handler)
            except Exception:
                pass
        try:
            page.unroute(f"**/{GW_FACILITY_PATH}")
        except Exception:
            pass

    def _wire_page_handlers(self) -> None:
        assert self._page is not None
        page = self._page
        page._gwbot_console_messages = []  # type: ignore[attr-defined]
        page._gwbot_page_errors = []  # type: ignore[attr-defined]

        self._network.attach(page)

        def on_console(msg) -> None:
            page._gwbot_console_messages.append(  # type: ignore[attr-defined]
                f"{msg.type}: {msg.text}"[:500]
            )

        def on_page_error(exc) -> None:
            page._gwbot_page_errors.append(str(exc)[:500])  # type: ignore[attr-defined]

        def on_response(response) -> None:
            if GW_FACILITY_PATH not in response.url:
                return
            if response.status != 200:
                return
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                return
            try:
                data = response.json()
            except json.JSONDecodeError:
                return
            if response_body_is_availability_payload(data):
                self._captured_payload = data

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

        self._console_handler = on_console
        self._page_error_handler = on_page_error
        self._facility_response_handler = on_response

        self._page.route(f"**/{GW_FACILITY_PATH}", rewrite_facility_post)
        page.on("console", self._console_handler)
        page.on("pageerror", self._page_error_handler)
        self._page.on("response", self._facility_response_handler)
