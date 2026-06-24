"""Registered complete-itinerary facility sequences for Great Walk tracks.

Facility names are matched case-insensitively against DOC ``FacilityName`` values
in ``greatwalkplacefacility`` responses. Update this registry when DOC renames
huts or when investigation captures new response shapes.

See docs/itinerary-availability.md for sources and assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass

from greatwalkbot.domain.direction import DirectionPreference

# Direction slugs used in validation output and confirmed bookings.
ROUTEBURN_FORWARD = "routeburn-shelter-to-divide"
ROUTEBURN_REVERSE = "routeburn-divide-to-shelter"


@dataclass(frozen=True)
class RequiredNight:
    """One overnight stay in a complete itinerary."""

    night_index: int
    facility_name: str


@dataclass(frozen=True)
class ItineraryDefinition:
    track_slug: str
    direction: str | None
    nights: int
    required_nights: tuple[RequiredNight, ...]


ITINERARY_DEFINITIONS: dict[tuple[str, str | None], ItineraryDefinition] = {
    ("milford", None): ItineraryDefinition(
        track_slug="milford",
        direction=None,
        nights=3,
        required_nights=(
            RequiredNight(0, "Clinton Hut"),
            RequiredNight(1, "Mintaro Hut"),
            RequiredNight(2, "Dumpling Hut"),
        ),
    ),
    ("routeburn", ROUTEBURN_FORWARD): ItineraryDefinition(
        track_slug="routeburn",
        direction=ROUTEBURN_FORWARD,
        nights=2,
        required_nights=(
            RequiredNight(0, "Routeburn Falls Hut"),
            RequiredNight(1, "Lake Mackenzie Hut"),
        ),
    ),
    ("routeburn", ROUTEBURN_REVERSE): ItineraryDefinition(
        track_slug="routeburn",
        direction=ROUTEBURN_REVERSE,
        nights=2,
        required_nights=(
            RequiredNight(0, "Lake Mackenzie Hut"),
            RequiredNight(1, "Routeburn Falls Hut"),
        ),
    ),
    ("kepler", None): ItineraryDefinition(
        track_slug="kepler",
        direction=None,
        nights=3,
        required_nights=(
            RequiredNight(0, "Luxmore Hut"),
            RequiredNight(1, "Iris Burn Hut"),
            RequiredNight(2, "Moturau Hut"),
        ),
    ),
}


def definitions_for_track(
    track_slug: str,
    direction: DirectionPreference,
) -> tuple[ItineraryDefinition, ...]:
    """Return itinerary definitions to evaluate for a track and direction preference."""
    normalized = track_slug.strip().lower().replace("_", "-")
    if normalized != "routeburn":
        definition = ITINERARY_DEFINITIONS.get((normalized, None))
        return (definition,) if definition is not None else ()

    if direction == DirectionPreference.FORWARD:
        keys = (ROUTEBURN_FORWARD,)
    elif direction == DirectionPreference.REVERSE:
        keys = (ROUTEBURN_REVERSE,)
    else:
        keys = (ROUTEBURN_FORWARD, ROUTEBURN_REVERSE)

    return tuple(
        ITINERARY_DEFINITIONS[(normalized, key)]
        for key in keys
        if (normalized, key) in ITINERARY_DEFINITIONS
    )


def has_itinerary_definition(track_slug: str) -> bool:
    normalized = track_slug.strip().lower().replace("_", "-")
    return any(slug == normalized for slug, _ in ITINERARY_DEFINITIONS)
