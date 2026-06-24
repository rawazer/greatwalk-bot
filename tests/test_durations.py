"""Tests for track duration registry."""

import pytest

from greatwalkbot.track_durations import (
    ITINERARY_NIGHTS,
    end_date_for_start,
    get_itinerary_nights,
)
from datetime import date


def test_registered_honeymoon_tracks_have_durations():
    assert get_itinerary_nights("milford") == 3
    assert get_itinerary_nights("routeburn") == 2
    assert get_itinerary_nights("kepler") == 3


def test_end_date_for_start():
    assert end_date_for_start(date(2026, 12, 7), 3) == date(2026, 12, 10)


def test_unknown_track_raises():
    with pytest.raises(ValueError, match="Unknown track"):
        get_itinerary_nights("not-a-real-track-slug")
