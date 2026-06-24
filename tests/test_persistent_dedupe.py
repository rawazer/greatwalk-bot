"""Tests for SQLite-backed deduplication."""

from datetime import date
from pathlib import Path

from greatwalkbot.monitoring.dedupe import SqliteSeenAvailabilityStore
from support import make_itinerary


def _itinerary(start: str):
    return make_itinerary(start_date=date.fromisoformat(start), spaces=4)


def test_sqlite_seen_store_persists_across_instances(tmp_path: Path):
    db_path = tmp_path / "seen.db"
    itinerary = _itinerary("2026-12-07")

    store = SqliteSeenAvailabilityStore(db_path)
    assert store.is_new(itinerary)
    store.mark_seen(itinerary)
    store.close()

    reloaded = SqliteSeenAvailabilityStore(db_path)
    assert not reloaded.is_new(itinerary)
    assert reloaded.filter_new((itinerary,)) == ()
    reloaded.close()


def test_sqlite_seen_store_filter_new(tmp_path: Path):
    db_path = tmp_path / "seen.db"
    first = _itinerary("2026-12-07")
    second = _itinerary("2026-12-08")

    store = SqliteSeenAvailabilityStore(db_path)
    store.mark_seen(first)
    assert store.filter_new((first, second)) == (second,)
    store.close()
