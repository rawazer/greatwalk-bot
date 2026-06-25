"""Playwright-backed availability source using a real browser session."""

from __future__ import annotations

import logging
import time
from datetime import date

from greatwalkbot.itinerary_form import itinerary_form_nights
from greatwalkbot.track_itineraries import has_itinerary_definition
from greatwalkbot.infra.errors import RetryableError, SessionError
from greatwalkbot.models import AvailabilitySnapshot, Track
from greatwalkbot.parsing import build_gw_facility_request, parse_gw_facility_response
from greatwalkbot.sources.diagnostics import save_session_failure_diagnostics
from greatwalkbot.sources.fetch_timing import TrackFetchTiming
from greatwalkbot.sources.session_manager import SessionManager
from greatwalkbot.sources.spa_navigation import (
    ensure_great_walk_session_ready,
    commit_track_selection,
)
from greatwalkbot.sources.spa_timing import (
    DEFAULT_APP_READY_TIMEOUT_MS,
    DEFAULT_CAPTURE_TIMEOUT_MS,
    DEFAULT_NAVIGATION_TIMEOUT_MS,
    DEFAULT_SELECTION_COMMIT_TIMEOUT_MS,
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
        selection_commit_timeout_ms: int = DEFAULT_SELECTION_COMMIT_TIMEOUT_MS,
        session_manager: SessionManager | None = None,
        metrics: object | None = None,
        people_size: int = 2,
    ) -> None:
        self.headless = headless
        self.navigation_timeout_ms = navigation_timeout_ms
        self.app_ready_timeout_ms = app_ready_timeout_ms
        self.capture_timeout_ms = capture_timeout_ms
        self.selection_commit_timeout_ms = selection_commit_timeout_ms
        self._session = session_manager
        self._metrics = metrics
        self._owns_session = session_manager is None
        self.people_size = people_size
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
                snapshot, timing = self._fetch_once(
                    track,
                    from_date,
                    to_date,
                    attempt=attempt,
                    session_restarted=attempt > 1,
                )
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
                    network_timeline=self._session.network.timeline_dicts(),
                    form_state=self._session.last_form_state,
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
        *,
        attempt: int = 1,
        session_restarted: bool = False,
    ) -> tuple[AvailabilitySnapshot, TrackFetchTiming]:
        assert self._session is not None
        if not self._session.is_healthy():
            raise SessionError("Browser session is unhealthy")

        started = time.monotonic()
        recorder = self._session.network

        browser_started = time.monotonic()
        request_body = build_gw_facility_request(track, from_date, to_date)
        self._session.prepare_fetch(request_body)
        page = self._session.page
        browser_start_seconds = time.monotonic() - browser_started

        stage_timing = ensure_great_walk_session_ready(
            page,
            shell_timeout_ms=self.navigation_timeout_ms,
            spa_ready_timeout_ms=self.app_ready_timeout_ms,
            recorder=recorder,
            browser_start_seconds=browser_start_seconds,
            full_bootstrap_required=self._session.needs_full_great_walk_bootstrap,
        )
        if self._session.needs_full_great_walk_bootstrap:
            self._session.mark_great_walk_bootstrapped()

        self._session.begin_capture_cycle(place_id=track.place_id)

        transition = commit_track_selection(
            page,
            track,
            recorder,
            navigation_timeout_ms=self.navigation_timeout_ms,
            app_ready_timeout_ms=self.app_ready_timeout_ms,
            selection_commit_timeout_ms=self.selection_commit_timeout_ms,
            prior_track_slug=self._session.last_track_slug,
            attempt=attempt,
            session_restarted=session_restarted,
        )
        self._session.record_track_transition(transition)
        self._session.mark_selection_committed()

        if has_itinerary_definition(track.slug):
            form_nights, _ = itinerary_form_nights(track.slug)
        else:
            form_nights = track.fixed_nights or (to_date - from_date).days

        capture_started = time.monotonic()
        payload = self._session.capture_availability_after_search(
            track=track,
            start_date=from_date,
            nights=form_nights,
            people_size=self.people_size,
            timeout_ms=self.capture_timeout_ms,
            attempt=attempt,
            session_restarted=session_restarted,
        )
        capture_done = time.monotonic()

        timing = TrackFetchTiming(
            track_slug=track.slug,
            navigation_seconds=stage_timing.shell_navigation_seconds,
            app_ready_seconds=(
                stage_timing.route_navigation_seconds + stage_timing.spa_readiness_seconds
            ),
            capture_seconds=capture_done - capture_started,
            total_seconds=capture_done - started,
            browser_start_seconds=stage_timing.browser_start_seconds,
            shell_navigation_seconds=stage_timing.shell_navigation_seconds,
            route_navigation_seconds=stage_timing.route_navigation_seconds,
            spa_readiness_seconds=stage_timing.spa_readiness_seconds,
            navigation_recovered_after_timeout=stage_timing.navigation_recovered_after_timeout,
        )

        snapshot = parse_gw_facility_response(payload, track, from_date, to_date)
        self._session.mark_track_completed(track.slug)
        return snapshot, timing

    def reset_poll_timings(self) -> None:
        self.last_poll_track_timings = ()
