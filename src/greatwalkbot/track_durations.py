"""Registered complete-itinerary durations for Great Walk tracks."""

from __future__ import annotations

from datetime import date, timedelta

from greatwalkbot.tracks import resolve_track

# Complete-itinerary night counts from DOC fixed-itinerary products.
# end_date = start_date + itinerary_nights (last calendar day on the track).
# See docs/trip-fit.md for sources and assumptions.
ITINERARY_NIGHTS: dict[str, int] = {
    "milford": 3,
    "routeburn": 2,
    "kepler": 3,
}


def get_itinerary_nights(slug: str) -> int:
    """Return the fixed night count for a complete Great Walk itinerary."""
    normalized = slug.strip().lower().replace("_", "-")
    if normalized in ITINERARY_NIGHTS:
        return ITINERARY_NIGHTS[normalized]
    track = resolve_track(normalized)
    if track.fixed_nights is not None:
        return track.fixed_nights
    raise ValueError(
        f"No complete-itinerary duration registered for track {slug!r}. "
        "Add it to ITINERARY_NIGHTS in track_durations.py."
    )


def end_date_for_start(start: date, itinerary_nights: int) -> date:
    """Return the last calendar day occupied by a walk starting on start."""
    if itinerary_nights < 1:
        raise ValueError("itinerary_nights must be at least 1")
    return start + timedelta(days=itinerary_nights)
