"""Monitoring domain models (source- and track-registry agnostic)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Literal

PreferenceLevel = Literal["preferred", "acceptable"]

TripFitReason = Literal[
    "outside_travel_window",
    "insufficient_room_for_remaining_tracks",
    "overlaps_required_buffer",
]


@dataclass(frozen=True)
class AvailableItinerary:
    """A bookable complete itinerary, independent of how it was fetched."""

    track_slug: str
    track_name: str
    start_date: date
    end_date: date
    itinerary_nights: int
    spaces: int
    facilities: tuple[str, ...]
    preference: PreferenceLevel
    complete_itinerary: bool = True
    trip_fit: bool | None = None
    trip_fit_reasons: tuple[str, ...] = ()

    @property
    def dedupe_key(self) -> tuple[str, date, tuple[str, ...]]:
        return (self.track_slug, self.start_date, self.facilities)

    def with_trip_fit(self, *, trip_fit: bool, reasons: tuple[str, ...] = ()) -> AvailableItinerary:
        return replace(self, trip_fit=trip_fit, trip_fit_reasons=reasons)


@dataclass(frozen=True)
class TrackCheckResult:
    track_slug: str
    track_name: str
    from_date: date
    to_date: date
    matches: tuple[AvailableItinerary, ...]
    new_matches: tuple[AvailableItinerary, ...]


@dataclass(frozen=True)
class WatchCycleResult:
    checked_at: datetime
    track_results: tuple[TrackCheckResult, ...]

    @property
    def new_matches(self) -> tuple[AvailableItinerary, ...]:
        return tuple(itinerary for result in self.track_results for itinerary in result.new_matches)
