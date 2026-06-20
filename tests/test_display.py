"""Tests for availability table formatting."""

from datetime import date

from greatwalkbot.display import format_availability_table
from greatwalkbot.models import AvailabilityDay, AvailabilitySnapshot, AvailabilityStatus, Track


def test_format_availability_table():
    track = Track("milford", "Milford Track", 873, 4, fixed_nights=3)
    snapshot = AvailabilitySnapshot(
        track=track,
        from_date=date(2026, 12, 7),
        to_date=date(2026, 12, 8),
        days=(
            AvailabilityDay(
                date(2026, 12, 7),
                AvailabilityStatus.LIMITED,
                3,
                ("Clinton Hut",),
            ),
            AvailabilityDay(
                date(2026, 12, 8),
                AvailabilityStatus.UNAVAILABLE,
                0,
                (),
            ),
        ),
    )

    text = format_availability_table(snapshot)
    assert "Milford Track" in text
    assert "2026-12-07" in text
    assert "limited" in text
    assert "Clinton Hut" in text
