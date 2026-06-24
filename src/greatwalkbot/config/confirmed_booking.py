"""Validate confirmed bookings against trip constraints."""

from __future__ import annotations

from greatwalkbot.domain.confirmed_booking import ConfirmedBooking
from greatwalkbot.domain.trip import Trip
from greatwalkbot.domain.trip_fit import TripFitConfig
from greatwalkbot.monitoring.trip_fit import _conflicts, usable_window
from greatwalkbot.track_durations import ITINERARY_NIGHTS
from greatwalkbot.tracks import resolve_track


def known_itinerary_nights(slug: str) -> int | None:
    """Return registered night count when known, else None."""
    normalized = slug.strip().lower().replace("_", "-")
    if normalized in ITINERARY_NIGHTS:
        return ITINERARY_NIGHTS[normalized]
    try:
        track = resolve_track(normalized)
    except ValueError:
        return None
    return track.fixed_nights


def validate_confirmed_booking_nights(
    track_slug: str,
    nights: int,
    *,
    allow_duration_override: bool,
    context: str,
) -> None:
    if nights < 1:
        raise ValueError(f"{context}.nights must be at least 1")

    known = known_itinerary_nights(track_slug)
    if known is None:
        return
    if nights != known and not allow_duration_override:
        raise ValueError(
            f"{context}.nights must be {known} for track {track_slug!r} "
            f"(got {nights}). Set allow_duration_override: true to override."
        )


def validate_confirmed_bookings(trip: Trip, trip_fit: TripFitConfig) -> None:
    """Validate all confirmed bookings for window, buffers, and mutual consistency."""
    bookings = trip.confirmed_bookings()
    if not bookings:
        return

    usable = usable_window(trip.travel_window, trip_fit)
    if usable.end < usable.start:
        raise ValueError(
            "travel_window is too short for configured trip_fit buffers "
            "with confirmed bookings"
        )

    for booking in bookings:
        context = f"tracks[{booking.track_slug}].confirmed_booking"
        if booking.start_date < usable.start or booking.end_date > usable.end:
            if (
                booking.start_date < trip.travel_window.start
                or booking.end_date > trip.travel_window.end
            ):
                raise ValueError(
                    f"{context} dates {booking.start_date.isoformat()}"
                    f"..{booking.end_date.isoformat()} fall outside travel_window"
                )
            raise ValueError(
                f"{context} dates {booking.start_date.isoformat()}"
                f"..{booking.end_date.isoformat()} overlap required trip_fit buffers"
            )

    min_rest = trip_fit.min_rest_days_between_walks
    for left in bookings:
        for right in bookings:
            if left.track_slug >= right.track_slug:
                continue
            if _booking_conflicts(left, right, min_rest):
                raise ValueError(
                    f"Confirmed bookings for {left.track_slug!r} "
                    f"({left.start_date.isoformat()}..{left.end_date.isoformat()}) "
                    f"and {right.track_slug!r} "
                    f"({right.start_date.isoformat()}..{right.end_date.isoformat()}) "
                    f"overlap or leave insufficient rest days "
                    f"(min_rest_days_between_walks={min_rest})"
                )


def _booking_conflicts(
    left: ConfirmedBooking,
    right: ConfirmedBooking,
    min_rest_days: int,
) -> bool:
    from greatwalkbot.monitoring.trip_fit import WalkInterval

    return _conflicts(
        WalkInterval(left.track_slug, left.start_date, left.end_date, left.nights),
        WalkInterval(right.track_slug, right.start_date, right.end_date, right.nights),
        min_rest_days,
    )
