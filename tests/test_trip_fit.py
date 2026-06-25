"""Tests for trip-fit evaluation."""

from datetime import date
from unittest.mock import patch

import pytest

from greatwalkbot.cli import main
from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.direction import DirectionPreference
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.plan import TripPlan
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.domain.trip import Trip
from greatwalkbot.domain.trip_fit import TripFitConfig
from greatwalkbot.models import AvailabilityDay, AvailabilitySnapshot, AvailabilityStatus, Track
from greatwalkbot.monitoring.matcher import find_matching_itineraries
from greatwalkbot.monitoring.trip_fit import (
    check_trip_feasible_in_principle,
    evaluate_trip_fit,
    usable_window,
)
from greatwalkbot.monitoring.watcher import Watcher
from greatwalkbot.notifications.console import ConsoleNotifier
from support import make_itinerary

HONEYMOON_TRIP_FIT = TripFitConfig(
    enabled=True,
    min_rest_days_between_walks=1,
    buffer_days_before_first_walk=1,
    buffer_days_after_last_walk=1,
)


def honeymoon_trip() -> Trip:
    return Trip(
        name="New Zealand Honeymoon",
        party=Party(adults=2),
        travel_window=TravelWindow(date(2026, 11, 29), date(2026, 12, 31)),
        tracks=(
            TrackPreference(
                slug="milford",
                priority=100,
                acceptable_start_range=DateRange(date(2026, 12, 3), date(2026, 12, 23)),
                preferred_start_dates=(date(2026, 12, 7), date(2026, 12, 8), date(2026, 12, 9)),
                complete_itinerary_only=True,
            ),
            TrackPreference(
                slug="routeburn",
                priority=90,
                direction=DirectionPreference.EITHER,
                acceptable_start_range=DateRange(date(2026, 12, 3), date(2026, 12, 23)),
                preferred_start_range=DateRange(date(2026, 12, 6), date(2026, 12, 14)),
                complete_itinerary_only=True,
            ),
            TrackPreference(
                slug="kepler",
                priority=80,
                acceptable_start_range=DateRange(date(2026, 12, 3), date(2026, 12, 23)),
                preferred_start_range=DateRange(date(2026, 12, 10), date(2026, 12, 18)),
                complete_itinerary_only=True,
            ),
        ),
    )


def honeymoon_plan(*, trip_fit: TripFitConfig | None = None) -> TripPlan:
    return TripPlan(
        trip=honeymoon_trip(),
        polling_interval_seconds=300,
        trip_fit=trip_fit or HONEYMOON_TRIP_FIT,
    )


def test_honeymoon_feasible_in_principle():
    report = check_trip_feasible_in_principle(honeymoon_trip(), HONEYMOON_TRIP_FIT)
    assert report.feasible is True


def test_candidate_fits_with_room_for_remaining_tracks():
    itinerary = make_itinerary(start_date=date(2026, 12, 7), itinerary_nights=3)
    result = evaluate_trip_fit(itinerary, honeymoon_trip(), HONEYMOON_TRIP_FIT)
    assert result.trip_fit is True
    assert result.trip_fit_reasons == ()


def test_candidate_leaves_insufficient_room_for_remaining_tracks():
    narrow_trip = Trip(
        name="Narrow window",
        party=Party(adults=2),
        travel_window=TravelWindow(date(2026, 12, 1), date(2026, 12, 10)),
        tracks=(
            TrackPreference(
                slug="milford",
                acceptable_start_range=DateRange(date(2026, 12, 1), date(2026, 12, 10)),
                preferred_start_dates=(date(2026, 12, 6),),
            ),
            TrackPreference(
                slug="routeburn",
                acceptable_start_range=DateRange(date(2026, 12, 8), date(2026, 12, 10)),
                preferred_start_dates=(date(2026, 12, 8),),
            ),
        ),
    )
    trip_fit = TripFitConfig(
        enabled=True,
        min_rest_days_between_walks=1,
        buffer_days_before_first_walk=1,
        buffer_days_after_last_walk=1,
    )
    # Usable window Dec 2-9. Milford Dec 6-9 blocks routeburn (acceptable only Dec 8-10).
    itinerary = make_itinerary(start_date=date(2026, 12, 6), itinerary_nights=3)
    result = evaluate_trip_fit(itinerary, narrow_trip, trip_fit)
    assert result.trip_fit is False
    assert "insufficient_room_for_remaining_tracks" in result.trip_fit_reasons


