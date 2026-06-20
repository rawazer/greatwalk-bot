"""Monitoring domain models (source- and track-registry agnostic)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

PreferenceLevel = Literal["preferred", "acceptable"]


@dataclass(frozen=True)
class AvailableItinerary:
    """A bookable start date for a track, independent of how it was fetched."""

    track_slug: str
    track_name: str
    start_date: date
    spaces: int
    facilities: tuple[str, ...]
    preference: PreferenceLevel

    @property
    def dedupe_key(self) -> tuple[str, date, tuple[str, ...]]:
        return (self.track_slug, self.start_date, self.facilities)


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
