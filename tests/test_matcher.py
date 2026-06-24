"""Tests for availability matching logic."""

import json
from datetime import date
from pathlib import Path

from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.models import AvailabilityDay, AvailabilitySnapshot, AvailabilityStatus, Track
from greatwalkbot.monitoring.matcher import find_matching_itineraries
from greatwalkbot.parsing import parse_gw_facility_response

FIXTURES = Path(__file__).parent / "fixtures"
MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)
TRAVEL_WINDOW = TravelWindow(date(2026, 11, 29), date(2026, 12, 31))
PARTY = Party(adults=2)
TRACK_PREFERENCE = TrackPreference(
    slug="milford",
    acceptable_start_range=DateRange(date(2026, 12, 1), date(2026, 12, 31)),
    preferred_start_range=DateRange(date(2026, 12, 7), date(2026, 12, 10)),
    complete_itinerary_only=True,
)


def _snapshot(days: tuple[AvailabilityDay, ...]) -> AvailabilitySnapshot:
    return AvailabilitySnapshot(
        track=MILFORD,
        from_date=days[0].date,
        to_date=days[-1].date,
        days=days,
    )


def test_find_preferred_and_acceptable_matches_with_complete_fixture():
    payload = json.loads((FIXTURES / "milford_complete.json").read_text(encoding="utf-8"))
    snapshot = parse_gw_facility_response(
        payload, MILFORD, date(2026, 12, 7), date(2026, 12, 9)
    )

    matches = find_matching_itineraries(
        snapshot, TRACK_PREFERENCE, PARTY, TRAVEL_WINDOW
    )
    assert len(matches) == 1
    assert matches[0].preference == "preferred"
    assert matches[0].start_date == date(2026, 12, 7)
    assert matches[0].complete_itinerary is True


def test_party_size_filters_small_availability():
    payload = json.loads((FIXTURES / "milford_complete.json").read_text(encoding="utf-8"))
    payload["GreatWalkFacilityData"][0]["GreatWalkFacilityDateData"][0]["TotalAvailable"] = 1
    snapshot = parse_gw_facility_response(
        payload, MILFORD, date(2026, 12, 7), date(2026, 12, 9)
    )

    matches = find_matching_itineraries(
        snapshot, TRACK_PREFERENCE, PARTY, TRAVEL_WINDOW
    )
    assert matches == ()


def test_preferred_start_dates():
    preference = TrackPreference(
        slug="milford",
        acceptable_start_range=DateRange(date(2026, 12, 1), date(2026, 12, 31)),
        preferred_start_dates=(date(2026, 12, 8),),
        complete_itinerary_only=False,
    )
    snapshot = _snapshot(
        (
            AvailabilityDay(
                date(2026, 12, 8),
                AvailabilityStatus.AVAILABLE,
                5,
                ("Clinton Hut",),
            ),
        )
    )
    matches = find_matching_itineraries(snapshot, preference, PARTY, TRAVEL_WINDOW)
    assert len(matches) == 1
    assert matches[0].preference == "preferred"
    assert matches[0].complete_itinerary is False
