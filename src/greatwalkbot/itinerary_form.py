"""Itinerary duration for Great Walk search form binding."""

from __future__ import annotations

from greatwalkbot.domain.direction import DirectionPreference
from greatwalkbot.track_itineraries import definitions_for_track, has_itinerary_definition


def itinerary_form_nights(
    track_slug: str,
    direction: DirectionPreference = DirectionPreference.EITHER,
) -> tuple[int, str | None]:
    """Return registered hike nights and direction slug used for the form.

  For Routeburn with ``direction: either``, the forward itinerary is used by
  default (both directions share the same 2-night duration).
    """
    definitions = definitions_for_track(track_slug, direction)
    if not definitions:
        raise ValueError(f"No itinerary definition for track {track_slug!r}")
    chosen = definitions[0]
    return chosen.nights, chosen.direction


def resolve_form_nights(
    track_slug: str,
    *,
    complete_itinerary_only: bool,
    direction: DirectionPreference = DirectionPreference.EITHER,
    fixed_nights: int | None = None,
    fallback_nights: int | None = None,
) -> tuple[int, str | None]:
    """Resolve nights for SPA form submission."""
    if complete_itinerary_only or has_itinerary_definition(track_slug):
        return itinerary_form_nights(track_slug, direction)
    if fixed_nights is not None:
        return fixed_nights, None
    if fallback_nights is not None:
        return fallback_nights, None
    raise ValueError(
        f"Cannot resolve form nights for {track_slug!r} "
        "(no itinerary definition and no fixed_nights)"
    )
