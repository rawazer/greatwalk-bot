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
    "conflicts_with_confirmed_booking",
]


@dataclass(frozen=True)
class NightAvailabilitySummary:
    """Per-night availability used to validate a complete itinerary."""

    night_index: int
    arrival_date: date
    facility_name: str
    spaces: int | None
    party_size: int
    satisfied: bool


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
    complete_itinerary: bool = False
    party_size: int = 0
    direction: str | None = None
    night_summaries: tuple[NightAvailabilitySummary, ...] = ()
    validation_notes: tuple[str, ...] = ()
    trip_fit: bool | None = None
    trip_fit_reasons: tuple[str, ...] = ()

    @property
    def dedupe_key(self) -> tuple[str, date, str | None, tuple[str, ...]]:
        return (self.track_slug, self.start_date, self.direction, self.facilities)

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
    evaluation_summary: dict[str, object] | None = None


@dataclass(frozen=True)
class WatchCycleResult:
    checked_at: datetime
    track_results: tuple[TrackCheckResult, ...]

    @property
    def new_matches(self) -> tuple[AvailableItinerary, ...]:
        return tuple(itinerary for result in self.track_results for itinerary in result.new_matches)
