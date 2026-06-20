"""Tests for availability matching logic."""

from datetime import date

from greatwalkbot.config.models import DateRange, TrackWatchConfig
from greatwalkbot.models import AvailabilityDay, AvailabilitySnapshot, AvailabilityStatus, Track
from greatwalkbot.monitoring.matcher import find_matching_itineraries

MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)
TRACK_CONFIG = TrackWatchConfig(
    slug="milford",
    preferred=(DateRange(date(2026, 12, 7), date(2026, 12, 10)),),
    acceptable=(DateRange(date(2026, 12, 1), date(2026, 12, 31)),),
)


def _snapshot(days: tuple[AvailabilityDay, ...]) -> AvailabilitySnapshot:
    return AvailabilitySnapshot(
        track=MILFORD,
        from_date=days[0].date,
        to_date=days[-1].date,
        days=days,
    )


def test_find_preferred_and_acceptable_matches():
    snapshot = _snapshot(
        (
            AvailabilityDay(
                date(2026, 12, 7),
                AvailabilityStatus.LIMITED,
                3,
                ("Clinton Hut",),
            ),
            AvailabilityDay(
                date(2026, 12, 20),
                AvailabilityStatus.AVAILABLE,
                10,
                ("Mintaro Hut",),
            ),
            AvailabilityDay(
                date(2026, 12, 21),
                AvailabilityStatus.UNAVAILABLE,
                0,
                (),
            ),
        )
    )

    matches = find_matching_itineraries(snapshot, TRACK_CONFIG, party_size=2)
    assert len(matches) == 2
    assert matches[0].preference == "preferred"
    assert matches[0].start_date == date(2026, 12, 7)
    assert matches[1].preference == "acceptable"
    assert matches[1].start_date == date(2026, 12, 20)


def test_party_size_filters_small_availability():
    snapshot = _snapshot(
        (
            AvailabilityDay(
                date(2026, 12, 7),
                AvailabilityStatus.LIMITED,
                1,
                ("Clinton Hut",),
            ),
        )
    )

    matches = find_matching_itineraries(snapshot, TRACK_CONFIG, party_size=2)
    assert matches == ()
