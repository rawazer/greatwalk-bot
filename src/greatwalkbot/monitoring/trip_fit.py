"""Trip-fit feasibility evaluation for multi-walk trips."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from itertools import permutations

from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.trip import Trip
from greatwalkbot.domain.trip_fit import TripFitConfig
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.monitoring.models import AvailableItinerary
from greatwalkbot.track_durations import end_date_for_start, get_itinerary_nights


@dataclass(frozen=True)
class WalkInterval:
    track_slug: str
    start_date: date
    end_date: date
    itinerary_nights: int


@dataclass(frozen=True)
class TripFeasibilityReport:
    feasible: bool
    reasons: tuple[str, ...]
    usable_window: DateRange


def usable_window(travel_window: TravelWindow, trip_fit: TripFitConfig) -> DateRange:
    return DateRange(
        travel_window.start + timedelta(days=trip_fit.buffer_days_before_first_walk),
        travel_window.end - timedelta(days=trip_fit.buffer_days_after_last_walk),
    )


def itinerary_to_interval(itinerary: AvailableItinerary) -> WalkInterval:
    return WalkInterval(
        track_slug=itinerary.track_slug,
        start_date=itinerary.start_date,
        end_date=itinerary.end_date,
        itinerary_nights=itinerary.itinerary_nights,
    )


def preference_to_interval(pref: TrackPreference, start: date) -> WalkInterval:
    nights = get_itinerary_nights(pref.slug)
    return WalkInterval(
        track_slug=pref.slug,
        start_date=start,
        end_date=end_date_for_start(start, nights),
        itinerary_nights=nights,
    )


def _buffer_violation_reasons(
    interval: WalkInterval,
    travel_window: TravelWindow,
    usable: DateRange,
) -> tuple[str, ...]:
    if usable.end < usable.start:
        return ("outside_travel_window",)

    reasons: list[str] = []
    if interval.start_date < usable.start or interval.end_date > usable.end:
        if (
            interval.start_date < travel_window.start
            or interval.end_date > travel_window.end
        ):
            reasons.append("outside_travel_window")
        else:
            reasons.append("overlaps_required_buffer")
    return tuple(reasons)


def _conflicts(
    left: WalkInterval,
    right: WalkInterval,
    min_rest_days: int,
) -> bool:
    if left.end_date < right.start_date:
        gap = (right.start_date - left.end_date).days
        return gap < min_rest_days + 1
    if right.end_date < left.start_date:
        gap = (left.start_date - right.end_date).days
        return gap < min_rest_days + 1
    return True


def _earliest_start(
    pref: TrackPreference,
    placed: tuple[WalkInterval, ...],
    usable: DateRange,
    min_rest_days: int,
) -> date | None:
    nights = get_itinerary_nights(pref.slug)
    earliest = max(usable.start, pref.acceptable_start_range.start)
    latest_start = min(usable.end, pref.acceptable_start_range.end)
    if latest_start < earliest:
        return None

    current = earliest
    while current <= latest_start:
        candidate = preference_to_interval(pref, current)
        if candidate.end_date > usable.end:
            break
        if all(not _conflicts(candidate, other, min_rest_days) for other in placed):
            return current
        current += timedelta(days=1)
    return None


def _can_schedule(
    tracks: tuple[TrackPreference, ...],
    *,
    fixed: WalkInterval | None,
    usable: DateRange,
    min_rest_days: int,
) -> bool:
    if not tracks:
        return True
    if usable.end < usable.start:
        return False

    for order in permutations(tracks):
        placed: list[WalkInterval] = []
        if fixed is not None:
            placed.append(fixed)
        success = True
        for pref in order:
            start = _earliest_start(pref, tuple(placed), usable, min_rest_days)
            if start is None:
                success = False
                break
            placed.append(preference_to_interval(pref, start))
        if success:
            return True
    return False


def evaluate_trip_fit(
    itinerary: AvailableItinerary,
    trip: Trip,
    trip_fit: TripFitConfig,
) -> AvailableItinerary:
    """Return itinerary annotated with trip_fit result."""
    if not trip_fit.enabled:
        return itinerary

    usable = usable_window(trip.travel_window, trip_fit)
    candidate = itinerary_to_interval(itinerary)

    buffer_reasons = _buffer_violation_reasons(
        candidate, trip.travel_window, usable
    )
    if buffer_reasons:
        return itinerary.with_trip_fit(trip_fit=False, reasons=buffer_reasons)

    remaining = tuple(
        pref for pref in trip.tracks if pref.slug != itinerary.track_slug
    )
    if _can_schedule(
        remaining,
        fixed=candidate,
        usable=usable,
        min_rest_days=trip_fit.min_rest_days_between_walks,
    ):
        return itinerary.with_trip_fit(trip_fit=True)

    return itinerary.with_trip_fit(
        trip_fit=False,
        reasons=("insufficient_room_for_remaining_tracks",),
    )


def check_trip_feasible_in_principle(
    trip: Trip,
    trip_fit: TripFitConfig,
) -> TripFeasibilityReport:
    """Check whether all configured tracks can fit in the travel window in principle."""
    usable = usable_window(trip.travel_window, trip_fit)
    if usable.end < usable.start:
        return TripFeasibilityReport(
            feasible=False,
            reasons=("outside_travel_window",),
            usable_window=usable,
        )

    if _can_schedule(
        trip.tracks,
        fixed=None,
        usable=usable,
        min_rest_days=trip_fit.min_rest_days_between_walks,
    ):
        return TripFeasibilityReport(feasible=True, reasons=(), usable_window=usable)

    return TripFeasibilityReport(
        feasible=False,
        reasons=("insufficient_room_for_remaining_tracks",),
        usable_window=usable,
    )
