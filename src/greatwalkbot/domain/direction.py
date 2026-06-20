"""Track direction preferences."""

from __future__ import annotations

from enum import Enum


class DirectionPreference(str, Enum):
    EITHER = "either"
    FORWARD = "forward"
    REVERSE = "reverse"

    @classmethod
    def parse(cls, value: str) -> DirectionPreference:
        normalized = value.strip().lower()
        for member in cls:
            if member.value == normalized:
                return member
        known = ", ".join(m.value for m in cls)
        raise ValueError(f"direction must be one of {known}, got {value!r}")
