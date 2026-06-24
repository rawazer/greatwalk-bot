"""Track seen availability to suppress duplicate notifications."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Protocol

from greatwalkbot.monitoring.models import AvailableItinerary


class SeenStore(Protocol):
    def is_new(self, itinerary: AvailableItinerary) -> bool: ...

    def mark_seen(self, itinerary: AvailableItinerary) -> None: ...

    def filter_new(
        self, itineraries: tuple[AvailableItinerary, ...]
    ) -> tuple[AvailableItinerary, ...]: ...


def _dedupe_key(itinerary: AvailableItinerary) -> tuple[str, date, tuple[str, ...]]:
    return itinerary.dedupe_key


class SeenAvailabilityStore:
    """In-memory store of itineraries already notified."""

    def __init__(self) -> None:
        self._seen: set[tuple[str, date, tuple[str, ...]]] = set()

    def is_new(self, itinerary: AvailableItinerary) -> bool:
        return _dedupe_key(itinerary) not in self._seen

    def mark_seen(self, itinerary: AvailableItinerary) -> None:
        self._seen.add(_dedupe_key(itinerary))

    def filter_new(
        self, itineraries: tuple[AvailableItinerary, ...]
    ) -> tuple[AvailableItinerary, ...]:
        return tuple(it for it in itineraries if self.is_new(it))

    def __len__(self) -> int:
        return len(self._seen)


class SqliteSeenAvailabilityStore:
    """Persistent SQLite store of itineraries already notified."""

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS seen_itineraries (
            track_slug TEXT NOT NULL,
            start_date TEXT NOT NULL,
            facilities TEXT NOT NULL,
            seen_at TEXT NOT NULL,
            PRIMARY KEY (track_slug, start_date, facilities)
        )
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(self._SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def is_new(self, itinerary: AvailableItinerary) -> bool:
        key = _dedupe_key(itinerary)
        row = self._conn.execute(
            """
            SELECT 1 FROM seen_itineraries
            WHERE track_slug = ? AND start_date = ? AND facilities = ?
            """,
            (key[0], key[1].isoformat(), json.dumps(list(key[2]))),
        ).fetchone()
        return row is None

    def mark_seen(self, itinerary: AvailableItinerary) -> None:
        key = _dedupe_key(itinerary)
        self._conn.execute(
            """
            INSERT OR IGNORE INTO seen_itineraries
            (track_slug, start_date, facilities, seen_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                key[0],
                key[1].isoformat(),
                json.dumps(list(key[2])),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def filter_new(
        self, itineraries: tuple[AvailableItinerary, ...]
    ) -> tuple[AvailableItinerary, ...]:
        return tuple(it for it in itineraries if self.is_new(it))

    def __len__(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM seen_itineraries").fetchone()
        return int(row[0]) if row else 0
