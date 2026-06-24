"""Manually recorded DOC bookings (configuration only, not live availability)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from greatwalkbot.track_durations import end_date_for_start


@dataclass(frozen=True)
class ConfirmedBooking:
    """A walk the user has already booked manually on DOC."""

    track_slug: str
    start_date: date
    nights: int
    direction: str | None = None
    notes: str | None = None
    allow_duration_override: bool = False

    @property
    def end_date(self) -> date:
        return end_date_for_start(self.start_date, self.nights)
