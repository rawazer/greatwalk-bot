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
    bootstrap_great_walk_ui,
    collect_navigation_state,
    commit_track_selection,
    navigate_to_site,
    open_great_walk_view,
    wait_for_great_walk_ui,
)
from greatwalkbot.sources.spa_timing import (
    DEFAULT_SHELL_NAVIGATION_TIMEOUT_MS,
    GOTO_WAIT_UNTIL,
    MAX_FETCH_ATTEMPTS_PER_TRACK,
)

MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)


class FakeSpaPage:
    def __init__(
        self,
        *,
        goto_raises: bool = False,
        on_doc_host: bool = True,
        spa_ready: bool = True,
        ready_state: str = "interactive",
    ) -> None:
        self.goto_calls: list[dict] = []
        self.evaluate_calls: list[tuple[str, object | None]] = []
        self.wait_for_function_calls: list[int] = []
        self.wait_for_timeout_calls: list[int] = []
        self._click_option_results: list[str | None] = []
        self._selection_committed = False
        self.url = (
            "https://bookings.doc.govt.nz/Web/Default.aspx"
            if on_doc_host
            else "https://example.com/timeout"
        )
        self._goto_raises = goto_raises
        self._spa_ready = spa_ready
        self._ready_state = ready_state
        self._visible_roots = 1 if spa_ready else 0
        self._visible_dropdowns = 1 if spa_ready else 0
        self._gwbot_console_messages: list[str] = []
        self._gwbot_page_errors: list[str] = []

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        self.goto_calls.append(
            {"url": url, "wait_until": wait_until, "timeout": timeout}
        )
        if self._goto_raises:
            raise TimeoutError(f"Timeout {timeout}ms exceeded.")

    def evaluate(self, expression: str, arg: object | None = None) -> object:
        self.evaluate_calls.append((expression, arg))
        if "ready_state" in expression:
            return {
                "ready_state": self._ready_state,
                "visible_desktop_search_root_count": self._visible_roots,
                "visible_great_walk_dropdown_count": self._visible_dropdowns,
            }
        if isinstance(arg, dict) and "trackName" in arg:
            return self._selection_committed
        if isinstance(arg, dict) and "optionId" in arg:
            if self._click_option_results:
                return self._click_option_results.pop(0)
            return arg["optionId"]
        if isinstance(arg, dict) and "optionIds" in arg:
            if self._click_option_results:
                return self._click_option_results.pop(0)
            return None
        if "dropdown" in expression and "click" in expression:
            return True
        return True

    def wait_for_function(self, expression: str, *, timeout: int) -> bool:
        self.wait_for_function_calls.append(timeout)
        if not self._spa_ready:
            raise TimeoutError("Great Walk UI not ready")
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
    assert page.goto_calls[0]["wait_until"] == "commit"
    assert page.goto_calls[0]["wait_until"] != "networkidle"


def test_bootstrap_goto_succeeds_and_spa_readiness_succeeds():
    page = FakeSpaPage()
    timing = bootstrap_great_walk_ui(
        page,
        shell_timeout_ms=5_000,
        spa_ready_timeout_ms=10_000,
    )
    assert page.goto_calls[0]["wait_until"] == "commit"
    assert any("location.hash" in expr for expr, _ in page.evaluate_calls)
    assert page.wait_for_function_calls == [10_000]
    assert timing.shell_navigation_seconds >= 0
    assert timing.spa_readiness_seconds >= 0
    assert timing.total_seconds >= timing.shell_navigation_seconds


def test_bootstrap_recovers_when_goto_times_out_on_doc_host():
    page = FakeSpaPage(goto_raises=True, on_doc_host=True, spa_ready=True)
    timing = bootstrap_great_walk_ui(
        page,
        shell_timeout_ms=30_000,
        spa_ready_timeout_ms=15_000,
    )
    assert timing.navigation_recovered_after_timeout is True
    assert timing.to_dict()["navigation_recovered_after_timeout"] is True
    assert page.wait_for_function_calls == [15_000]
    assert len(page.goto_calls) == 1


