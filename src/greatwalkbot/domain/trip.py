"""A complete New Zealand trip plan."""

from __future__ import annotations

from dataclasses import dataclass

from greatwalkbot.domain.party import Party
from greatwalkbot.domain.dates import TravelWindow
from greatwalkbot.domain.track import TrackPreference


@dataclass(frozen=True)
class Trip:
    name: str
    party: Party
    travel_window: TravelWindow
    tracks: tuple[TrackPreference, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("trip.name must not be empty")
        if not self.tracks:
            raise ValueError("trip must include at least one track preference")
        for track in self.tracks:
            track.validate_against(self.travel_window)
