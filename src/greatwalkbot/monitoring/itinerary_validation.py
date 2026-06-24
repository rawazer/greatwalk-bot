"""Validate complete Great Walk itineraries against facility-level availability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from greatwalkbot.domain.direction import DirectionPreference
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.facility_index import FacilityAvailabilityIndex
from greatwalkbot.models import AvailabilitySnapshot, AvailabilityStatus
from greatwalkbot.monitoring.models import AvailableItinerary, NightAvailabilitySummary
from greatwalkbot.track_durations import end_date_for_start
from greatwalkbot.track_itineraries import ItineraryDefinition, definitions_for_track


@dataclass(frozen=True)
class ItineraryValidationResult:
    track_slug: str
    track_name: str
    start_date: date
    direction: str | None
    party_size: int
    complete_itinerary: bool
    nights: tuple[NightAvailabilitySummary, ...]
    bottleneck_spaces: int
    failure_reasons: tuple[str, ...]
    validation_notes: tuple[str, ...]

    @property
    def required_facilities(self) -> tuple[str, ...]:
        return tuple(night.facility_name for night in self.nights)


def _validate_definition(
    definition: ItineraryDefinition,
    *,
    track_name: str,
    start_date: date,
    party_size: int,
    index: FacilityAvailabilityIndex,
) -> ItineraryValidationResult:
    night_summaries: list[NightAvailabilitySummary] = []
    failure_reasons: list[str] = []
    notes: list[str] = []
    bottleneck: int | None = None

    for required in definition.required_nights:
        arrival = start_date + timedelta(days=required.night_index)
        spaces = index.spaces_on(required.facility_name, arrival)
        if spaces is None:
            failure_reasons.append("missing_facility_data")
            night_summaries.append(
                NightAvailabilitySummary(
                    night_index=required.night_index,
                    arrival_date=arrival,
                    facility_name=required.facility_name,
                    spaces=None,
                    party_size=party_size,
                    satisfied=False,
                )
            )
            notes.append(
                f"No DOC row for {required.facility_name} on {arrival.isoformat()}"
            )
            continue

        satisfied = spaces >= party_size
        if spaces <= 0:
            failure_reasons.append("facility_unavailable")
        elif not satisfied:
            failure_reasons.append("insufficient_party_spaces")

        night_summaries.append(
            NightAvailabilitySummary(
                night_index=required.night_index,
                arrival_date=arrival,
                facility_name=required.facility_name,
                spaces=spaces,
                party_size=party_size,
                satisfied=satisfied,
            )
        )
        if satisfied:
            bottleneck = spaces if bottleneck is None else min(bottleneck, spaces)

    complete = bool(night_summaries) and all(n.satisfied for n in night_summaries)
    if not complete and not failure_reasons:
        failure_reasons.append("incomplete_itinerary")

    return ItineraryValidationResult(
        track_slug=definition.track_slug,
        track_name=track_name,
        start_date=start_date,
        direction=definition.direction,
        party_size=party_size,
        complete_itinerary=complete,
        nights=tuple(night_summaries),
        bottleneck_spaces=bottleneck if complete and bottleneck is not None else 0,
        failure_reasons=tuple(dict.fromkeys(failure_reasons)),
        validation_notes=tuple(notes),
    )


def validate_complete_itineraries(
    *,
    index: FacilityAvailabilityIndex,
    snapshot: AvailabilitySnapshot,
    preference: TrackPreference,
    start_date: date,
    party: Party,
) -> tuple[ItineraryValidationResult, ...]:
    """Validate all applicable itinerary directions for one candidate start date."""
    definitions = definitions_for_track(preference.slug, preference.direction)
    if not definitions:
        return (
            ItineraryValidationResult(
                track_slug=preference.slug,
                track_name=snapshot.track.name,
                start_date=start_date,
                direction=None,
                party_size=party.size,
                complete_itinerary=False,
                nights=(),
                bottleneck_spaces=0,
                failure_reasons=("no_itinerary_definition",),
                validation_notes=(
                    f"No complete-itinerary metadata registered for {preference.slug!r}",
                ),
            ),
        )

    return tuple(
        _validate_definition(
            definition,
            track_name=snapshot.track.name,
            start_date=start_date,
            party_size=party.size,
            index=index,
        )
        for definition in definitions
    )


def validation_to_itinerary(
    result: ItineraryValidationResult,
    *,
    preference_level: str,
    itinerary_nights: int,
) -> AvailableItinerary:
    end = end_date_for_start(result.start_date, itinerary_nights)
    return AvailableItinerary(
        track_slug=result.track_slug,
        track_name=result.track_name,
        start_date=result.start_date,
        end_date=end,
        itinerary_nights=itinerary_nights,
        spaces=result.bottleneck_spaces,
        facilities=result.required_facilities,
        preference=preference_level,  # type: ignore[arg-type]
        complete_itinerary=result.complete_itinerary,
        party_size=result.party_size,
        direction=result.direction,
        night_summaries=result.nights,
        validation_notes=result.validation_notes,
    )


def day_is_candidate(
    day_status: AvailabilityStatus,
    *,
    spaces: int,
    party_size: int,
) -> bool:
    return (
        day_status in (AvailabilityStatus.AVAILABLE, AvailabilityStatus.LIMITED)
        and spaces >= party_size
    )
