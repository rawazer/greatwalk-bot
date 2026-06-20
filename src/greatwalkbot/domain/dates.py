"""Date-related domain value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(
                f"Invalid date range {self.start.isoformat()}..{self.end.isoformat()}"
            )

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    @classmethod
    def spanning(cls, dates: tuple[date, ...]) -> DateRange:
        if not dates:
            raise ValueError("Cannot build a date range from an empty sequence")
        return cls(min(dates), max(dates))


@dataclass(frozen=True)
class TravelWindow:
    """Overall dates when the traveller is in New Zealand."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(
                f"Invalid travel window {self.start.isoformat()}..{self.end.isoformat()}"
            )

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    def intersect(self, other: DateRange) -> DateRange:
        start = max(self.start, other.start)
        end = min(self.end, other.end)
        if end < start:
            raise ValueError(
                f"Travel window {self.start}..{self.end} does not overlap {other.start}..{other.end}"
            )
        return DateRange(start, end)

    @property
    def as_range(self) -> DateRange:
        return DateRange(self.start, self.end)
