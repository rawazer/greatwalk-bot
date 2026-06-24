"""Tests for graceful shutdown behaviour."""

from datetime import date
from unittest.mock import patch

from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.plan import TripPlan
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.domain.trip import Trip
from greatwalkbot.infra.shutdown import ShutdownController
from greatwalkbot.models import AvailabilityDay, AvailabilitySnapshot, AvailabilityStatus, Track
from greatwalkbot.monitoring.watcher import Watcher
from greatwalkbot.notifications.console import ConsoleNotifier

MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)


class SlowSource:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_track_availability(self, track, from_date, to_date):
        self.calls += 1
        return AvailabilitySnapshot(
            track=MILFORD,
            from_date=from_date,
            to_date=to_date,
            days=(
                AvailabilityDay(
                    date(2026, 12, 7),
                    AvailabilityStatus.AVAILABLE,
                    5,
                    ("Clinton Hut",),
                ),
            ),
        )


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


def test_run_forever_exits_when_shutdown_requested():
    shutdown = ShutdownController()
    source = SlowSource()
    watcher = Watcher(
        _plan(),
        source,
        ConsoleNotifier(),
        resolve_track_fn=lambda slug: MILFORD,
        shutdown=shutdown,
    )

    with patch.object(watcher, "_interruptible_sleep", side_effect=lambda _seconds: shutdown.request_shutdown()):
        watcher.run_forever()

    assert source.calls == 1