def test_rest_days_are_enforced():
    trip = Trip(
        name="Rest test",
        party=Party(adults=2),
        travel_window=TravelWindow(date(2026, 12, 1), date(2026, 12, 31)),
        tracks=(
            TrackPreference(
                slug="milford",
                acceptable_start_range=DateRange(date(2026, 12, 7), date(2026, 12, 7)),
                preferred_start_dates=(date(2026, 12, 7),),
            ),
            TrackPreference(
                slug="routeburn",
                acceptable_start_range=DateRange(date(2026, 12, 10), date(2026, 12, 10)),
                preferred_start_dates=(date(2026, 12, 10),),
            ),
        ),
    )
    trip_fit = TripFitConfig(enabled=True, min_rest_days_between_walks=2)
    report = check_trip_feasible_in_principle(trip, trip_fit)
    assert report.feasible is False


def test_travel_window_buffers():
    trip = honeymoon_trip()
    trip_fit = TripFitConfig(
        enabled=True,
        buffer_days_before_first_walk=5,
        buffer_days_after_last_walk=5,
        min_rest_days_between_walks=1,
    )
    usable = usable_window(trip.travel_window, trip_fit)
    itinerary = make_itinerary(start_date=date(2026, 11, 30), itinerary_nights=3)
    result = evaluate_trip_fit(itinerary, trip, trip_fit)
    assert result.trip_fit is False
    assert "overlaps_required_buffer" in result.trip_fit_reasons or (
        "outside_travel_window" in result.trip_fit_reasons
    )


def test_routeburn_direction_does_not_change_duration():
    itinerary = make_itinerary(
        track_slug="routeburn",
        track_name="Routeburn Track",
        start_date=date(2026, 12, 12),
        itinerary_nights=2,
    )
    result = evaluate_trip_fit(itinerary, honeymoon_trip(), HONEYMOON_TRIP_FIT)
    assert itinerary.itinerary_nights == 2
    assert result.trip_fit is True


def test_disabled_trip_fit_preserves_matcher_behavior():
    itinerary = make_itinerary(start_date=date(2026, 12, 20))
    result = evaluate_trip_fit(
        itinerary,
        honeymoon_trip(),
        TripFitConfig(enabled=False),
    )
    assert result.trip_fit is None


def test_matcher_includes_end_date_and_nights():
    import json
    from pathlib import Path

    milford = Track("milford", "Milford Track", 873, 4, fixed_nights=3)
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "milford_complete.json").read_text(
            encoding="utf-8"
        )
    )
    from greatwalkbot.parsing import parse_gw_facility_response

    snapshot = parse_gw_facility_response(
        payload, milford, date(2026, 12, 7), date(2026, 12, 9)
    )
    preference = TrackPreference(
        slug="milford",
        acceptable_start_range=DateRange(date(2026, 12, 1), date(2026, 12, 31)),
        preferred_start_dates=(date(2026, 12, 7),),
        complete_itinerary_only=True,
    )
    result = find_matching_itineraries(
        snapshot,
        preference,
        Party(adults=2),
        TravelWindow(date(2026, 12, 1), date(2026, 12, 31)),
    )
    matches = result.itineraries
    assert len(matches) == 1
    assert matches[0].itinerary_nights == 3
    assert matches[0].end_date == date(2026, 12, 10)


