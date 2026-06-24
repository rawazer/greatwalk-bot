"""Tests for composite notifier and watcher resilience."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.notifications import NotificationConfig
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.plan import TripPlan
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.domain.trip import Trip
from greatwalkbot.models import AvailabilityDay, AvailabilitySnapshot, AvailabilityStatus, Track
from greatwalkbot.monitoring.metrics import RuntimeMetrics
from greatwalkbot.monitoring.models import AvailableItinerary
from greatwalkbot.monitoring.watcher import Watcher
from greatwalkbot.notifications.composite import CompositeNotifier
from greatwalkbot.notifications.console import ConsoleNotifier
from greatwalkbot.notifications.errors import TelegramDeliveryError

MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)


class FailingTelegramNotifier:
    def notify_new_availability(self, itinerary):
        raise TelegramDeliveryError("network down")


class OkTelegramNotifier:
    def __init__(self):
        self.sent: list[str] = []

    def notify_new_availability(self, itinerary):
        self.sent.append(itinerary.start_date.isoformat())


def _plan() -> TripPlan:
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
    return TripPlan(trip=trip, polling_interval_seconds=60)


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


class SingleSnapshotSource:
    def fetch_track_availability(self, track, from_date, to_date):
        return _snapshot()


def test_composite_notifier_delivers_to_both_channels():
    ok = OkTelegramNotifier()
    notifier = CompositeNotifier((ConsoleNotifier(party_size=2), ok))
    itinerary = AvailableItinerary(
        track_slug="milford",
        track_name="Milford Track",
        start_date=date(2026, 12, 7),
        spaces=5,
        facilities=("Clinton Hut",),
        preference="preferred",
    )
    notifier.notify_new_availability(itinerary)
    assert ok.sent == ["2026-12-07"]


def test_telegram_failure_does_not_stop_other_notifiers(tmp_path):
    metrics = RuntimeMetrics(status_path=tmp_path / "status.json")
    ok = OkTelegramNotifier()
    notifier = CompositeNotifier(
        (ConsoleNotifier(party_size=2), FailingTelegramNotifier(), ok),
        metrics=metrics,
    )
    itinerary = AvailableItinerary(
        track_slug="milford",
        track_name="Milford Track",
        start_date=date(2026, 12, 7),
        spaces=5,
        facilities=("Clinton Hut",),
        preference="preferred",
    )
    notifier.notify_new_availability(itinerary)

    loaded = RuntimeMetrics.load(tmp_path / "status.json")
    assert loaded is not None
    assert loaded.last_notification_error is not None
    assert "network down" in loaded.last_notification_error.message
    assert ok.sent == ["2026-12-07"]


def test_watcher_continues_after_telegram_failure(tmp_path):
    metrics = RuntimeMetrics(status_path=tmp_path / "status.json")
    notifier = CompositeNotifier(
        (FailingTelegramNotifier(),),
        metrics=metrics,
    )
    source = SingleSnapshotSource()
    watcher = Watcher(
        _plan(),
        source,
        notifier,
        resolve_track_fn=lambda slug: MILFORD,
        metrics=metrics,
    )

    watcher.run_once()
    watcher.run_once()

    loaded = RuntimeMetrics.load(tmp_path / "status.json")
    assert loaded is not None
    assert loaded.successful_polls == 2
    assert loaded.last_notification_error is not None
