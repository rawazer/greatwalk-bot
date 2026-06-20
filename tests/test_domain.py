"""Tests for trip domain model validation."""

from datetime import date

import pytest

from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.direction import DirectionPreference
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.domain.trip import Trip


def _track(**kwargs) -> TrackPreference:
    defaults = {
        "slug": "milford",
        "acceptable_start_range": DateRange(date(2026, 12, 1), date(2026, 12, 31)),
        "preferred_start_dates": (date(2026, 12, 7),),
    }
    defaults.update(kwargs)
    return TrackPreference(**defaults)


def test_travel_window_intersection():
    window = TravelWindow(date(2026, 11, 29), date(2026, 12, 31))
    bounds = window.intersect(DateRange(date(2026, 12, 3), date(2026, 12, 23)))
    assert bounds.start == date(2026, 12, 3)
    assert bounds.end == date(2026, 12, 23)


def test_track_preference_levels():
    window = TravelWindow(date(2026, 11, 29), date(2026, 12, 31))
    pref = _track(
        preferred_start_dates=(date(2026, 12, 7),),
        preferred_start_range=DateRange(date(2026, 12, 10), date(2026, 12, 12)),
    )

    assert pref.preference_for(date(2026, 12, 7), window) == "preferred"
    assert pref.preference_for(date(2026, 12, 11), window) == "preferred"
    assert pref.preference_for(date(2026, 12, 20), window) == "acceptable"
    assert pref.preference_for(date(2026, 11, 1), window) is None


def test_trip_validates_track_bounds():
    window = TravelWindow(date(2026, 11, 29), date(2026, 12, 31))
    with pytest.raises(ValueError, match="does not overlap"):
        Trip(
            name="Test",
            party=Party(adults=2),
            travel_window=window,
            tracks=(
                _track(
                    acceptable_start_range=DateRange(date(2026, 10, 1), date(2026, 10, 31)),
                ),
            ),
        )


def test_direction_parse():
    assert DirectionPreference.parse("either") == DirectionPreference.EITHER
    with pytest.raises(ValueError, match="direction"):
        DirectionPreference.parse("northbound")
