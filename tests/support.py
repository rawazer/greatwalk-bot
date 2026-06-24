"""Shared helpers for tests."""

from datetime import date

from greatwalkbot.monitoring.models import AvailableItinerary
from greatwalkbot.track_durations import end_date_for_start, get_itinerary_nights


def make_itinerary(
    *,
    track_slug: str = "milford",
    track_name: str = "Milford Track",
    start_date: date | None = None,
    itinerary_nights: int | None = None,
    spaces: int = 5,
    facilities: tuple[str, ...] = ("Clinton Hut",),
    preference: str = "preferred",
    trip_fit: bool | None = None,
    trip_fit_reasons: tuple[str, ...] = (),
) -> AvailableItinerary:
    start = start_date or date(2026, 12, 7)
    nights = itinerary_nights if itinerary_nights is not None else get_itinerary_nights(track_slug)
    return AvailableItinerary(
        track_slug=track_slug,
        track_name=track_name,
        start_date=start,
        end_date=end_date_for_start(start, nights),
        itinerary_nights=nights,
        spaces=spaces,
        facilities=facilities,
        preference=preference,
        trip_fit=trip_fit,
        trip_fit_reasons=trip_fit_reasons,
    )
