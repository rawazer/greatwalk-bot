"""Tests for notification deduplication."""

from datetime import date

from greatwalkbot.monitoring.dedupe import SeenAvailabilityStore
from greatwalkbot.monitoring.models import AvailableItinerary


def _itinerary(start: str) -> AvailableItinerary:
    return AvailableItinerary(
        track_slug="milford",
        track_name="Milford Track",
        start_date=date.fromisoformat(start),
        spaces=4,
        facilities=("Clinton Hut",),
        preference="preferred",
    )


def test_seen_store_suppresses_repeats():
    store = SeenAvailabilityStore()
    first = _itinerary("2026-12-07")

    assert store.is_new(first)
    assert store.filter_new((first,)) == (first,)

    store.mark_seen(first)
    assert not store.is_new(first)
    assert store.filter_new((first,)) == ()
