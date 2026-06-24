"""Parse Tyler RDR Great Walk facility responses into domain models."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from greatwalkbot.constants import LIMITED_AVAILABILITY_THRESHOLD
from greatwalkbot.facility_index import build_facility_index
from greatwalkbot.models import AvailabilityDay, AvailabilitySnapshot, AvailabilityStatus, Track


def _parse_api_date(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _date_range(from_date: date, to_date: date) -> tuple[date, ...]:
    if to_date < from_date:
        raise ValueError("to_date must be on or after from_date")
    days: list[date] = []
    current = from_date
    while current <= to_date:
        days.append(current)
        current += timedelta(days=1)
    return tuple(days)


def build_gw_facility_request(track: Track, from_date: date, to_date: date) -> dict[str, Any]:
    nights = (to_date - from_date).days
    return {
        "accomodation": "",
        "placeId": track.place_id,
        "customerClassificationId": 0,
        "arrivalDate": from_date.isoformat(),
        "nights": nights,
    }


def parse_gw_facility_response(
    payload: dict[str, Any],
    track: Track,
    from_date: date,
    to_date: date,
) -> AvailabilitySnapshot:
    facilities = payload.get("GreatWalkFacilityData") or []
    requested_dates = _date_range(from_date, to_date)

    days: list[AvailabilityDay] = []
    for day in requested_dates:
        available_facilities: list[tuple[str, int]] = []
        season_open = False

        for facility in facilities:
            name = str(facility.get("FacilityName", "Unknown"))
            for entry in facility.get("GreatWalkFacilityDateData") or []:
                if _parse_api_date(str(entry["ArrivalDate"])) != day:
                    continue
                if entry.get("IsSeasonAvailable"):
                    season_open = True
                if entry.get("IsAvailable") and int(entry.get("TotalAvailable") or 0) > 0:
                    available_facilities.append((name, int(entry["TotalAvailable"])))

        if not season_open and not available_facilities:
            status = AvailabilityStatus.CLOSED
            spaces = 0
            names: tuple[str, ...] = ()
        elif available_facilities:
            spaces = max(count for _, count in available_facilities)
            status = (
                AvailabilityStatus.LIMITED
                if spaces <= LIMITED_AVAILABILITY_THRESHOLD
                else AvailabilityStatus.AVAILABLE
            )
            names = tuple(sorted({name for name, _ in available_facilities}))
        else:
            status = AvailabilityStatus.UNAVAILABLE
            spaces = 0
            names = ()

        days.append(AvailabilityDay(date=day, status=status, spaces=spaces, facilities=names))

    return AvailabilitySnapshot(
        track=track,
        from_date=from_date,
        to_date=to_date,
        days=tuple(days),
        facility_index=build_facility_index(payload, from_date=from_date, to_date=to_date),
    )
