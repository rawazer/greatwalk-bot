"""Error types for retry and recovery logic."""

from __future__ import annotations


class RetryableError(Exception):
    """Transient failure that may succeed on retry."""


class SessionError(RetryableError):
    """Browser or Playwright session is unhealthy."""


class FetchError(RetryableError):
    """Availability fetch failed but may succeed on retry."""


class NavigationError(RetryableError):
    """DOC page navigation timed out or failed."""


class UIReadinessError(RetryableError):
    """Great Walk UI did not become ready within the bounded wait."""


class TrackSelectorError(RetryableError):
    """Expected track dropdown item was not found after bounded recovery."""

    def __init__(
        self,
        message: str,
        *,
        track_slug: str | None = None,
        element_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.track_slug = track_slug
        self.element_id = element_id

