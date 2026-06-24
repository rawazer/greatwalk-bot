"""Runtime status schema and atomic persistence."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

STATUS_SCHEMA_VERSION = 1


class RuntimeState(str, Enum):
    STARTING = "starting"
    POLLING = "polling"
    SLEEPING = "sleeping"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass(frozen=True)
class LastError:
    at: str
    message: str
    track_slug: str | None = None


@dataclass
class StatusSnapshot:
    """Documented JSON contract for logs/status.json."""

    schema_version: int
    started_at: str
    state: str
    polls_completed: int = 0
    successful_polls: int = 0
    failed_polls: int = 0
    browser_restarts: int = 0
    average_poll_duration_seconds: float = 0.0
    last_poll_at: str | None = None
    last_successful_poll_at: str | None = None
    trip_name: str | None = None
    last_error: LastError | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.last_error is None:
            payload["last_error"] = None
        return payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically so readers never see partial content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temp_path, path)


def load_status_snapshot(path: Path) -> StatusSnapshot | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        last_error_raw = raw.get("last_error")
        last_error = None
        if isinstance(last_error_raw, dict):
            last_error = LastError(
                at=str(last_error_raw["at"]),
                message=str(last_error_raw["message"]),
                track_slug=last_error_raw.get("track_slug"),
            )
        return StatusSnapshot(
            schema_version=int(raw.get("schema_version", 1)),
            started_at=str(raw["started_at"]),
            state=str(raw.get("state", RuntimeState.STOPPED.value)),
            polls_completed=int(raw.get("polls_completed", 0)),
            successful_polls=int(raw.get("successful_polls", 0)),
            failed_polls=int(raw.get("failed_polls", 0)),
            browser_restarts=int(raw.get("browser_restarts", 0)),
            average_poll_duration_seconds=float(
                raw.get("average_poll_duration_seconds", 0.0)
            ),
            last_poll_at=raw.get("last_poll_at"),
            last_successful_poll_at=raw.get("last_successful_poll_at"),
            trip_name=raw.get("trip_name"),
            last_error=last_error,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
