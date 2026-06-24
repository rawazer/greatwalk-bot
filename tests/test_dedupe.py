"""Tests for notification deduplication."""

from datetime import date

from greatwalkbot.monitoring.dedupe import SeenAvailabilityStore
from support import make_itinerary


def _itinerary(start: str):
    return make_itinerary(start_date=date.fromisoformat(start), spaces=4)


def test_seen_store_suppresses_repeats():
    store = SeenAvailabilityStore()
    first = _itinerary("2026-12-07")

    assert store.is_new(first)
    assert store.filter_new((first,)) == (first,)

    store.mark_seen(first)
    assert not store.is_new(first)
    assert store.filter_new((first,)) == ()
