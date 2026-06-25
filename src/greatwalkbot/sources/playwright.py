"""Playwright-backed availability source using a real browser session."""

from __future__ import annotations

import logging
import time
from datetime import date

from greatwalkbot.infra.errors import FetchError, RetryableError, SessionError
from greatwalkbot.models import AvailabilitySnapshot, Track
from greatwalkbot.parsing import build_gw_facility_request, parse_gw_facility_response
from greatwalkbot.sources.diagnostics import save_session_failure_diagnostics
from greatwalkbot.sources.fetch_timing import TrackFetchTiming
from greatwalkbot.sources.session_manager import SessionManager
from greatwalkbot.sources.spa_navigation import (
    click_search_button,
    navigate_to_site,
    select_track_with_recovery,
    wait_for_great_walk_ui,
)
from greatwalkbot.sources.spa_timing import (
    DEFAULT_APP_READY_TIMEOUT_MS,
    DEFAULT_CAPTURE_TIMEOUT_MS,
    DEFAULT_NAVIGATION_TIMEOUT_MS,
    MAX_FETCH_ATTEMPTS_PER_TRACK,
)

logger = logging.getLogger(__name__)


class PlaywrightAvailabilitySource:
    """Load the DOC SPA and capture the Great Walk facility grid API.

    Per track: one fetch attempt; on retryable failure, restart the browser
    session and retry once (``MAX_FETCH_ATTEMPTS_PER_TRACK`` = 2 total).
    No nested exponential retry loops — worst-case per track is roughly
    2 × (navigation + app-ready + capture) bounded waits (~150s).
    """

    def __init__(
        self,
        headless: bool = True,
        *,
        navigation_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS,
        app_ready_timeout_ms: int = DEFAULT_APP_READY_TIMEOUT_MS,
        capture_timeout_ms: int = DEFAULT_CAPTURE_TIMEOUT_MS,
        session_manager: SessionManager | None = None,
        metrics: object | None = None,
    ) -> None:
        self.headless = headless
        self.navigation_timeout_ms = navigation_timeout_ms
        self.app_ready_timeout_ms = app_ready_timeout_ms
        self.capture_timeout_ms = capture_timeout_ms
        self._session = session_manager
        self._metrics = metrics
        self._owns_session = session_manager is None
        self.last_track_timing: TrackFetchTiming | None = None
        self.last_poll_track_timings: tuple[TrackFetchTiming, ...] = ()

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
                timeout_ms=self.navigation_timeout_ms,
            )
            self._session.start()
            created_session = True

        try:
            return self._fetch_with_session_recovery(track, from_date, to_date)
        finally:
            if created_session and self._session is not None:
                self._session.close()
                self._session = None

    def close(self) -> None:
        if self._owns_session and self._session is not None:
            self._session.close()
            self._session = None

    def _fetch_with_session_recovery(
        self,
        track: Track,
        from_date: date,
        to_date: date,
    ) -> AvailabilitySnapshot:
        assert self._session is not None
        last_exc: BaseException | None = None
        page = None

        for attempt in range(1, MAX_FETCH_ATTEMPTS_PER_TRACK + 1):
            try:
                snapshot, timing = self._fetch_once(track, from_date, to_date)
                self.last_track_timing = timing
                self.last_poll_track_timings = (*self.last_poll_track_timings, timing)
                logger.info("Fetch timing: %s", timing.log_line())
                return snapshot
            except RetryableError as exc:
                last_exc = exc
                page = self._session.page if self._session.is_healthy() else None
                save_session_failure_diagnostics(
                    page=page,
                    track_name=track.name,
                    track_slug=track.slug,
                    error=exc,
                )
                if attempt >= MAX_FETCH_ATTEMPTS_PER_TRACK:
                    break
                logger.warning(
                    "Retryable fetch failure for %s (attempt %s/%s): %s; "
                    "restarting browser session",
                    track.slug,
                    attempt,
                    MAX_FETCH_ATTEMPTS_PER_TRACK,
                    exc,
                )
                self._session.restart()
                if self._metrics is not None and hasattr(
                    self._metrics, "record_browser_restart"
                ):
                    self._metrics.record_browser_restart()

        assert last_exc is not None
        raise last_exc

    def _fetch_once(
        self,
        track: Track,
        from_date: date,
        to_date: date,
    ) -> tuple[AvailabilitySnapshot, TrackFetchTiming]:
        assert self._session is not None
        if not self._session.is_healthy():
            raise SessionError("Browser session is unhealthy")

        started = time.monotonic()

        request_body = build_gw_facility_request(track, from_date, to_date)
        self._session.prepare_fetch(request_body)
        page = self._session.page

        nav_t0 = time.monotonic()
        from greatwalkbot.constants import GREATWALK_HASH

        navigate_to_site(page, timeout_ms=self.navigation_timeout_ms)
        nav_t1 = time.monotonic()
        page.evaluate(f"window.location.hash = '{GREATWALK_HASH}'")
        wait_for_great_walk_ui(page, timeout_ms=self.app_ready_timeout_ms)
        app_t1 = time.monotonic()

        select_track_with_recovery(
            page,
            track,
            navigation_timeout_ms=self.navigation_timeout_ms,
            app_ready_timeout_ms=self.app_ready_timeout_ms,
        )

        click_search_button(page)
        capture_started = time.monotonic()
        payload = self._session.wait_for_capture(self.capture_timeout_ms)
        capture_done = time.monotonic()

        timing = TrackFetchTiming(
            track_slug=track.slug,
            navigation_seconds=nav_t1 - nav_t0,
            app_ready_seconds=app_t1 - nav_t1,
            capture_seconds=capture_done - capture_started,
            total_seconds=capture_done - started,
        )

        snapshot = parse_gw_facility_response(payload, track, from_date, to_date)
        return snapshot, timing

    def reset_poll_timings(self) -> None:
        self.last_poll_track_timings = ()
