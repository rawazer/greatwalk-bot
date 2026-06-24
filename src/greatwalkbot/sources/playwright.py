"""Playwright-backed availability source using a real browser session."""

from __future__ import annotations

import logging
from datetime import date

from playwright.sync_api import Page

from greatwalkbot.constants import GREATWALK_HASH, SITE_URL
from greatwalkbot.infra.errors import FetchError, SessionError
from greatwalkbot.infra.retry import RetryPolicy, is_retryable, retry_call
from greatwalkbot.models import AvailabilitySnapshot, Track
from greatwalkbot.parsing import build_gw_facility_request, parse_gw_facility_response
from greatwalkbot.sources.session_manager import SessionManager

logger = logging.getLogger(__name__)


class PlaywrightAvailabilitySource:
    """Load the DOC SPA and capture the Great Walk facility grid API."""

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 120_000,
        *,
        session_manager: SessionManager | None = None,
        retry_policy: RetryPolicy | None = None,
        metrics: object | None = None,
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._session = session_manager
        self._retry_policy = retry_policy or RetryPolicy()
        self._metrics = metrics
        self._owns_session = session_manager is None

    def fetch_track_availability(
        self,
        track: Track,
        from_date: date,
        to_date: date,
    ) -> AvailabilitySnapshot:
        created_session = False
        if self._session is None:
            self._session = SessionManager(
                headless=self.headless,
                timeout_ms=self.timeout_ms,
            )
            self._session.start()
            created_session = True

        try:
            return self._fetch_with_recovery(track, from_date, to_date)
        finally:
            if created_session and self._session is not None:
                self._session.close()
                self._session = None

    def close(self) -> None:
        if self._owns_session and self._session is not None:
            self._session.close()
            self._session = None

    def _fetch_with_recovery(
        self,
        track: Track,
        from_date: date,
        to_date: date,
    ) -> AvailabilitySnapshot:
        assert self._session is not None
        try:
            return retry_call(
                lambda: self._fetch_once(track, from_date, to_date),
                self._retry_policy,
            )
        except Exception as exc:
            if not is_retryable(exc):
                raise
            logger.warning(
                "Fetch failed after retries for %s; restarting browser session",
                track.slug,
            )
            self._session.restart()
            if self._metrics is not None and hasattr(self._metrics, "record_browser_restart"):
                self._metrics.record_browser_restart()
            return self._fetch_once(track, from_date, to_date)

    def _fetch_once(
        self,
        track: Track,
        from_date: date,
        to_date: date,
    ) -> AvailabilitySnapshot:
        assert self._session is not None
        if not self._session.is_healthy():
            raise SessionError("Browser session is unhealthy")

        request_body = build_gw_facility_request(track, from_date, to_date)
        self._session.prepare_fetch(request_body)
        page = self._session.page

        page.goto(SITE_URL, wait_until="networkidle", timeout=self.timeout_ms)
        page.wait_for_timeout(3000)
        page.evaluate(f"window.location.hash = '{GREATWALK_HASH}'")
        page.wait_for_timeout(8000)

        self._select_track(page, track)
        page.wait_for_timeout(2000)
        self._click_search(page)
        page.wait_for_timeout(15000)

        payload = self._session.captured_payload()
        if payload is None:
            raise FetchError(
                "No availability data captured. AWS WAF may have blocked the session; "
                "retry with --headed."
            )

        return parse_gw_facility_response(payload, track, from_date, to_date)

    @staticmethod
    def _select_track(page: Page, track: Track) -> None:
        element_id = track.dropdown_element_id
        clicked = page.evaluate(
            f"() => {{ const el = document.getElementById('{element_id}'); if (el) el.click(); return !!el; }}"
        )
        if not clicked:
            raise RuntimeError(f"Could not select track dropdown item #{element_id}")

    @staticmethod
    def _click_search(page: Page) -> None:
        clicked = page.evaluate(
            """() => {
                const btn = Array.from(document.querySelectorAll('button'))
                    .find(b => b.textContent.trim() === 'Search' && b.offsetParent);
                if (btn) { btn.click(); return true; }
                return false;
            }"""
        )
        if not clicked:
            raise RuntimeError("Could not find the Great Walk Search button on the page")
