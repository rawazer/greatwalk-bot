"""Error types for retry and recovery logic."""

from __future__ import annotations


class RetryableError(Exception):
    """Transient failure that may succeed on retry."""


class SessionError(RetryableError):
    """Browser or Playwright session is unhealthy."""


class FetchError(RetryableError):
    """Availability fetch failed but may succeed on retry."""
