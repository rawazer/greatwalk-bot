"""Runtime metrics persisted for status reporting."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class MetricsSnapshot:
    started_at: str
    polls_completed: int = 0
    successful_polls: int = 0
    failed_polls: int = 0
    browser_restarts: int = 0
    average_poll_duration_seconds: float = 0.0
    last_poll_at: str | None = None
    last_successful_poll_at: str | None = None
    trip_name: str | None = None


class RuntimeMetrics:
    """Collect and persist basic watcher runtime metrics."""

    def __init__(self, status_path: Path, trip_name: str | None = None) -> None:
        self.status_path = status_path
        self.trip_name = trip_name
        self.started_at = _utc_now()
        self.polls_completed = 0
        self.successful_polls = 0
        self.failed_polls = 0
        self.browser_restarts = 0
        self._total_poll_duration_seconds = 0.0
        self.last_poll_at: datetime | None = None
        self.last_successful_poll_at: datetime | None = None
        self._lock = threading.Lock()

    def record_poll_start(self) -> float:
        return time.monotonic()

    def record_poll_success(self, started_monotonic: float) -> None:
        duration = time.monotonic() - started_monotonic
        with self._lock:
            self.polls_completed += 1
            self.successful_polls += 1
            self._total_poll_duration_seconds += duration
            now = _utc_now()
            self.last_poll_at = now
            self.last_successful_poll_at = now
        self.flush()

    def record_poll_failure(self, started_monotonic: float) -> None:
        duration = time.monotonic() - started_monotonic
        with self._lock:
            self.polls_completed += 1
            self.failed_polls += 1
            self._total_poll_duration_seconds += duration
            self.last_poll_at = _utc_now()
        self.flush()

    def record_browser_restart(self) -> None:
        with self._lock:
            self.browser_restarts += 1
        self.flush()

    @property
    def average_poll_duration_seconds(self) -> float:
        with self._lock:
            if self.polls_completed == 0:
                return 0.0
            return self._total_poll_duration_seconds / self.polls_completed

    def snapshot(self) -> MetricsSnapshot:
        with self._lock:
            average = (
                self._total_poll_duration_seconds / self.polls_completed
                if self.polls_completed
                else 0.0
            )
            return MetricsSnapshot(
                started_at=_iso(self.started_at) or "",
                polls_completed=self.polls_completed,
                successful_polls=self.successful_polls,
                failed_polls=self.failed_polls,
                browser_restarts=self.browser_restarts,
                average_poll_duration_seconds=average,
                last_poll_at=_iso(self.last_poll_at),
                last_successful_poll_at=_iso(self.last_successful_poll_at),
                trip_name=self.trip_name,
            )

    def flush(self) -> None:
        snapshot = self.snapshot()
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        self.status_path.write_text(
            json.dumps(asdict(snapshot), indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, status_path: Path) -> MetricsSnapshot | None:
        if not status_path.is_file():
            return None
        try:
            raw = json.loads(status_path.read_text(encoding="utf-8"))
            return MetricsSnapshot(**raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.exception("Failed to load metrics from %s", status_path)
            return None
