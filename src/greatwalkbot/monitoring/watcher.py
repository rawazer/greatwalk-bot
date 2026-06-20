"""Long-running availability watch loop."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone

from greatwalkbot.config.models import WatchConfig
from greatwalkbot.models import Track
from greatwalkbot.monitoring.dedupe import SeenAvailabilityStore
from greatwalkbot.monitoring.matcher import find_matching_itineraries
from greatwalkbot.monitoring.models import TrackCheckResult, WatchCycleResult
from greatwalkbot.notifications.protocol import Notifier
from greatwalkbot.sources.protocol import AvailabilitySource
from greatwalkbot.tracks import resolve_track

LogFn = Callable[[str], None]


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_check(
    logger: LogFn,
    track_name: str,
    from_date,
    to_date,
    match_count: int,
    new_count: int,
) -> None:
    logger(
        f"{_timestamp()} [check] {track_name} {from_date.isoformat()}..{to_date.isoformat()}: "
        f"{match_count} match(es), {new_count} new"
    )


class Watcher:
    """Poll availability and notify when new matching itineraries appear."""

    def __init__(
        self,
        config: WatchConfig,
        source: AvailabilitySource,
        notifier: Notifier,
        *,
        resolve_track_fn=resolve_track,
        logger: LogFn | None = None,
        seen_store: SeenAvailabilityStore | None = None,
    ) -> None:
        self.config = config
        self.source = source
        self.notifier = notifier
        self._resolve_track = resolve_track_fn
        self._logger = logger or (lambda msg: print(msg, file=sys.stdout, flush=True))
        self._seen = seen_store or SeenAvailabilityStore()
        self._track_cache: dict[str, Track] = {}

    def _get_track(self, slug: str) -> Track:
        if slug not in self._track_cache:
            track = self._resolve_track(slug)
            self._track_cache[slug] = track
        return self._track_cache[slug]

    def run_once(self) -> WatchCycleResult:
        track_results: list[TrackCheckResult] = []

        for track_config in self.config.tracks:
            track = self._get_track(track_config.slug)
            bounds = track_config.query_bounds()

            try:
                snapshot = self.source.fetch_track_availability(
                    track,
                    bounds.from_date,
                    bounds.to_date,
                )
            except Exception as exc:
                self._logger(
                    f"{_timestamp()} [error] {track.name}: {exc}"
                )
                continue

            matches = find_matching_itineraries(
                snapshot,
                track_config,
                self.config.party_size,
            )
            new_matches = self._seen.filter_new(matches)

            _log_check(
                self._logger,
                track.name,
                bounds.from_date,
                bounds.to_date,
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
                    from_date=bounds.from_date,
                    to_date=bounds.to_date,
                    matches=matches,
                    new_matches=new_matches,
                )
            )

        return WatchCycleResult(
            checked_at=datetime.now(timezone.utc),
            track_results=tuple(track_results),
        )

    def run_forever(self) -> None:
        self._logger(
            f"{_timestamp()} [watch] started "
            f"(interval={self.config.polling_interval_seconds}s, "
            f"party_size={self.config.party_size}, tracks={len(self.config.tracks)})"
        )
        try:
            while True:
                self.run_once()
                time.sleep(self.config.polling_interval_seconds)
        except KeyboardInterrupt:
            self._logger(f"{_timestamp()} [watch] stopped")
