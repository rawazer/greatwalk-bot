"""Trip-fit configuration for multi-walk feasibility checks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TripFitConfig:
    enabled: bool = False
    min_rest_days_between_walks: int = 1
    buffer_days_before_first_walk: int = 1
    buffer_days_after_last_walk: int = 1

    def __post_init__(self) -> None:
        if self.min_rest_days_between_walks < 0:
            raise ValueError("min_rest_days_between_walks must be >= 0")
        if self.buffer_days_before_first_walk < 0:
            raise ValueError("buffer_days_before_first_walk must be >= 0")
        if self.buffer_days_after_last_walk < 0:
            raise ValueError("buffer_days_after_last_walk must be >= 0")
