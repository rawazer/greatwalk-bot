"""Operational settings combined with a trip plan."""

from __future__ import annotations

from dataclasses import dataclass

from greatwalkbot.domain.trip import Trip


@dataclass(frozen=True)
class TripPlan:
    """A trip plus the runtime settings used to monitor it."""

    trip: Trip
    polling_interval_seconds: int
    source: str = "playwright"

    def __post_init__(self) -> None:
        if self.polling_interval_seconds < 1:
            raise ValueError("polling_interval must be at least 1 second")
        if self.source not in ("playwright", "http"):
            raise ValueError("source must be playwright or http")

    @property
    def party_size(self) -> int:
        return self.trip.party.size
