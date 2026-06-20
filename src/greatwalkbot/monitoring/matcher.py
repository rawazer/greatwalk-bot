"""Match availability snapshots against trip track preferences."""

from __future__ import annotations

from greatwalkbot.domain.dates import TravelWindow
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.models import AvailabilitySnapshot, AvailabilityStatus
from greatwalkbot.monitoring.models import AvailableItinerary


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

    matches: list[AvailableItinerary] = []
    for day in snapshot.days:
        level = preference.preference_for(day.date, travel_window)
        if level is None:
            continue
        if day.status not in (AvailabilityStatus.AVAILABLE, AvailabilityStatus.LIMITED):
            continue
        if day.spaces < party.size:
            continue
        if not day.facilities:
            continue
        if preference.complete_itinerary_only and snapshot.track.fixed_nights:
            # Fixed-itinerary Great Walks are evaluated by start date; the snapshot
            # already represents whole-itinerary availability for that date.
            pass

        matches.append(
            AvailableItinerary(
                track_slug=snapshot.track.slug,
                track_name=snapshot.track.name,
                start_date=day.date,
                spaces=day.spaces,
                facilities=day.facilities,
                preference=level,
            )
        )

    return tuple(matches)
