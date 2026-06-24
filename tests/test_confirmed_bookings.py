"""Tests for confirmed booking configuration and behavior."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from greatwalkbot.cli import main
from greatwalkbot.config.loader import load_watch_config
from greatwalkbot.domain.confirmed_booking import ConfirmedBooking
from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.plan import TripPlan
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.domain.trip import Trip
from greatwalkbot.domain.trip_fit import TripFitConfig
from greatwalkbot.models import AvailabilityDay, AvailabilitySnapshot, AvailabilityStatus, Track
from greatwalkbot.monitoring.trip_fit import evaluate_trip_fit
from greatwalkbot.monitoring.watcher import Watcher
from greatwalkbot.notifications.console import ConsoleNotifier
from support import make_itinerary

HONEYMOON_WINDOW = TravelWindow(date(2026, 11, 29), date(2026, 12, 31))
TRIP_FIT = TripFitConfig(
    enabled=True,
    min_rest_days_between_walks=1,
    buffer_days_before_first_walk=1,
    buffer_days_after_last_walk=1,
)


def _base_yaml(*, routeburn_booking: str = "") -> str:
    return f"""
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
{routeburn_booking}
  - track: kepler
    preferred_start_range:
      start: 2026-12-10
      end: 2026-12-18
    acceptable_start_range:
      start: 2026-12-03
      end: 2026-12-23
"""


def _routeburn_confirmed_block() -> str:
    return """
    confirmed_booking:
      start_date: 2026-12-10
      nights: 2
      direction: routeburn-shelter-to-divide
      notes: Booked manually on DOC
"""


def test_confirmed_booking_parsing(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        _base_yaml(routeburn_booking=_routeburn_confirmed_block()),
        encoding="utf-8",
    )

    plan = load_watch_config(config_file)
    routeburn = plan.trip.tracks[1]
    assert routeburn.confirmed_booking is not None
    booking = routeburn.confirmed_booking
    assert booking.track_slug == "routeburn"
    assert booking.start_date == date(2026, 12, 10)
    assert booking.nights == 2
    assert booking.end_date == date(2026, 12, 12)
    assert booking.direction == "routeburn-shelter-to-divide"
    assert booking.notes == "Booked manually on DOC"


def test_confirmed_booking_nights_must_match_known_duration(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        _base_yaml(
            routeburn_booking="""
    confirmed_booking:
      start_date: 2026-12-10
      nights: 5
"""
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="nights must be 2"):
        load_watch_config(config_file)


def test_confirmed_booking_duration_override(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        _base_yaml(
            routeburn_booking="""
    confirmed_booking:
      start_date: 2026-12-10
      nights: 5
      allow_duration_override: true
"""
        ),
        encoding="utf-8",
    )

    plan = load_watch_config(config_file)
    assert plan.trip.tracks[1].confirmed_booking.nights == 5


def test_confirmed_bookings_overlap_validation(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
polling_interval: 300
trip:
  name: Overlap
party:
  adults: 2
travel_window:
  start: 2026-12-01
  end: 2026-12-31
trip_fit:
  enabled: true
  min_rest_days_between_walks: 1
tracks:
  - track: milford
    preferred_start_dates:
      - 2026-12-10
    acceptable_start_range:
      start: 2026-12-01
      end: 2026-12-31
    confirmed_booking:
      start_date: 2026-12-10
      nights: 3
  - track: routeburn
    preferred_start_dates:
      - 2026-12-12
    acceptable_start_range:
      start: 2026-12-01
      end: 2026-12-31
    confirmed_booking:
      start_date: 2026-12-12
      nights: 2
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="insufficient rest days"):
        load_watch_config(config_file)


def test_confirmed_booking_outside_travel_window(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        _base_yaml(
            routeburn_booking="""
    confirmed_booking:
      start_date: 2027-01-05
      nights: 2
