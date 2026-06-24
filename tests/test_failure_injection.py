"""Deterministic failure-injection tests for watcher recovery."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.plan import TripPlan
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.domain.trip import Trip
from greatwalkbot.infra.errors import FetchError
from greatwalkbot.infra.retry import RetryPolicy, retry_call
from greatwalkbot.infra.shutdown import ShutdownController
from greatwalkbot.models import AvailabilityDay, AvailabilitySnapshot, AvailabilityStatus, Track
from greatwalkbot.monitoring.dedupe import SqliteSeenAvailabilityStore
from greatwalkbot.monitoring.metrics import RuntimeMetrics
from greatwalkbot.monitoring.models import AvailableItinerary
from greatwalkbot.monitoring.watcher import Watcher
from greatwalkbot.notifications.console import ConsoleNotifier
from greatwalkbot.sources.playwright import PlaywrightAvailabilitySource

MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)


def _snapshot() -> AvailabilitySnapshot:
    return AvailabilitySnapshot(
        track=MILFORD,
        from_date=date(2026, 12, 1),
        to_date=date(2026, 12, 31),
        days=(
            AvailabilityDay(
                date(2026, 12, 7),
                AvailabilityStatus.AVAILABLE,
                5,
                ("Clinton Hut",),
            ),
        ),
    )


def _plan(**kwargs) -> TripPlan:
    trip = Trip(
        name="Test Trip",
        party=Party(adults=2),
        travel_window=TravelWindow(date(2026, 12, 1), date(2026, 12, 31)),
        tracks=(
            TrackPreference(
                slug="milford",
                acceptable_start_range=DateRange(date(2026, 12, 1), date(2026, 12, 31)),
                preferred_start_dates=(date(2026, 12, 7),),
            ),
        ),
    )
    return TripPlan(trip=trip, polling_interval_seconds=60, **kwargs)


def _watcher(source, *, metrics=None, shutdown=None, seen_store=None, sleeper=None) -> Watcher:
    return Watcher(
        _plan(),
        source,
        ConsoleNotifier(),
        resolve_track_fn=lambda slug: MILFORD,
        metrics=metrics,
        shutdown=shutdown or ShutdownController(),
        seen_store=seen_store,
        sleeper=sleeper,
    )


class FailThenSucceedSource:
    """Fails the first poll cycle entirely, then succeeds on later cycles."""

    def __init__(self) -> None:
        self.calls = 0

    def fetch_track_availability(self, track, from_date, to_date):
        self.calls += 1
        if self.calls == 1:
            raise FetchError("session dead after recovery")
        return _snapshot()


class ShutdownDuringPollSource:
    def __init__(self, shutdown: ShutdownController) -> None:
        self.shutdown = shutdown
        self.calls = 0

    def fetch_track_availability(self, track, from_date, to_date):
        self.calls += 1
        self.shutdown.request_shutdown()
        return _snapshot()


def test_transient_source_failure_succeeds_after_retry(tmp_path):
    """Retry policy recovers from a transient error without watcher involvement."""
    attempts = {"count": 0}
    sleeps: list[float] = []

    def fn():
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise FetchError("transient")
        return "ok"

    result = retry_call(
        fn,
        RetryPolicy(max_attempts=3, base_delay_seconds=1.0),
        sleep_fn=sleeps.append,
    )

    assert result == "ok"
    assert attempts["count"] == 2
    assert len(sleeps) == 1


def test_non_retryable_error_fails_immediately():
    attempts = {"count": 0}

    def fn():
        attempts["count"] += 1
        raise ValueError("bad config")

    with pytest.raises(ValueError, match="bad config"):
        retry_call(
            fn,
            RetryPolicy(max_attempts=3, base_delay_seconds=0.01),
            sleep_fn=lambda _s: None,
        )
    assert attempts["count"] == 1


def test_browser_restart_then_success():
    session = MagicMock()
    session.is_healthy.return_value = True
    snapshot = _snapshot()

    source = PlaywrightAvailabilitySource(
        session_manager=session,
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.01),
    )

    calls = {"count": 0}

    def fetch_once(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise FetchError("browser session lost")
        return snapshot

    with patch.object(source, "_fetch_once", side_effect=fetch_once):
        with patch("greatwalkbot.sources.playwright.retry_call", side_effect=lambda fn, _p: fn()):
            result = source.fetch_track_availability(
                MILFORD, date(2026, 12, 1), date(2026, 12, 31)
            )

    assert result is snapshot
    session.restart.assert_called_once()
    assert calls["count"] == 2


def test_failed_poll_recorded_without_stopping_future_cycles(tmp_path):
    status_path = tmp_path / "status.json"
    metrics = RuntimeMetrics(status_path=status_path, trip_name="Test Trip")
    source = FailThenSucceedSource()
    watcher = _watcher(source, metrics=metrics)

    watcher.run_once()
    watcher.run_once()

    assert source.calls == 2
    loaded = RuntimeMetrics.load(status_path)
    assert loaded is not None
    assert loaded.failed_polls == 1
    assert loaded.successful_polls == 1
    assert loaded.last_error is not None
    assert "session dead" in loaded.last_error.message


def test_persistent_dedupe_survives_store_recreation(tmp_path):
    db_path = tmp_path / "seen.db"
    itinerary = AvailableItinerary(
        track_slug="milford",
        track_name="Milford Track",
        start_date=date(2026, 12, 7),
        spaces=4,
        facilities=("Clinton Hut",),
        preference="preferred",
    )

    store = SqliteSeenAvailabilityStore(db_path)
    store.mark_seen(itinerary)
    store.close()

    recreated = SqliteSeenAvailabilityStore(db_path)
    notifications: list[str] = []

    class RecordingNotifier(ConsoleNotifier):
        def notify_new_availability(self, it):
            notifications.append(it.start_date.isoformat())

    source = MagicMock()
    source.fetch_track_availability.return_value = _snapshot()

    watcher = _watcher(source, seen_store=recreated, metrics=None)
    watcher.notifier = RecordingNotifier()
    watcher.run_once()

    assert notifications == []
    recreated.close()


def test_graceful_shutdown_while_idle():
    shutdown = ShutdownController()
    shutdown.request_shutdown()
    source = MagicMock()

    watcher = _watcher(source, shutdown=shutdown)
    watcher.run_forever()

    source.fetch_track_availability.assert_not_called()


def test_graceful_shutdown_during_poll_finishes_current_cycle():
    shutdown = ShutdownController()
    source = ShutdownDuringPollSource(shutdown)
    sleeps: list[float] = []

    watcher = _watcher(source, shutdown=shutdown, sleeper=sleeps.append)
    watcher.run_forever()

    assert source.calls == 1
    assert shutdown.shutdown_requested
