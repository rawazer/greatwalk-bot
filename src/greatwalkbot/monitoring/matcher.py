"""Match availability snapshots against trip track preferences."""

from __future__ import annotations

import logging

from greatwalkbot.domain.dates import TravelWindow
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.models import AvailabilitySnapshot
from greatwalkbot.monitoring.itinerary_validation import (
    day_is_candidate,
    validate_complete_itineraries,
    validation_to_itinerary,
)
from greatwalkbot.monitoring.models import AvailableItinerary
from greatwalkbot.track_durations import get_itinerary_nights

logger = logging.getLogger(__name__)


def find_matching_itineraries(
    snapshot: AvailabilitySnapshot,
    preference: TrackPreference,
    party: Party,
    travel_window: TravelWindow,
) -> tuple[AvailableItinerary, ...]:
    """Return bookable itineraries that satisfy the track and trip constraints."""
    if snapshot.track.slug != preference.slug:
        raise ValueError(
            f"Snapshot track {snapshot.track.slug!r} does not match preference {preference.slug!r}"
        )

    requires_validation = preference.complete_itinerary_only
    matches: list[AvailableItinerary] = []

    for day in snapshot.days:
        level = preference.preference_for(day.date, travel_window)
        if level is None:
            continue
        if not day_is_candidate(day.status, spaces=day.spaces, party_size=party.size):
            continue
        if not day.facilities and not requires_validation:
            continue

        if requires_validation:
            if snapshot.facility_index is None:
                logger.info(
                    "Skipped unverified itinerary for %s on %s: no facility index",
                    snapshot.track.slug,
                    day.date.isoformat(),
                )
                continue

            validations = validate_complete_itineraries(
                index=snapshot.facility_index,
                snapshot=snapshot,
                preference=preference,
                start_date=day.date,
                party=party,
            )
            for result in validations:
                if not result.complete_itinerary:
                    logger.info(
                        "Skipped incomplete itinerary for %s on %s%s: %s",
                        snapshot.track.slug,
                        day.date.isoformat(),
                        f" ({result.direction})" if result.direction else "",
                        ", ".join(result.failure_reasons) or "unknown",
                    )
                    continue
                nights = get_itinerary_nights(snapshot.track.slug)
                matches.append(
                    validation_to_itinerary(
                        result,
                        preference_level=level,
                        itinerary_nights=nights,
                    )
                )
            continue

        if not day.facilities:
            continue

        from greatwalkbot.track_durations import end_date_for_start

        nights = get_itinerary_nights(snapshot.track.slug)
        start = day.date
        matches.append(
            AvailableItinerary(
                track_slug=snapshot.track.slug,
                track_name=snapshot.track.name,
                start_date=start,
                end_date=end_date_for_start(start, nights),
                itinerary_nights=nights,
                spaces=day.spaces,
                facilities=day.facilities,
                preference=level,
                complete_itinerary=False,
                party_size=party.size,
                validation_notes=("legacy_day_level_match",),
            )
        )

    return tuple(matches)
