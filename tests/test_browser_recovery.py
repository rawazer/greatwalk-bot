"""Tests for browser recovery in PlaywrightAvailabilitySource."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from greatwalkbot.infra.errors import FetchError
from greatwalkbot.models import AvailabilitySnapshot, Track
from greatwalkbot.sources.playwright import PlaywrightAvailabilitySource
from greatwalkbot.sources.session_manager import SessionManager


MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)
SNAPSHOT = AvailabilitySnapshot(
    track=MILFORD,
    from_date=date(2026, 12, 1),
    to_date=date(2026, 12, 31),
    days=(),
)


def test_browser_recovery_restarts_session_and_retries():
    session = MagicMock(spec=SessionManager)
    session.is_healthy.return_value = True

    source = PlaywrightAvailabilitySource(
        session_manager=session,
        retry_policy=MagicMock(max_attempts=1, base_delay_seconds=0.01, max_delay_seconds=0.01),
    )

    calls = {"count": 0}

    def fetch_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise FetchError("session broken")
        return SNAPSHOT

    with patch.object(source, "_fetch_once", side_effect=fetch_once):
        with patch("greatwalkbot.sources.playwright.retry_call", side_effect=lambda fn, _policy: fn()):
            result = source.fetch_track_availability(
                MILFORD,
                date(2026, 12, 1),
                date(2026, 12, 31),
            )

    assert result is SNAPSHOT
    session.restart.assert_called_once()
    assert calls["count"] == 2
