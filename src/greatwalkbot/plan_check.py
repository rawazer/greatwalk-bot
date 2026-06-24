"""Format plan-check output."""

from __future__ import annotations

from greatwalkbot.domain.plan import TripPlan
from greatwalkbot.monitoring.trip_fit import check_trip_feasible_in_principle, usable_window
from greatwalkbot.track_durations import get_itinerary_nights


def format_plan_check(plan: TripPlan) -> str:
    trip = plan.trip
    trip_fit = plan.trip_fit
    usable = usable_window(trip.travel_window, trip_fit)
    report = check_trip_feasible_in_principle(trip, trip_fit)

    lines = [
        f"Trip: {trip.name}",
        f"Travel window: {trip.travel_window.start.isoformat()}..{trip.travel_window.end.isoformat()}",
        f"Party size: {trip.party.size}",
        "",
        "Trip-fit rules:",
        f"  enabled: {trip_fit.enabled}",
        f"  min_rest_days_between_walks: {trip_fit.min_rest_days_between_walks}",
        f"  buffer_days_before_first_walk: {trip_fit.buffer_days_before_first_walk}",
        f"  buffer_days_after_last_walk: {trip_fit.buffer_days_after_last_walk}",
        f"  usable scheduling window: {usable.start.isoformat()}..{usable.end.isoformat()}",
        "",
        "Configured tracks:",
    ]

    for pref in trip.tracks:
        nights = get_itinerary_nights(pref.slug)
        lines.append(f"  - {pref.slug}")
        lines.append(
            f"      acceptable starts: {pref.acceptable_start_range.start.isoformat()}"
            f"..{pref.acceptable_start_range.end.isoformat()}"
        )
        lines.append(f"      complete itinerary nights: {nights}")
        lines.append(f"      direction: {pref.direction.value}")

    lines.append("")
    if report.feasible:
        lines.append("Feasibility: YES — all configured walks can fit in principle.")
    else:
        lines.append("Feasibility: NO — configured walks cannot all fit in principle.")
        lines.append(f"Reasons: {', '.join(report.reasons)}")

    lines.append("")
    lines.append(
        "Note: plausible layout does not mean other walks are actually available."
    )
    return "\n".join(lines)
