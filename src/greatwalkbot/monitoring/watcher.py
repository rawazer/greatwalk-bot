"""Long-running availability watch loop."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from greatwalkbot.domain.plan import TripPlan
from greatwalkbot.infra.shutdown import ShutdownController
from greatwalkbot.models import Track
from greatwalkbot.monitoring.dedupe import SeenAvailabilityStore, SeenStore
from greatwalkbot.monitoring.matcher import find_matching_itineraries
from greatwalkbot.monitoring.metrics import RuntimeMetrics
from greatwalkbot.monitoring.models import TrackCheckResult, WatchCycleResult
from greatwalkbot.notifications.protocol import Notifier
from greatwalkbot.sources.protocol import AvailabilitySource
from greatwalkbot.tracks import resolve_track

logger = logging.getLogger(__name__)


class Watcher:
    """Poll availability and notify when new matching itineraries appear."""

    def __init__(
        self,
        plan: TripPlan,
        source: AvailabilitySource,
        notifier: Notifier,
        *,
        resolve_track_fn=resolve_track,
        seen_store: SeenStore | None = None,
        metrics: RuntimeMetrics | None = None,
        shutdown: ShutdownController | None = None,
    ) -> None:
        self.plan = plan
        self.source = source
        self.notifier = notifier
        self._resolve_track = resolve_track_fn
        self._seen: SeenStore = seen_store or SeenAvailabilityStore()
        self._metrics = metrics
        self._shutdown = shutdown or ShutdownController()
        self._track_cache: dict[str, Track] = {}

    def _get_track(self, slug: str) -> Track:
        if slug not in self._track_cache:
            track = self._resolve_track(slug)
            self._track_cache[slug] = track
        return self._track_cache[slug]

    def run_once(self) -> WatchCycleResult:
        poll_started = self._metrics.record_poll_start() if self._metrics else None
        track_results: list[TrackCheckResult] = []
        trip = self.plan.trip
        poll_failed = False

        for track_preference in trip.tracks:
            if self._shutdown.shutdown_requested:
                break

            track = self._get_track(track_preference.slug)
            bounds = track_preference.query_bounds(trip.travel_window)

            try:
                snapshot = self.source.fetch_track_availability(
                    track,
                    bounds.start,
                    bounds.end,
                )
            except Exception:
                poll_failed = True
                logger.exception(
                    "Failed to fetch availability for %s (%s..%s)",
                    track.name,
                    bounds.start.isoformat(),
                    bounds.end.isoformat(),
                )
                continue

            matches = find_matching_itineraries(
                snapshot,
                track_preference,
                trip.party,
                trip.travel_window,
            )
            new_matches = self._seen.filter_new(matches)

            logger.info(
                "Checked %s %s..%s: %s match(es), %s new",
                track.name,
                bounds.start.isoformat(),
                bounds.end.isoformat(),
                len(matches),
                len(new_matches),
            )

            for itinerary in new_matches:
                self.notifier.notify_new_availability(itinerary)
                self._seen.mark_seen(itinerary)

            track_results.append(
                TrackCheckResult(
                    track_slug=track.slug,
                    track_name=track.name,
                    from_date=bounds.start,
                    to_date=bounds.end,
                    matches=matches,
                    new_matches=new_matches,
                )
            )

        result = WatchCycleResult(
            checked_at=datetime.now(timezone.utc),
            track_results=tuple(track_results),
        )

        if self._metrics is not None and poll_started is not None:
            if poll_failed and not track_results:
                self._metrics.record_poll_failure(poll_started)
            else:
                self._metrics.record_poll_success(poll_started)

        return result

    def run_forever(self) -> None:
        trip = self.plan.trip
        self._shutdown.install_handlers()
        logger.info(
            "Watch started trip=%r interval=%ss party_size=%s tracks=%s",
            trip.name,
            self.plan.polling_interval_seconds,
            trip.party.size,
            len(trip.tracks),
        )
        try:
            while not self._shutdown.shutdown_requested:
                self.run_once()
                if self._shutdown.shutdown_requested:
                    break
                self._interruptible_sleep(self.plan.polling_interval_seconds)
        finally:
            logger.info("Watch stopped")
            if self._metrics is not None:
                self._metrics.flush()

    def _interruptible_sleep(self, seconds: int) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._shutdown.shutdown_requested:
                return
            time.sleep(min(1.0, deadline - time.monotonic()))
