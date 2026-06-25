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
    browser_start_seconds: float = 0.0
    shell_navigation_seconds: float = 0.0
    route_navigation_seconds: float = 0.0
    spa_readiness_seconds: float = 0.0
    navigation_recovered_after_timeout: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def log_line(self) -> str:
        parts = [
            f"track={self.track_slug}",
            f"shell_nav={self.shell_navigation_seconds:.1f}s",
            f"spa_ready={self.spa_readiness_seconds:.1f}s",
            f"capture={self.capture_seconds:.1f}s",
            f"total={self.total_seconds:.1f}s",
        ]
        if self.navigation_recovered_after_timeout:
            parts.append("nav_recovered=true")
        return " ".join(parts)
