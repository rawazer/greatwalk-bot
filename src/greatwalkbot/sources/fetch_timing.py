"""Per-track fetch timing for poll diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class TrackFetchTiming:
    track_slug: str
    navigation_seconds: float
    app_ready_seconds: float
    capture_seconds: float
    total_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def log_line(self) -> str:
        return (
            f"track={self.track_slug} "
            f"nav={self.navigation_seconds:.1f}s "
            f"app_ready={self.app_ready_seconds:.1f}s "
            f"capture={self.capture_seconds:.1f}s "
            f"total={self.total_seconds:.1f}s"
        )
