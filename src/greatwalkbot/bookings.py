"""Format confirmed booking listings."""

from __future__ import annotations

from greatwalkbot.domain.plan import TripPlan


def format_bookings(plan: TripPlan) -> str:
    trip = plan.trip
    bookings = sorted(trip.confirmed_bookings(), key=lambda booking: booking.start_date)

    lines = [
        f"Trip: {trip.name}",
        f"Travel window: {trip.travel_window.start.isoformat()}..{trip.travel_window.end.isoformat()}",
        "",
    ]

    if not bookings:
        lines.append("No confirmed bookings recorded.")
        return "\n".join(lines)

    lines.append("Confirmed bookings (chronological):")
    for booking in bookings:
        lines.append(
            f"  - {booking.track_slug}: {booking.start_date.isoformat()}"
            f"..{booking.end_date.isoformat()} ({booking.nights} nights)"
        )
        if booking.direction:
            lines.append(f"      direction: {booking.direction}")
        if booking.notes:
            lines.append(f"      notes: {booking.notes}")

    return "\n".join(lines)
