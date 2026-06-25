"""Tests for track slug resolution."""

import pytest

from greatwalkbot.tracks import resolve_track


def test_resolve_milford():
    track = resolve_track("milford")
    assert track.place_id == 873
    assert track.dropdown_element_id == "great-walk-5"
    assert track.dropdown_option_ids == ("great-walk-5", "great-walk-mobile-5")


def test_resolve_partial_name():
    track = resolve_track("routeburn")
    assert track.name == "Routeburn Track"


def test_unknown_track():
    with pytest.raises(ValueError, match="Unknown track"):
        resolve_track("unknown-track")
