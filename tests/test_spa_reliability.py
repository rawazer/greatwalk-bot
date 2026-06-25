"""Deterministic tests for DOC SPA navigation reliability."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from greatwalkbot.infra.errors import (
    FetchError,
    NavigationError,
    TrackSelectionNotCommittedError,
    TrackSelectorError,
    UIReadinessError,
)
from greatwalkbot.models import AvailabilitySnapshot, Track
from greatwalkbot.sources.diagnostics import (
    enforce_retention,
    save_session_failure_diagnostics,
)
from greatwalkbot.sources.fetch_timing import TrackFetchTiming
from greatwalkbot.sources.network_recorder import NetworkRecorder
from greatwalkbot.sources.playwright import PlaywrightAvailabilitySource
from greatwalkbot.sources.session_manager import SessionManager
from greatwalkbot.sources.spa_navigation import (
    commit_track_selection,
    navigate_to_site,
    open_great_walk_view,
    wait_for_great_walk_ui,
)
from greatwalkbot.sources.spa_timing import (
    GOTO_WAIT_UNTIL,
    MAX_FETCH_ATTEMPTS_PER_TRACK,
)

MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)


class FakeSpaPage:
    def __init__(self) -> None:
        self.goto_calls: list[dict] = []
        self.evaluate_calls: list[tuple[str, object | None]] = []
        self.wait_for_function_calls: list[int] = []
        self.wait_for_timeout_calls: list[int] = []
        self._click_option_results: list[str | None] = []
        self._selection_committed = False
        self.url = "https://bookings.doc.govt.nz/Web/Default.aspx"
        self._gwbot_console_messages: list[str] = []
        self._gwbot_page_errors: list[str] = []

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        self.goto_calls.append(
            {"url": url, "wait_until": wait_until, "timeout": timeout}
        )

    def evaluate(self, expression: str, arg: object | None = None) -> object:
        self.evaluate_calls.append((expression, arg))
        if isinstance(arg, dict) and "trackName" in arg:
            return self._selection_committed
        if isinstance(arg, dict) and "optionIds" in arg:
            if self._click_option_results:
                return self._click_option_results.pop(0)
            return None
        if "dropdown" in expression and "click" in expression:
            return True
        return True

    def wait_for_function(self, expression: str, *, timeout: int) -> bool:
        self.wait_for_function_calls.append(timeout)
        return True

    def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)

    def title(self) -> str:
        return "Great Walk Bookings"

    def content(self) -> str:
        return "<html><body>great-walk</body></html>"

    def screenshot(self, **kwargs) -> None:
        return None


def test_navigation_does_not_use_networkidle():
    page = FakeSpaPage()
    navigate_to_site(page, timeout_ms=5_000)
    assert page.goto_calls[0]["wait_until"] == GOTO_WAIT_UNTIL
    assert page.goto_calls[0]["wait_until"] != "networkidle"


def test_wait_for_great_walk_ui_succeeds():
    page = FakeSpaPage()
    wait_for_great_walk_ui(page, timeout_ms=10_000)
    assert page.wait_for_function_calls == [10_000]


def test_missing_selector_triggers_one_recovery_attempt():
    page = FakeSpaPage()
    page._click_option_results = [None, "great-walk-5"]
    page._selection_committed = True
    recorder = NetworkRecorder()
    open_calls: list[int] = []

    def track_open(*_args, **kwargs):
        open_calls.append(kwargs.get("navigation_timeout_ms", 0))

    with patch(
        "greatwalkbot.sources.spa_navigation.open_great_walk_view",
        side_effect=track_open,
    ):
        commit_track_selection(
            page,
            MILFORD,
            recorder,
            navigation_timeout_ms=30_000,
            app_ready_timeout_ms=15_000,
            selection_commit_timeout_ms=50,
        )

    assert len(open_calls) == 1


def test_missing_selector_after_recovery_raises_track_selector_error():
    page = FakeSpaPage()
    page._click_option_results = [None, None]
    recorder = NetworkRecorder()

    with patch("greatwalkbot.sources.spa_navigation.open_great_walk_view"):
        with pytest.raises(TrackSelectorError, match="Could not click any track option"):
            commit_track_selection(
                page,
                MILFORD,
                recorder,
                navigation_timeout_ms=30_000,
                app_ready_timeout_ms=15_000,
                selection_commit_timeout_ms=50,
            )


def test_browser_restart_before_retry():
    session = MagicMock(spec=SessionManager)
    session.is_healthy.return_value = True
    session.network = NetworkRecorder()
    source = PlaywrightAvailabilitySource(session_manager=session)
    snapshot = AvailabilitySnapshot(
        track=MILFORD,
        from_date=date(2026, 12, 1),
        to_date=date(2026, 12, 31),
        days=(),
    )
    timing = TrackFetchTiming("milford", 1, 1, 1, 4)

    calls = {"n": 0}

    def fetch_once(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FetchError("no capture")
        return snapshot, timing

    with patch.object(source, "_fetch_once", side_effect=fetch_once):
        with patch("greatwalkbot.sources.playwright.save_session_failure_diagnostics"):
            source.fetch_track_availability(MILFORD, date(2026, 12, 1), date(2026, 12, 31))

    session.restart.assert_called_once()
    assert calls["n"] == MAX_FETCH_ATTEMPTS_PER_TRACK


def test_retry_loop_is_bounded():
    session = MagicMock(spec=SessionManager)
    session.is_healthy.return_value = True
    session.network = NetworkRecorder()
    source = PlaywrightAvailabilitySource(session_manager=session)

    with patch.object(
        source,
        "_fetch_once",
        side_effect=FetchError("always fails"),
    ):
        with patch("greatwalkbot.sources.playwright.save_session_failure_diagnostics"):
            with pytest.raises(FetchError):
                source.fetch_track_availability(
                    MILFORD, date(2026, 12, 1), date(2026, 12, 31)
                )

    assert session.restart.call_count == 1


def test_diagnostics_written_on_failure(tmp_path):
    page = FakeSpaPage()
    artifacts = save_session_failure_diagnostics(
        page=page,
        track_name="Milford Track",
        track_slug="milford",
        error=NavigationError("timeout"),
        diagnostics_dir=tmp_path,
    )
    assert artifacts is not None
    assert artifacts.summary_path.is_file()
    summary = artifacts.summary_path.read_text(encoding="utf-8")
    assert "milford" in summary
    assert "NavigationError" in summary
    assert "cookie" not in summary.lower() or "***" in summary


def test_diagnostics_retention(tmp_path):
    for index in range(5):
        run_dir = tmp_path / f"2026010{index}T120000Z_track"
        run_dir.mkdir()
        (run_dir / "summary.json").write_text("{}", encoding="utf-8")

    enforce_retention(tmp_path, 3)
    remaining = list(tmp_path.iterdir())
    assert len(remaining) == 3


def test_selection_not_committed_raises_typed_error():
    page = FakeSpaPage()
    page._click_option_results = ["great-walk-5", "great-walk-5"]
    page._selection_committed = False
    recorder = NetworkRecorder()

    with patch("greatwalkbot.sources.spa_navigation.open_great_walk_view"):
        with pytest.raises(TrackSelectionNotCommittedError, match="did not commit"):
            commit_track_selection(
                page,
                MILFORD,
                recorder,
                navigation_timeout_ms=30_000,
                app_ready_timeout_ms=15_000,
                selection_commit_timeout_ms=50,
            )