def test_watcher_suppresses_trip_fit_mismatch(tmp_path):
    notifications: list[str] = []

    class RecordingNotifier(ConsoleNotifier):
        def notify_new_availability(self, itinerary):
            notifications.append(itinerary.start_date.isoformat())

    tracks = {
        "milford": Track("milford", "Milford Track", 873, 4, fixed_nights=3),
        "routeburn": Track("routeburn", "Routeburn Track", 874, 5, fixed_nights=2),
    }

    class Source:
        def fetch_track_availability(self, track, from_date, to_date):
            if track.slug != "milford":
                return AvailabilitySnapshot(
                    track=track,
                    from_date=from_date,
                    to_date=to_date,
                    days=(),
                )
            return AvailabilitySnapshot(
                track=tracks["milford"],
                from_date=from_date,
                to_date=to_date,
                days=(
                    AvailabilityDay(
                        date(2026, 12, 6),
                        AvailabilityStatus.AVAILABLE,
                        5,
                        ("Clinton Hut",),
                    ),
                ),
            )

    trip = Trip(
        name="Narrow window",
        party=Party(adults=2),
        travel_window=TravelWindow(date(2026, 12, 1), date(2026, 12, 10)),
        tracks=(
            TrackPreference(
                slug="milford",
                acceptable_start_range=DateRange(date(2026, 12, 1), date(2026, 12, 10)),
                preferred_start_dates=(date(2026, 12, 6),),
                complete_itinerary_only=True,
            ),
            TrackPreference(
                slug="routeburn",
                acceptable_start_range=DateRange(date(2026, 12, 8), date(2026, 12, 10)),
                preferred_start_dates=(date(2026, 12, 8),),
                complete_itinerary_only=True,
            ),
        ),
    )
    plan = TripPlan(
        trip=trip,
        polling_interval_seconds=300,
        trip_fit=HONEYMOON_TRIP_FIT,
    )
    watcher = Watcher(
        plan,
        Source(),
        RecordingNotifier(party_size=2),
        resolve_track_fn=lambda slug: tracks[slug],
    )
    watcher.run_once()
    assert notifications == []


def test_plan_check_makes_no_network_calls(tmp_path, capsys):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
polling_interval: 300
trip:
  name: New Zealand Honeymoon
party:
  adults: 2
travel_window:
  start: 2026-11-29
  end: 2026-12-31
trip_fit:
  enabled: true
  min_rest_days_between_walks: 1
  buffer_days_before_first_walk: 1
  buffer_days_after_last_walk: 1
tracks:
  - track: milford
    preferred_start_dates:
      - 2026-12-07
    acceptable_start_range:
      start: 2026-12-03
      end: 2026-12-23
  - track: routeburn
    direction: either
    preferred_start_range:
      start: 2026-12-06
      end: 2026-12-14
    acceptable_start_range:
      start: 2026-12-03
      end: 2026-12-23
  - track: kepler
    preferred_start_range:
      start: 2026-12-10
      end: 2026-12-18
    acceptable_start_range:
      start: 2026-12-03
      end: 2026-12-23
""",
        encoding="utf-8",
    )

    with patch("greatwalkbot.cli.PlaywrightAvailabilitySource") as playwright_cls:
        with patch("greatwalkbot.cli.HttpAvailabilitySource") as http_cls:
            exit_code = main(["plan-check", str(config_file)])

    assert exit_code == 0
    playwright_cls.assert_not_called()
    http_cls.assert_not_called()
    output = capsys.readouterr().out
    assert "milford" in output
    assert "Feasibility: YES" in output


def test_impossible_trip_returns_nonzero(tmp_path, capsys):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
polling_interval: 60
trip:
  name: Impossible
party:
  adults: 2
travel_window:
  start: 2026-12-01
  end: 2026-12-05
trip_fit:
  enabled: true
  min_rest_days_between_walks: 1
tracks:
  - track: milford
    preferred_start_dates:
      - 2026-12-01
    acceptable_start_range:
      start: 2026-12-01
      end: 2026-12-05
  - track: routeburn
    preferred_start_dates:
      - 2026-12-01
    acceptable_start_range:
      start: 2026-12-01
      end: 2026-12-05
  - track: kepler
    preferred_start_dates:
      - 2026-12-01
    acceptable_start_range:
      start: 2026-12-01
      end: 2026-12-05
""",
        encoding="utf-8",
    )

    exit_code = main(["plan-check", str(config_file)])
    assert exit_code == 1
    assert "Feasibility: NO" in capsys.readouterr().out
