"""Match availability snapshots against watch preferences."""

from __future__ import annotations

from greatwalkbot.config.models import TrackWatchConfig
from greatwalkbot.models import AvailabilitySnapshot, AvailabilityStatus
from greatwalkbot.monitoring.models import AvailableItinerary


def find_matching_itineraries(
    snapshot: AvailabilitySnapshot,
    track_config: TrackWatchConfig,
    party_size: int,
) -> tuple[AvailableItinerary, ...]:
    """Return bookable itineraries within configured date ranges for the party size."""
    if snapshot.track.slug != track_config.slug:
        raise ValueError(
            f"Snapshot track {snapshot.track.slug!r} does not match config {track_config.slug!r}"
        )

    matches: list[AvailableItinerary] = []
    for day in snapshot.days:
        preference = track_config.preference_for(day.date)
        if preference is None:
            continue
        if day.status not in (AvailabilityStatus.AVAILABLE, AvailabilityStatus.LIMITED):
            continue
        if day.spaces < party_size:
            continue
        if not day.facilities:
            continue

        matches.append(
            AvailableItinerary(
                track_slug=snapshot.track.slug,
                track_name=snapshot.track.name,
                start_date=day.date,
                spaces=day.spaces,
                facilities=day.facilities,
                preference=preference,  # type: ignore[arg-type]
            )
        )

    return tuple(matches)
