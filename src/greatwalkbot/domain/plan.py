"""Operational settings combined with a trip plan."""

from __future__ import annotations

from dataclasses import dataclass, field

from greatwalkbot.domain.notifications import NotificationConfig
from greatwalkbot.domain.trip import Trip
from greatwalkbot.domain.trip_fit import TripFitConfig


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("retry.max_attempts must be at least 1")


@dataclass(frozen=True)
class TripPlan:
    """A trip plus the runtime settings used to monitor it."""

    trip: Trip
    polling_interval_seconds: int
    source: str = "playwright"
    retry: RetryConfig = field(default_factory=RetryConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    trip_fit: TripFitConfig = field(default_factory=TripFitConfig)

    def __post_init__(self) -> None:
        if self.polling_interval_seconds < 1:
            raise ValueError("polling_interval must be at least 1 second")
        if self.source not in ("playwright", "http"):
            raise ValueError("source must be playwright or http")

    @property
    def party_size(self) -> int:
        return self.trip.party.size