def test_bootstrap_goto_timeout_off_host_raises_navigation_error_with_state():
    page = FakeSpaPage(goto_raises=True, on_doc_host=False)
    with pytest.raises(NavigationError, match="timed out or failed") as exc_info:
        bootstrap_great_walk_ui(
            page,
            shell_timeout_ms=30_000,
            spa_ready_timeout_ms=15_000,
        )
    err = exc_info.value
    assert err.stage == "shell_navigation"
    assert err.timeout_ms == 30_000
    assert err.wait_until == "commit"
    assert err.navigation_state is not None
    assert err.navigation_state.get("on_doc_booking_host") is False
    assert err.timing is not None
    assert "shell_navigation_seconds" in err.timing


def test_bootstrap_goto_timeout_on_host_but_ui_never_ready():
    page = FakeSpaPage(goto_raises=True, on_doc_host=True, spa_ready=False)
    with pytest.raises(NavigationError, match="UI did not become ready") as exc_info:
        bootstrap_great_walk_ui(
            page,
            shell_timeout_ms=30_000,
            spa_ready_timeout_ms=15_000,
        )
    err = exc_info.value
    assert err.stage == "spa_readiness_after_shell_timeout"
    assert err.timeout_ms == 15_000
    assert err.navigation_recovered_after_timeout is False


def test_stage_timing_fields_are_monotonic():
    page = FakeSpaPage()
    timing = bootstrap_great_walk_ui(
        page,
        shell_timeout_ms=5_000,
        spa_ready_timeout_ms=5_000,
        browser_start_seconds=0.5,
    )
    payload = timing.to_dict()
    assert payload["browser_start_seconds"] == 0.5
    assert payload["total_seconds"] >= (
        payload["shell_navigation_seconds"]
        + payload["route_navigation_seconds"]
        + payload["spa_readiness_seconds"]
    )


def test_recovery_is_bounded_to_one_goto_attempt():
    page = FakeSpaPage(goto_raises=True, on_doc_host=True, spa_ready=True)
    bootstrap_great_walk_ui(page, shell_timeout_ms=5_000, spa_ready_timeout_ms=5_000)
    assert len(page.goto_calls) == 1


def test_collect_navigation_state_includes_host_and_counts():
    page = FakeSpaPage()
    state = collect_navigation_state(page)
    assert state["on_doc_booking_host"] is True
    assert state["visible_desktop_search_root_count"] == 1
    assert state["ready_state"] == "interactive"


def test_default_shell_navigation_timeout_is_suitable_for_slow_vm():
    assert DEFAULT_SHELL_NAVIGATION_TIMEOUT_MS >= 45_000


def test_wait_for_great_walk_ui_succeeds():
    page = FakeSpaPage()
    wait_for_great_walk_ui(page, timeout_ms=10_000)
    assert page.wait_for_function_calls == [10_000]


def test_missing_selector_triggers_one_recovery_attempt():
    page = MagicMock()
    recorder = NetworkRecorder()
    open_calls: list[int] = []

    with patch(
        "greatwalkbot.sources.track_transition.transition_track_selection",
        side_effect=TrackSelectorError("missing option", track_slug="milford"),
    ):
        with pytest.raises(TrackSelectorError):
            commit_track_selection(
                page,
                MILFORD,
                recorder,
                navigation_timeout_ms=30_000,
                app_ready_timeout_ms=15_000,
                selection_commit_timeout_ms=50,
            )


def test_missing_selector_after_recovery_raises_track_selector_error():
    page = MagicMock()
    recorder = NetworkRecorder()

    with patch(
        "greatwalkbot.sources.track_transition.transition_track_selection",
        side_effect=TrackSelectorError("missing option", track_slug="milford"),
    ):
        with pytest.raises(TrackSelectorError, match="missing option"):
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
    page = MagicMock()
    recorder = NetworkRecorder()

    with patch(
        "greatwalkbot.sources.track_transition.transition_track_selection",
        side_effect=TrackSelectionNotCommittedError(
            "Track 'Milford Track' transition did not commit",
            place_id=MILFORD.place_id,
            failure_stage="wait_for_commit",
        ),
    ):
        with pytest.raises(TrackSelectionNotCommittedError, match="did not commit"):
            commit_track_selection(
                page,
                MILFORD,
                recorder,
                navigation_timeout_ms=30_000,
                app_ready_timeout_ms=15_000,
                selection_commit_timeout_ms=50,
            )
