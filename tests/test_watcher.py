"""Tests for the watch loop with a fake availability source."""

from datetime import date

from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.plan import TripPlan
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.domain.trip import Trip
from greatwalkbot.models import AvailabilityDay, AvailabilitySnapshot, AvailabilityStatus, Track
from greatwalkbot.monitoring.watcher import Watcher
from greatwalkbot.notifications.console import ConsoleNotifier

MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)


class FakeSource:
    def __init__(self, snapshots: list[AvailabilitySnapshot]) -> None:
        self._snapshots = list(snapshots)
        self.calls = 0

    def fetch_track_availability(self, track, from_date, to_date):
        self.calls += 1
        if not self._snapshots:
            raise RuntimeError("no data")
        return self._snapshots.pop(0)


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


def _snapshot(status: AvailabilityStatus, spaces: int) -> AvailabilitySnapshot:
    return AvailabilitySnapshot(
        track=MILFORD,
        from_date=date(2026, 12, 1),
        to_date=date(2026, 12, 31),
        days=(
            AvailabilityDay(
                date(2026, 12, 7),
                status,
                spaces,
                ("Clinton Hut",) if spaces else (),
            ),
        ),
    )


def test_watcher_notifies_only_once_for_same_availability():
    logs: list[str] = []
    notifications: list[str] = []

    class RecordingNotifier(ConsoleNotifier):
        def notify_new_availability(self, itinerary):
            notifications.append(itinerary.start_date.isoformat())

    source = FakeSource(
        [
            _snapshot(AvailabilityStatus.AVAILABLE, 5),
            _snapshot(AvailabilityStatus.AVAILABLE, 5),
        ]
    )
    watcher = Watcher(
        _plan(),
        source,
        RecordingNotifier(),
        resolve_track_fn=lambda slug: MILFORD,
        logger=logs.append,
    )

    watcher.run_once()
    watcher.run_once()

    assert source.calls == 2
    assert notifications == ["2026-12-07"]
    assert any("[check]" in line for line in logs)
    assert any("1 new" in line for line in logs)
    assert any("0 new" in line for line in logs)
