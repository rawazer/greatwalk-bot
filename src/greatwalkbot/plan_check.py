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
    confirmed = sorted(trip.confirmed_bookings(), key=lambda booking: booking.start_date)
    unconfirmed = trip.unconfirmed_tracks()

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
    ]

    lines.append("Confirmed bookings:")
    if confirmed:
        for booking in confirmed:
            lines.append(
                f"  - {booking.track_slug}: {booking.start_date.isoformat()}"
                f"..{booking.end_date.isoformat()} ({booking.nights} nights)"
            )
            if booking.direction:
                lines.append(f"      direction: {booking.direction}")
            if booking.notes:
                lines.append(f"      notes: {booking.notes}")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("Remaining walks to monitor:")
    if unconfirmed:
        for pref in unconfirmed:
            nights = get_itinerary_nights(pref.slug)
            lines.append(f"  - {pref.slug} ({nights} nights)")
            lines.append(
                f"      acceptable starts: {pref.acceptable_start_range.start.isoformat()}"
                f"..{pref.acceptable_start_range.end.isoformat()}"
            )
    else:
        lines.append("  (none — all configured tracks are confirmed)")

    lines.append("")
    lines.append("All configured tracks:")
    for pref in trip.tracks:
        nights = get_itinerary_nights(pref.slug)
        status = "confirmed" if pref.confirmed_booking else "monitoring"
        lines.append(f"  - {pref.slug} [{status}]")
        lines.append(
            f"      acceptable starts: {pref.acceptable_start_range.start.isoformat()}"
            f"..{pref.acceptable_start_range.end.isoformat()}"
        )
        lines.append(f"      complete itinerary nights: {nights}")
        lines.append(f"      direction: {pref.direction.value}")

    lines.append("")
    if not unconfirmed:
        lines.append(
            "Feasibility: YES — no remaining walks to schedule "
            "(all tracks confirmed)."
        )
    elif report.feasible:
        if confirmed:
            lines.append(
                "Feasibility: YES — remaining walks can fit around "
                "confirmed bookings in principle."
            )
        else:
            lines.append(
                "Feasibility: YES — all configured walks can fit in principle."
            )
    else:
        if confirmed:
            lines.append(
                "Feasibility: NO — remaining walks cannot fit around "
                "confirmed bookings in principle."
            )
        else:
            lines.append(
                "Feasibility: NO — configured walks cannot all fit in principle."
            )
        lines.append(f"Reasons: {', '.join(report.reasons)}")

    lines.append("")
    lines.append(
        "Note: plausible layout does not mean other walks are actually available."
    )
    return "\n".join(lines)
