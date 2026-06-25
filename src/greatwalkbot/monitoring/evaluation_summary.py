"""Aggregate itinerary evaluation counts for concise operational logging."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from greatwalkbot.monitoring.models import AvailableItinerary


@dataclass
class ItineraryEvaluationSummary:
    """Per-track counts from itinerary validation during one availability check."""

    track_slug: str
    candidates: int = 0
    complete: int = 0
    incomplete: int = 0
    _reason_counts: dict[str, int] = field(default_factory=dict)

    def record_complete(self) -> None:
        self.candidates += 1
        self.complete += 1

    def record_incomplete(self, reasons: tuple[str, ...]) -> None:
        self.candidates += 1
        self.incomplete += 1
        for reason in reasons or ("unknown",):
            self._reason_counts[reason] = self._reason_counts.get(reason, 0) + 1

    @property
    def reason_counts(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(self._reason_counts.items()))

    def format_log_line(self) -> str:
        base = (
            f"Evaluation summary: track={self.track_slug} "
            f"candidates={self.candidates} complete={self.complete} "
            f"incomplete={self.incomplete}"
        )
        if self.incomplete and self._reason_counts:
            reasons = ",".join(
                f"{reason}:{count}" for reason, count in self.reason_counts
            )
            return f"{base} reasons={reasons}"
        return base

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "track_slug": self.track_slug,
            "candidates": self.candidates,
            "complete": self.complete,
            "incomplete": self.incomplete,
        }
        if self._reason_counts:
            payload["reason_counts"] = dict(self.reason_counts)
        return payload


@dataclass(frozen=True)
class MatchingResult:
    """Itineraries that passed matching plus evaluation aggregates for logging."""

    itineraries: tuple[AvailableItinerary, ...]
    evaluation: ItineraryEvaluationSummary
