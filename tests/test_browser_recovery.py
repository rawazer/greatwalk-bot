"""Tests for browser recovery in PlaywrightAvailabilitySource."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from greatwalkbot.infra.errors import FetchError
from greatwalkbot.models import AvailabilitySnapshot, Track
from greatwalkbot.sources.fetch_timing import TrackFetchTiming
from greatwalkbot.sources.playwright import PlaywrightAvailabilitySource
from greatwalkbot.sources.session_manager import SessionManager
from greatwalkbot.sources.spa_timing import MAX_FETCH_ATTEMPTS_PER_TRACK

MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)
SNAPSHOT = AvailabilitySnapshot(
    track=MILFORD,
    from_date=date(2026, 12, 1),
    to_date=date(2026, 12, 31),
    days=(),
)
TIMING = TrackFetchTiming(
    track_slug="milford",
    navigation_seconds=1.0,
    app_ready_seconds=2.0,
    capture_seconds=3.0,
    total_seconds=6.0,
)


def test_browser_recovery_restarts_session_and_retries_once():
    session = MagicMock(spec=SessionManager)
    session.is_healthy.return_value = True

    source = PlaywrightAvailabilitySource(session_manager=session)

    calls = {"count": 0}

    def fetch_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise FetchError("session broken")
        return SNAPSHOT, TIMING

    with patch.object(source, "_fetch_once", side_effect=fetch_once):
        with patch(
            "greatwalkbot.sources.playwright.save_session_failure_diagnostics"
        ) as save_diag:
            result = source.fetch_track_availability(
                MILFORD,
                date(2026, 12, 1),
                date(2026, 12, 31),
            )

    assert result is SNAPSHOT
    session.restart.assert_called_once()
    assert calls["count"] == MAX_FETCH_ATTEMPTS_PER_TRACK
    save_diag.assert_called_once()
