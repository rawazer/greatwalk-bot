"""Tests for YAML config loading."""

from datetime import date
from pathlib import Path

import pytest

from greatwalkbot.config.loader import load_watch_config


def test_load_legacy_watch_config(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
party_size: 2
polling_interval: 120
tracks:
  - track: milford
    preferred:
      - from: 2026-12-07
        to: 2026-12-10
    acceptable:
      - from: 2026-12-01
        to: 2026-12-31
""",
        encoding="utf-8",
    )

    plan = load_watch_config(config_file)
    assert plan.party_size == 2
    assert plan.polling_interval_seconds == 120
    assert plan.trip.name == "Watch"
    assert len(plan.trip.tracks) == 1
    assert plan.trip.tracks[0].slug == "milford"
    assert plan.trip.tracks[0].preferred_start_range.start == date(2026, 12, 7)


def test_load_trip_config(tmp_path: Path):
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
tracks:
  - track: milford
    priority: 100
    complete_itinerary_only: true
    preferred_start_dates:
      - 2026-12-07
      - 2026-12-08
    acceptable_start_range:
      start: 2026-12-03
      end: 2026-12-23
  - track: routeburn
    priority: 90
    direction: either
    preferred_start_range:
      start: 2026-12-06
      end: 2026-12-14
    acceptable_start_range:
      start: 2026-12-03
      end: 2026-12-23
""",
        encoding="utf-8",
    )

    plan = load_watch_config(config_file)
    assert plan.trip.name == "New Zealand Honeymoon"
    assert plan.trip.party.adults == 2
    assert plan.trip.travel_window.start == date(2026, 11, 29)
    assert len(plan.trip.tracks) == 2

    milford = plan.trip.tracks[0]
    assert milford.priority == 100
    assert milford.complete_itinerary_only is True
    assert milford.preferred_start_dates == (date(2026, 12, 7), date(2026, 12, 8))

    routeburn = plan.trip.tracks[1]
    assert routeburn.preferred_start_range.start == date(2026, 12, 6)


def test_load_trip_config_nested_party(tmp_path: Path):
    """party and travel_window may also appear under trip."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
polling_interval: 60
trip:
  name: Nested
  party:
    adults: 1
  travel_window:
    start: 2026-12-01
    end: 2026-12-31
tracks:
  - track: milford
    preferred_start_dates:
      - 2026-12-07
    acceptable_start_range:
      start: 2026-12-01
      end: 2026-12-31
""",
        encoding="utf-8",
    )

    plan = load_watch_config(config_file)
    assert plan.trip.party.adults == 1


def test_preferred_must_be_within_acceptable(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
party_size: 1
polling_interval: 60
tracks:
  - track: milford
    preferred:
      - from: 2027-01-01
        to: 2027-01-05
    acceptable:
      - from: 2026-12-01
        to: 2026-12-31
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="preferred"):
        load_watch_config(config_file)


def test_trip_preferred_outside_travel_window(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
polling_interval: 60
trip:
  name: Test
party:
  adults: 2
travel_window:
  start: 2026-12-01
  end: 2026-12-31
tracks:
  - track: milford
    preferred_start_dates:
      - 2026-11-01
    acceptable_start_range:
      start: 2026-12-01
      end: 2026-12-31
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="preferred_start_dates"):
        load_watch_config(config_file)
