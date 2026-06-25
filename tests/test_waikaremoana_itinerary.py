"""Tests for Lake Waikaremoana complete-itinerary metadata and matching."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.direction import DirectionPreference
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.monitoring.itinerary_validation import validate_complete_itineraries
from greatwalkbot.monitoring.matcher import find_matching_itineraries
from greatwalkbot.models import Track
from greatwalkbot.parsing import parse_gw_facility_response
from greatwalkbot.track_durations import get_itinerary_nights
from greatwalkbot.track_itineraries import (
    WAIKAREMOANA_FORWARD,
    WAIKAREMOANA_REVERSE,
    definitions_for_track,
    has_itinerary_definition,
)

FIXTURES = Path(__file__).parent / "fixtures"
WAIKAREMOANA = Track("waikaremoana", "Lake Waikaremoana Track", 878, 3, fixed_nights=3)
TRAVEL_WINDOW = TravelWindow(date(2026, 12, 1), date(2026, 12, 31))
PARTY = Party(adults=2)


def _preference(*, direction: DirectionPreference = DirectionPreference.EITHER) -> TrackPreference:
    return TrackPreference(
        slug="waikaremoana",
        direction=direction,
        acceptable_start_range=DateRange(date(2026, 12, 1), date(2026, 12, 31)),
        preferred_start_range=DateRange(date(2026, 12, 1), date(2026, 12, 31)),
        complete_itinerary_only=True,
    )


def test_waikaremoana_itinerary_registered():
    assert has_itinerary_definition("waikaremoana")
    assert get_itinerary_nights("waikaremoana") == 3
    either = definitions_for_track("waikaremoana", DirectionPreference.EITHER)
    assert {definition.direction for definition in either} == {
        WAIKAREMOANA_FORWARD,
        WAIKAREMOANA_REVERSE,
    }
    forward = definitions_for_track("waikaremoana", DirectionPreference.FORWARD)[0]
    assert [night.facility_name for night in forward.required_nights] == [
        "Panekire Hut",
        "Waiopaoa Hut",
        "Marauiti Hut",
    ]


def test_waikaremoana_forward_complete_fixture_matches():
    payload = json.loads((FIXTURES / "waikaremoana_complete.json").read_text(encoding="utf-8"))
    snapshot = parse_gw_facility_response(
        payload, WAIKAREMOANA, date(2026, 12, 5), date(2026, 12, 7)
    )
    result = find_matching_itineraries(snapshot, _preference(), PARTY, TRAVEL_WINDOW)
    assert len(result.itineraries) == 1
    match = result.itineraries[0]
    assert match.complete_itinerary is True
    assert match.direction == WAIKAREMOANA_FORWARD
    assert match.facilities == ("Panekire Hut", "Waiopaoa Hut", "Marauiti Hut")
    assert match.party_size == 2


def test_waikaremoana_reverse_requires_reverse_facility_order():
    payload = json.loads((FIXTURES / "waikaremoana_complete.json").read_text(encoding="utf-8"))
    snapshot = parse_gw_facility_response(
        payload, WAIKAREMOANA, date(2026, 12, 5), date(2026, 12, 7)
    )
    results = validate_complete_itineraries(
        index=snapshot.facility_index,
        snapshot=snapshot,
        preference=_preference(direction=DirectionPreference.REVERSE),
        start_date=date(2026, 12, 5),
        party=PARTY,
    )
    assert len(results) == 1
    assert results[0].direction == WAIKAREMOANA_REVERSE
    assert results[0].complete_itinerary is False


def test_waikaremoana_either_evaluates_both_directions():
    payload = json.loads((FIXTURES / "waikaremoana_complete.json").read_text(encoding="utf-8"))
    snapshot = parse_gw_facility_response(
        payload, WAIKAREMOANA, date(2026, 12, 5), date(2026, 12, 7)
    )
    results = validate_complete_itineraries(
        index=snapshot.facility_index,
        snapshot=snapshot,
        preference=_preference(),
        start_date=date(2026, 12, 5),
        party=PARTY,
    )
    assert len(results) == 2
    by_direction = {result.direction: result for result in results}
    assert by_direction[WAIKAREMOANA_FORWARD].complete_itinerary is True
    assert by_direction[WAIKAREMOANA_REVERSE].complete_itinerary is False
