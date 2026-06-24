"""Runtime metrics persisted for status reporting."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from greatwalkbot.monitoring.status import (
    STATUS_SCHEMA_VERSION,
    LastError,
    RuntimeState,
    StatusSnapshot,
    atomic_write_json,
    load_status_snapshot,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RuntimeMetrics:
    """Collect and persist basic watcher runtime metrics."""

    def __init__(self, status_path: Path, trip_name: str | None = None) -> None:
        self.status_path = status_path
        self.trip_name = trip_name
        self.started_at = _utc_now()
        self.state = RuntimeState.STARTING
        self.polls_completed = 0
        self.successful_polls = 0
        self.failed_polls = 0
        self.browser_restarts = 0
        self._total_poll_duration_seconds = 0.0
        self.last_poll_at: datetime | None = None
        self.last_successful_poll_at: datetime | None = None
        self._last_error: LastError | None = None
        self._lock = threading.Lock()

    def set_state(self, state: RuntimeState) -> None:
        with self._lock:
            self.state = state
        self.flush()

    def record_poll_start(self) -> float:
        return time.monotonic()

    def record_fetch_error(self, track_slug: str, message: str) -> None:
        with self._lock:
            self._last_error = LastError(
                at=_iso(_utc_now()) or "",
                message=message,
                track_slug=track_slug,
            )

    def record_poll_success(self, started_monotonic: float) -> None:
        duration = time.monotonic() - started_monotonic
        with self._lock:
            self.polls_completed += 1
            self.successful_polls += 1
            self._total_poll_duration_seconds += duration
            now = _utc_now()
            self.last_poll_at = now
            self.last_successful_poll_at = now
            if self.state != RuntimeState.STOPPING:
                self.state = RuntimeState.POLLING
        self.flush()

    def record_poll_failure(self, started_monotonic: float) -> None:
        duration = time.monotonic() - started_monotonic
        with self._lock:
            self.polls_completed += 1
            self.failed_polls += 1
            self._total_poll_duration_seconds += duration
            self.last_poll_at = _utc_now()
            if self.state != RuntimeState.STOPPING:
                self.state = RuntimeState.ERROR
        self.flush()

    def record_browser_restart(self) -> None:
        with self._lock:
            self.browser_restarts += 1
        self.flush()

    def snapshot(self) -> StatusSnapshot:
        with self._lock:
            average = (
                self._total_poll_duration_seconds / self.polls_completed
                if self.polls_completed
                else 0.0
            )
            return StatusSnapshot(
                schema_version=STATUS_SCHEMA_VERSION,
                started_at=_iso(self.started_at) or "",
                state=self.state.value,
                polls_completed=self.polls_completed,
                successful_polls=self.successful_polls,
                failed_polls=self.failed_polls,
                browser_restarts=self.browser_restarts,
                average_poll_duration_seconds=average,
                last_poll_at=_iso(self.last_poll_at),
                last_successful_poll_at=_iso(self.last_successful_poll_at),
                trip_name=self.trip_name,
                last_error=self._last_error,
            )

    def flush(self) -> None:
        atomic_write_json(self.status_path, self.snapshot().to_dict())

    @classmethod
    def load(cls, status_path: Path) -> StatusSnapshot | None:
        return load_status_snapshot(status_path)
