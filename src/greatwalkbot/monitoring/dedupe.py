"""Track seen availability to suppress duplicate notifications."""

from __future__ import annotations

from datetime import date

from greatwalkbot.monitoring.models import AvailableItinerary


class SeenAvailabilityStore:
    """In-memory store of itineraries already notified."""

    def __init__(self) -> None:
        self._seen: set[tuple[str, date, tuple[str, ...]]] = set()

    def is_new(self, itinerary: AvailableItinerary) -> bool:
        return itinerary.dedupe_key not in self._seen

    def mark_seen(self, itinerary: AvailableItinerary) -> None:
        self._seen.add(itinerary.dedupe_key)

    def filter_new(self, itineraries: tuple[AvailableItinerary, ...]) -> tuple[AvailableItinerary, ...]:
        return tuple(it for it in itineraries if self.is_new(it))

    def __len__(self) -> int:
        return len(self._seen)
