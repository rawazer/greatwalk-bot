"""Per-track constraints within a trip."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.direction import DirectionPreference
from greatwalkbot.domain.confirmed_booking import ConfirmedBooking

PreferenceLevel = Literal["preferred", "acceptable"]


@dataclass(frozen=True)
class TrackPreference:
    slug: str
    acceptable_start_range: DateRange
    priority: int = 50
    direction: DirectionPreference = DirectionPreference.EITHER
    complete_itinerary_only: bool = False
    preferred_start_dates: tuple[date, ...] = ()
    preferred_start_range: DateRange | None = None
    confirmed_booking: ConfirmedBooking | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.priority <= 100:
            raise ValueError("priority must be between 0 and 100")
        if not self.preferred_start_dates and self.preferred_start_range is None:
            raise ValueError(
                f"Track {self.slug!r} must define preferred_start_dates or preferred_start_range"
            )

    def preference_for(self, day: date, travel_window: TravelWindow) -> PreferenceLevel | None:
        if not travel_window.contains(day):
            return None
        if not self.acceptable_start_range.contains(day):
            return None
        if day in self.preferred_start_dates:
            return "preferred"
        if self.preferred_start_range and self.preferred_start_range.contains(day):
            return "preferred"
        return "acceptable"

    def query_bounds(self, travel_window: TravelWindow) -> DateRange:
        return travel_window.intersect(self.acceptable_start_range)

    def validate_against(self, travel_window: TravelWindow) -> None:
        travel_window.intersect(self.acceptable_start_range)
        for day in self.preferred_start_dates:
            if self.preference_for(day, travel_window) != "preferred":
                raise ValueError(
                    f"preferred_start_dates contains {day.isoformat()} outside configured bounds"
                )
        if self.preferred_start_range is not None:
            if not travel_window.contains(self.preferred_start_range.start):
                raise ValueError("preferred_start_range must fall within the travel window")
            if not travel_window.contains(self.preferred_start_range.end):
                raise ValueError("preferred_start_range must fall within the travel window")
            if not self.acceptable_start_range.contains(self.preferred_start_range.start):
                raise ValueError("preferred_start_range must fall within acceptable_start_range")
            if not self.acceptable_start_range.contains(self.preferred_start_range.end):
                raise ValueError("preferred_start_range must fall within acceptable_start_range")
