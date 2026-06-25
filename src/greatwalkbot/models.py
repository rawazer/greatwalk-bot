"""Typed domain models for Great Walk availability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from greatwalkbot.facility_index import FacilityAvailabilityIndex


class AvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"
    CLOSED = "closed"


@dataclass(frozen=True)
class Track:
    slug: str
    name: str
    place_id: int
    list_index: int
    fixed_nights: int | None = None

    @property
    def dropdown_element_id(self) -> str:
        return f"great-walk-{self.list_index + 1}"

    @property
    def dropdown_option_ids(self) -> tuple[str, ...]:
        index = self.list_index + 1
        return (f"great-walk-{index}", f"great-walk-mobile-{index}")


@dataclass(frozen=True)
class AvailabilityDay:
    date: date
    status: AvailabilityStatus
    spaces: int
    facilities: tuple[str, ...]


@dataclass(frozen=True)
class AvailabilitySnapshot:
    track: Track
    from_date: date
    to_date: date
    days: tuple[AvailabilityDay, ...]
    facility_index: FacilityAvailabilityIndex | None = None