"""
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="outside travel_window"):
        load_watch_config(config_file)


def test_confirmed_booking_overlaps_buffer(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        _base_yaml(
            routeburn_booking="""
    confirmed_booking:
      start_date: 2026-12-29
      nights: 2
"""
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="overlap required trip_fit buffers"):
        load_watch_config(config_file)


def _trip_with_routeburn_confirmed() -> Trip:
    routeburn_booking = ConfirmedBooking(
        track_slug="routeburn",
        start_date=date(2026, 12, 10),
        nights=2,
    )
    return Trip(
        name="Honeymoon",
        party=Party(adults=2),
        travel_window=HONEYMOON_WINDOW,
        tracks=(
            TrackPreference(
                slug="milford",
                acceptable_start_range=DateRange(date(2026, 12, 3), date(2026, 12, 23)),
                preferred_start_dates=(date(2026, 12, 7),),
            ),
            TrackPreference(
                slug="routeburn",
                acceptable_start_range=DateRange(date(2026, 12, 3), date(2026, 12, 23)),
                preferred_start_range=DateRange(date(2026, 12, 6), date(2026, 12, 14)),
                confirmed_booking=routeburn_booking,
            ),
            TrackPreference(
                slug="kepler",
                acceptable_start_range=DateRange(date(2026, 12, 3), date(2026, 12, 23)),
                preferred_start_range=DateRange(date(2026, 12, 10), date(2026, 12, 18)),
            ),
        ),
    )


def test_candidate_fits_around_confirmed_booking():
    trip = _trip_with_routeburn_confirmed()
    itinerary = make_itinerary(
        track_slug="milford",
        start_date=date(2026, 12, 3),
        itinerary_nights=3,
    )
    result = evaluate_trip_fit(itinerary, trip, TRIP_FIT)
    assert result.trip_fit is True


def test_candidate_conflicts_with_confirmed_booking():
    trip = _trip_with_routeburn_confirmed()
    itinerary = make_itinerary(
        track_slug="milford",
        start_date=date(2026, 12, 10),
        itinerary_nights=3,
    )
    result = evaluate_trip_fit(itinerary, trip, TRIP_FIT)
    assert result.trip_fit is False
    assert "conflicts_with_confirmed_booking" in result.trip_fit_reasons


def test_remaining_unconfirmed_tracks_considered():
    routeburn_booking = ConfirmedBooking(
        track_slug="routeburn",
        start_date=date(2026, 12, 10),
        nights=2,
    )
    trip = Trip(
        name="Honeymoon",
        party=Party(adults=2),
        travel_window=HONEYMOON_WINDOW,
        tracks=(
            TrackPreference(
                slug="milford",
                acceptable_start_range=DateRange(date(2026, 12, 3), date(2026, 12, 23)),
                preferred_start_dates=(date(2026, 12, 18),),
            ),
            TrackPreference(
                slug="routeburn",
                acceptable_start_range=DateRange(date(2026, 12, 3), date(2026, 12, 23)),
                preferred_start_range=DateRange(date(2026, 12, 6), date(2026, 12, 14)),
                confirmed_booking=routeburn_booking,
            ),
            TrackPreference(
                slug="kepler",
                acceptable_start_range=DateRange(date(2026, 12, 16), date(2026, 12, 18)),
                preferred_start_range=DateRange(date(2026, 12, 16), date(2026, 12, 18)),
            ),
        ),
    )
    itinerary = make_itinerary(
        track_slug="milford",
        start_date=date(2026, 12, 18),
        itinerary_nights=3,
    )
    result = evaluate_trip_fit(itinerary, trip, TRIP_FIT)
    assert result.trip_fit is False
    assert "insufficient_room_for_remaining_tracks" in result.trip_fit_reasons


def test_watcher_skips_confirmed_track_without_fetching():
    fetch_mock = MagicMock()
    notifications: list[str] = []

    class RecordingNotifier(ConsoleNotifier):
        def notify_new_availability(self, itinerary):
            notifications.append(itinerary.track_slug)

    tracks = {
        "milford": Track("milford", "Milford Track", 873, 4, fixed_nights=3),
        "routeburn": Track("routeburn", "Routeburn Track", 874, 5, fixed_nights=2),
        "kepler": Track("kepler", "Kepler Track", 875, 6, fixed_nights=3),
    }

    class Source:
        def fetch_track_availability(self, track, from_date, to_date):
            fetch_mock(track.slug, from_date, to_date)
            if track.slug == "milford":
                return AvailabilitySnapshot(
                    track=tracks["milford"],
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
            return AvailabilitySnapshot(
                track=track,
                from_date=from_date,
                to_date=to_date,
                days=(),
            )

    plan = TripPlan(
        trip=_trip_with_routeburn_confirmed(),
        polling_interval_seconds=300,
        trip_fit=TRIP_FIT,
    )
    watcher = Watcher(
        plan,
        Source(),
        RecordingNotifier(party_size=2),
        resolve_track_fn=lambda slug: tracks[slug],
    )
    watcher.run_once()

    fetched_slugs = [call.args[0] for call in fetch_mock.call_args_list]
    assert "routeburn" not in fetched_slugs
    assert "milford" in fetched_slugs
    assert "kepler" in fetched_slugs


def test_plan_check_makes_no_network_calls(tmp_path, capsys):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        _base_yaml(routeburn_booking=_routeburn_confirmed_block()),
        encoding="utf-8",
    )

    with patch("greatwalkbot.cli.PlaywrightAvailabilitySource") as playwright_cls:
        with patch("greatwalkbot.cli.HttpAvailabilitySource") as http_cls:
            exit_code = main(["plan-check", str(config_file)])

    assert exit_code == 0
    playwright_cls.assert_not_called()
    http_cls.assert_not_called()
    output = capsys.readouterr().out
    assert "Confirmed bookings:" in output
    assert "routeburn" in output
    assert "Remaining walks to monitor:" in output
    assert "milford" in output
    assert "kepler" in output


def test_bookings_makes_no_network_calls(tmp_path, capsys):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        _base_yaml(routeburn_booking=_routeburn_confirmed_block()),
        encoding="utf-8",
    )

    with patch("greatwalkbot.cli.PlaywrightAvailabilitySource") as playwright_cls:
        with patch("greatwalkbot.cli.HttpAvailabilitySource") as http_cls:
            exit_code = main(["bookings", str(config_file)])

    assert exit_code == 0
    playwright_cls.assert_not_called()
    http_cls.assert_not_called()
    output = capsys.readouterr().out
    assert "routeburn" in output
    assert "2026-12-10" in output


def test_impossible_remaining_plan_returns_nonzero(tmp_path, capsys):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
polling_interval: 300
trip:
  name: Tight
party:
  adults: 2
travel_window:
  start: 2026-12-01
  end: 2026-12-12
trip_fit:
  enabled: true
  min_rest_days_between_walks: 1
  buffer_days_before_first_walk: 1
  buffer_days_after_last_walk: 1
tracks:
  - track: milford
    preferred_start_dates:
      - 2026-12-02
    acceptable_start_range:
      start: 2026-12-02
      end: 2026-12-12
    confirmed_booking:
      start_date: 2026-12-02
      nights: 3
  - track: routeburn
    preferred_start_dates:
      - 2026-12-10
    acceptable_start_range:
      start: 2026-12-02
      end: 2026-12-12
  - track: kepler
    preferred_start_dates:
      - 2026-12-10
    acceptable_start_range:
      start: 2026-12-02
      end: 2026-12-12
""",
        encoding="utf-8",
    )

    exit_code = main(["plan-check", str(config_file)])
    assert exit_code == 1
    output = capsys.readouterr().out
    assert "Feasibility: NO" in output or "not feasible" in output.lower()
