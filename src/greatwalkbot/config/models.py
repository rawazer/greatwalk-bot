"""Watch configuration models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DateRange:
    from_date: date
    to_date: date

    def __post_init__(self) -> None:
        if self.to_date < self.from_date:
            raise ValueError(
                f"Invalid date range {self.from_date.isoformat()}..{self.to_date.isoformat()}"
            )

    def contains(self, day: date) -> bool:
        return self.from_date <= day <= self.to_date


@dataclass(frozen=True)
class TrackWatchConfig:
    slug: str
    preferred: tuple[DateRange, ...]
    acceptable: tuple[DateRange, ...]

    def query_bounds(self) -> DateRange:
        if not self.acceptable:
            raise ValueError(f"Track {self.slug!r} has no acceptable date ranges")
        return DateRange(
            min(r.from_date for r in self.acceptable),
            max(r.to_date for r in self.acceptable),
        )

    def preference_for(self, day: date) -> str | None:
        if any(r.contains(day) for r in self.preferred):
            return "preferred"
        if any(r.contains(day) for r in self.acceptable):
            return "acceptable"
        return None


@dataclass(frozen=True)
class WatchConfig:
    party_size: int
    polling_interval_seconds: int
    tracks: tuple[TrackWatchConfig, ...]
    source: str = "playwright"

    def __post_init__(self) -> None:
        if self.party_size < 1:
            raise ValueError("party_size must be at least 1")
        if self.polling_interval_seconds < 1:
            raise ValueError("polling_interval must be at least 1 second")
        if not self.tracks:
            raise ValueError("At least one track must be configured")
