"""Tests for complete-itinerary availability validation."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from greatwalkbot.cli import main
from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.direction import DirectionPreference
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.monitoring.itinerary_validation import validate_complete_itineraries
from greatwalkbot.monitoring.matcher import find_matching_itineraries
from greatwalkbot.models import AvailabilityDay, AvailabilitySnapshot, AvailabilityStatus, Track
from greatwalkbot.parsing import parse_gw_facility_response
from greatwalkbot.track_itineraries import ROUTEBURN_FORWARD, ROUTEBURN_REVERSE

FIXTURES = Path(__file__).parent / "fixtures"
MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)
ROUTEBURN = Track("routeburn", "Routeburn Track", 874, 7, fixed_nights=2)
TRAVEL_WINDOW = TravelWindow(date(2026, 11, 29), date(2026, 12, 31))
PARTY = Party(adults=2)


def _load_snapshot(track: Track, fixture_name: str, start: date, end: date):
    payload = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
    return parse_gw_facility_response(payload, track, start, end)


def _milford_preference() -> TrackPreference:
    return TrackPreference(
        slug="milford",
        acceptable_start_range=DateRange(date(2026, 12, 1), date(2026, 12, 31)),
        preferred_start_range=DateRange(date(2026, 12, 7), date(2026, 12, 10)),
        complete_itinerary_only=True,
    )


def _routeburn_preference() -> TrackPreference:
    return TrackPreference(
        slug="routeburn",
        direction=DirectionPreference.EITHER,
        acceptable_start_range=DateRange(date(2026, 12, 1), date(2026, 12, 31)),
        preferred_start_range=DateRange(date(2026, 12, 10), date(2026, 12, 14)),
        complete_itinerary_only=True,
    )


def test_fully_complete_milford_itinerary():
    snapshot = _load_snapshot(
        MILFORD, "milford_complete.json", date(2026, 12, 7), date(2026, 12, 9)
    )
    result = find_matching_itineraries(
        snapshot, _milford_preference(), PARTY, TRAVEL_WINDOW
    )
    matches = result.itineraries
    assert len(matches) == 1
    match = matches[0]
    assert match.complete_itinerary is True
    assert match.party_size == 2
    assert match.facilities == ("Clinton Hut", "Mintaro Hut", "Dumpling Hut")
    assert match.spaces == 6


def test_one_required_night_unavailable():
    snapshot = _load_snapshot(
        MILFORD, "milford_partial.json", date(2026, 12, 7), date(2026, 12, 9)
    )
    result = find_matching_itineraries(
        snapshot, _milford_preference(), PARTY, TRAVEL_WINDOW
    )
    matches = result.itineraries
    assert matches == ()


def test_insufficient_spaces_for_party_size():
    payload = json.loads((FIXTURES / "milford_complete.json").read_text(encoding="utf-8"))
    payload["GreatWalkFacilityData"][0]["GreatWalkFacilityDateData"][0]["TotalAvailable"] = 1
    snapshot = parse_gw_facility_response(
        payload, MILFORD, date(2026, 12, 7), date(2026, 12, 9)
    )
    result = find_matching_itineraries(
        snapshot, _milford_preference(), PARTY, TRAVEL_WINDOW
    )
    matches = result.itineraries
    assert matches == ()


def test_routeburn_one_direction_valid_other_invalid():
    snapshot = _load_snapshot(
        ROUTEBURN,
        "routeburn_directions.json",
        date(2026, 12, 10),
        date(2026, 12, 11),
    )
    results = validate_complete_itineraries(
        index=snapshot.facility_index,
        snapshot=snapshot,
        preference=_routeburn_preference(),
        start_date=date(2026, 12, 10),
        party=PARTY,
    )
    assert len(results) == 2
    by_direction = {result.direction: result for result in results}
    assert by_direction[ROUTEBURN_FORWARD].complete_itinerary is True
    assert by_direction[ROUTEBURN_REVERSE].complete_itinerary is False

    result = find_matching_itineraries(
        snapshot, _routeburn_preference(), PARTY, TRAVEL_WINDOW
    )
    matches = result.itineraries
    assert len(matches) == 1
    assert matches[0].direction == ROUTEBURN_FORWARD


def test_insufficient_source_data_produces_no_alert():
    snapshot = AvailabilitySnapshot(
        track=MILFORD,
        from_date=date(2026, 12, 7),
        to_date=date(2026, 12, 7),
        days=(
            AvailabilityDay(
                date(2026, 12, 7),
                AvailabilityStatus.AVAILABLE,
                5,
                ("Clinton Hut",),
            ),
        ),
        facility_index=None,
    )
    result = find_matching_itineraries(
        snapshot, _milford_preference(), PARTY, TRAVEL_WINDOW
    )
    matches = result.itineraries
    assert matches == ()


def test_explain_availability_does_not_notify_or_mutate_dedupe(tmp_path, capsys):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
polling_interval: 300
trip:
  name: Test
party:
  adults: 2
travel_window:
  start: 2026-11-29
  end: 2026-12-31
tracks:
  - track: milford
    complete_itinerary_only: true
    preferred_start_dates:
      - 2026-12-07
    acceptable_start_range:
      start: 2026-12-01
      end: 2026-12-31
""",
        encoding="utf-8",
    )

    payload = json.loads((FIXTURES / "milford_complete.json").read_text(encoding="utf-8"))
    snapshot = parse_gw_facility_response(
        payload, MILFORD, date(2026, 12, 7), date(2026, 12, 9)
    )

    class Source:
        def fetch_track_availability(self, track, from_date, to_date):
            return snapshot

    with patch("greatwalkbot.cli.PlaywrightAvailabilitySource", return_value=Source()):
        exit_code = main(
            [
                "explain-availability",
                str(config_file),
                "--track",
                "milford",
                "--date",
                "2026-12-07",
            ]
        )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Complete itinerary validated: YES" in output
    assert "Clinton Hut" in output
