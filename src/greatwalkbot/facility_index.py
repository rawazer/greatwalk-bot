"""Per-facility availability index built from DOC facility responses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any


def normalize_facility_name(name: str) -> str:
    """Normalize facility names for stable matching."""
    return " ".join(name.strip().lower().split())


@dataclass(frozen=True)
class FacilityNightRecord:
    facility_name: str
    arrival_date: date
    spaces: int
    is_available: bool
    is_season_available: bool


@dataclass(frozen=True)
class FacilityAvailabilityIndex:
    """Spaces per facility per arrival night within a parsed response."""

    records: tuple[FacilityNightRecord, ...]

    def spaces_on(self, facility_name: str, arrival_date: date) -> int | None:
        normalized = normalize_facility_name(facility_name)
        for record in self.records:
            if (
                normalize_facility_name(record.facility_name) == normalized
                and record.arrival_date == arrival_date
            ):
                return record.spaces if record.is_available else 0
        return None

    def has_record(self, facility_name: str, arrival_date: date) -> bool:
        return self.spaces_on(facility_name, arrival_date) is not None


def _parse_api_date(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def build_facility_index(
    payload: dict[str, Any],
    *,
    from_date: date,
    to_date: date,
) -> FacilityAvailabilityIndex:
    """Build a facility-level index from a greatwalkplacefacility payload."""
    if to_date < from_date:
        raise ValueError("to_date must be on or after from_date")

    records: list[FacilityNightRecord] = []
    for facility in payload.get("GreatWalkFacilityData") or []:
        name = str(facility.get("FacilityName", "Unknown"))
        for entry in facility.get("GreatWalkFacilityDateData") or []:
            arrival = _parse_api_date(str(entry["ArrivalDate"]))
            if arrival < from_date or arrival > to_date:
                continue
            is_available = bool(entry.get("IsAvailable"))
            spaces = int(entry.get("TotalAvailable") or 0)
            records.append(
                FacilityNightRecord(
                    facility_name=name,
                    arrival_date=arrival,
                    spaces=spaces,
                    is_available=is_available,
                    is_season_available=bool(entry.get("IsSeasonAvailable")),
                )
            )

    return FacilityAvailabilityIndex(records=tuple(records))


def date_span(from_date: date, to_date: date) -> tuple[date, ...]:
    days: list[date] = []
    current = from_date
    while current <= to_date:
        days.append(current)
        current += timedelta(days=1)
    return tuple(days)
