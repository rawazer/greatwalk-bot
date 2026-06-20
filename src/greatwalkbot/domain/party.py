"""Travelling party description."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Party:
    adults: int

    def __post_init__(self) -> None:
        if self.adults < 1:
            raise ValueError("party.adults must be at least 1")

    @property
    def size(self) -> int:
        return self.adults
