"""Regression tests for shared-session track transitions (Milestone 12)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.plan import TripPlan
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.domain.trip import Trip
from greatwalkbot.infra.errors import (
    AvailabilityRequestFailedError,
    TrackSelectionNotCommittedError,
    TrackSelectorError,
)
from greatwalkbot.models import AvailabilitySnapshot, Track
from greatwalkbot.sources.fetch_timing import TrackFetchTiming
from greatwalkbot.sources.gw_desktop_form import DESKTOP_ROOT_SELECTOR, DesktopRootBinding
from greatwalkbot.sources.network_recorder import NetworkRecorder
from greatwalkbot.sources.playwright import PlaywrightAvailabilitySource
from greatwalkbot.sources.session_manager import SessionManager
from greatwalkbot.sources.spa_navigation import (
    commit_track_selection,
    ensure_great_walk_session_ready,
)
from greatwalkbot.sources.track_transition import (
    TrackTransitionDiagnostics,
    TrackTransitionLifecycle,
    transition_track_selection,
)

MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)
ROUTEBURN = Track("routeburn", "Routeburn Track", 874, 7, fixed_nights=2)
KEPLER = Track("kepler", "Kepler Track", 872, 2, fixed_nights=3)
BINDING = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)


def _track_state(track_name: str, *, matches: bool) -> dict:
    return {
        "desktop_root_count": 1,
        "desktop_root": {"selector": DESKTOP_ROOT_SELECTOR, "id": "gw-root", "class": "themeTopsearch"},
        "track_control": {
            "visible_text": track_name,
            "aria_expanded": "false",
            "enabled": True,
            "matches_requested": matches,
        },
        "loading_present": False,
        "search_button": {"visible_text": "Search", "enabled": True},
        "validation_messages": [],
    }


def _diagnostics(outcome: str) -> TrackTransitionDiagnostics:
    lifecycle = TrackTransitionLifecycle(
        requested_track_slug="milford",
        requested_track_name="Milford Track",
        outcome=outcome,  # type: ignore[arg-type]
        visible_trigger_matches=True,
    )
    return TrackTransitionDiagnostics(lifecycle=lifecycle)


def test_routeburn_to_milford_shared_session_transition():
    page = MagicMock()
    recorder = NetworkRecorder()
    states = [
        _track_state("Routeburn Track", matches=False),
        _track_state("Milford Track", matches=True),
    ]

    with patch(
        "greatwalkbot.sources.track_transition.resolve_desktop_great_walk_root",
        return_value=BINDING,
    ), patch(
        "greatwalkbot.sources.track_transition.read_desktop_form_state",
        side_effect=states,
    ), patch(
        "greatwalkbot.sources.track_transition.refresh_desktop_root_binding",
        return_value=(BINDING, {"root_replaced": False}),
    ), patch(
        "greatwalkbot.sources.track_transition.select_desktop_track",
    ) as select_track, patch(
        "greatwalkbot.sources.track_transition._track_option_metadata",
        return_value={"found": True, "option_id": "great-walk-5"},
    ), patch(
        "greatwalkbot.sources.track_transition._dropdown_open_state",
        return_value={"open": False},
    ), patch(
        "greatwalkbot.sources.track_transition.wait_for_inter_track_quiescence",
        return_value={"settled": True},
    ), patch(
        "greatwalkbot.sources.track_transition.wait_for_track_transition_committed",
        return_value=(True, True, True),
    ):
        result = transition_track_selection(
            page,
            MILFORD,
            recorder,
            navigation_timeout_ms=30_000,
            app_ready_timeout_ms=15_000,
            selection_commit_timeout_ms=8_000,
            prior_track_slug="routeburn",
        )

    select_track.assert_called_once()
    assert result.lifecycle.outcome == "changed_and_verified"


def test_routeburn_to_kepler_shared_session_transition():
    page = MagicMock()
    recorder = NetworkRecorder()

    with patch(
        "greatwalkbot.sources.track_transition.resolve_desktop_great_walk_root",
        return_value=BINDING,
    ), patch(
        "greatwalkbot.sources.track_transition.read_desktop_form_state",
        side_effect=[
            _track_state("Routeburn Track", matches=False),
            _track_state("Kepler Track", matches=True),
        ],
    ), patch(
        "greatwalkbot.sources.track_transition.refresh_desktop_root_binding",
        return_value=(BINDING, {"root_replaced": False}),
    ), patch(
        "greatwalkbot.sources.track_transition.select_desktop_track",
    ) as select_track, patch(
        "greatwalkbot.sources.track_transition._track_option_metadata",
        return_value={"found": True, "option_id": "great-walk-3"},
    ), patch(
        "greatwalkbot.sources.track_transition._dropdown_open_state",
        return_value={"open": False},
    ), patch(
        "greatwalkbot.sources.track_transition.wait_for_inter_track_quiescence",
        return_value={"settled": True},
    ), patch(
        "greatwalkbot.sources.track_transition.wait_for_track_transition_committed",
        return_value=(True, True, True),
    ):
        result = transition_track_selection(
            page,
            KEPLER,
            recorder,
            navigation_timeout_ms=30_000,
            app_ready_timeout_ms=15_000,
            selection_commit_timeout_ms=8_000,
            prior_track_slug="routeburn",
        )

    select_track.assert_called_once()
    assert result.lifecycle.outcome == "changed_and_verified"


def test_already_matched_skips_dropdown_interaction():
    page = MagicMock()
    recorder = NetworkRecorder()

    with patch(
        "greatwalkbot.sources.track_transition.resolve_desktop_great_walk_root",
        return_value=BINDING,
    ), patch(
        "greatwalkbot.sources.track_transition.read_desktop_form_state",
        return_value=_track_state("Milford Track", matches=True),
    ), patch(
        "greatwalkbot.sources.track_transition.select_desktop_track",
    ) as select_track:
        result = transition_track_selection(
            page,
            MILFORD,
            recorder,
            navigation_timeout_ms=30_000,
            app_ready_timeout_ms=15_000,
            selection_commit_timeout_ms=8_000,
        )

    select_track.assert_not_called()
    assert result.lifecycle.outcome == "already_matched"


def test_root_replaced_after_selection_re_resolves_binding():
    page = MagicMock()
    recorder = NetworkRecorder()
    refresh_calls: list[dict] = []

    def _refresh(_page, _binding):
        refresh_calls.append({"root_replaced": len(refresh_calls) > 0})
        return BINDING, {"root_replaced": len(refresh_calls) > 1}

    with patch(
        "greatwalkbot.sources.track_transition.resolve_desktop_great_walk_root",
        return_value=BINDING,
    ), patch(
        "greatwalkbot.sources.track_transition.read_desktop_form_state",
        side_effect=[
            _track_state("Routeburn Track", matches=False),
            _track_state("Milford Track", matches=True),
        ],
    ), patch(
        "greatwalkbot.sources.track_transition.refresh_desktop_root_binding",
        side_effect=_refresh,
    ), patch(
        "greatwalkbot.sources.track_transition.select_desktop_track",
    ), patch(
        "greatwalkbot.sources.track_transition._track_option_metadata",
        return_value={"found": True, "option_id": "great-walk-5"},
    ), patch(
        "greatwalkbot.sources.track_transition._dropdown_open_state",
        return_value={"open": False},
    ), patch(
        "greatwalkbot.sources.track_transition.wait_for_inter_track_quiescence",
        return_value={"settled": True},
    ), patch(
        "greatwalkbot.sources.track_transition.wait_for_track_transition_committed",
        return_value=(True, True, True),
    ):
        result = transition_track_selection(
            page,
            MILFORD,
            recorder,
            navigation_timeout_ms=30_000,
            app_ready_timeout_ms=15_000,
            selection_commit_timeout_ms=8_000,
            prior_track_slug="routeburn",
        )

    assert result.lifecycle.root_re_resolved is True
    assert len(refresh_calls) >= 1


def test_stale_visible_trigger_after_metadata_raises_typed_error():
    page = MagicMock()
    recorder = NetworkRecorder()
    recorder.begin_cycle(place_id=MILFORD.place_id)
    recorder._append(
        phase="response",
        method="GET",
        path="search/getgreatwalksearchdata/placeId/{id}",
        status=200,
        content_type="application/json",
        selection_metadata_match=True,
    )

    with patch(
        "greatwalkbot.sources.track_transition.resolve_desktop_great_walk_root",
        return_value=BINDING,
    ), patch(
        "greatwalkbot.sources.track_transition.read_desktop_form_state",
        return_value=_track_state("Routeburn Track", matches=False),
    ), patch(
        "greatwalkbot.sources.track_transition.refresh_desktop_root_binding",
        return_value=(BINDING, {"root_replaced": False}),
    ), patch(
        "greatwalkbot.sources.track_transition.select_desktop_track",
    ), patch(
        "greatwalkbot.sources.track_transition._track_option_metadata",
        return_value={"found": True, "option_id": "great-walk-5"},
    ), patch(
        "greatwalkbot.sources.track_transition._dropdown_open_state",
        return_value={"open": False},
    ), patch(
        "greatwalkbot.sources.track_transition.wait_for_inter_track_quiescence",
        return_value={"settled": True},
    ), patch(
        "greatwalkbot.sources.track_transition.wait_for_track_transition_committed",
        return_value=(False, True, False),
    ), patch(
        "greatwalkbot.sources.track_transition.open_great_walk_view",
    ):
        with pytest.raises(TrackSelectionNotCommittedError) as exc_info:
            transition_track_selection(
                page,
                MILFORD,
                recorder,
                navigation_timeout_ms=30_000,
                app_ready_timeout_ms=15_000,
                selection_commit_timeout_ms=50,
                prior_track_slug="routeburn",
            )

    err = exc_info.value
    assert err.transition_diagnostics is not None
    assert err.failure_stage is not None
    assert err.prior_track_slug == "routeburn"


def test_playwright_restarts_once_after_transition_failure():
    session = MagicMock(spec=SessionManager)
    session.is_healthy.return_value = True
    session.network = NetworkRecorder()
    session.needs_full_great_walk_bootstrap = False
    session.last_track_slug = "routeburn"

    source = PlaywrightAvailabilitySource(session_manager=session, people_size=2)
    ok_snapshot = AvailabilitySnapshot(
        track=MILFORD,
        from_date=date(2026, 12, 3),
        to_date=date(2026, 12, 6),
        days=(),
    )
    timing = TrackFetchTiming(
        track_slug="milford",
        navigation_seconds=0.0,
        app_ready_seconds=0.0,
        capture_seconds=0.0,
        total_seconds=0.0,
    )
    source._fetch_once = MagicMock(
        side_effect=[
            TrackSelectionNotCommittedError(
                "stale trigger",
                transition_diagnostics={"transition_lifecycle": {"attempt": 1}},
            ),
            (ok_snapshot, timing),
        ]
    )

    with patch("greatwalkbot.sources.playwright.save_session_failure_diagnostics"):
        snapshot = source.fetch_track_availability(
            MILFORD,
            date(2026, 12, 3),
            date(2026, 12, 6),
        )

    assert snapshot is ok_snapshot
    session.restart.assert_called_once()


def test_ensure_great_walk_session_ready_skips_full_goto_when_bootstrapped():
    page = MagicMock()
    page.url = "https://bookings.doc.govt.nz/Web/Default.aspx#!greatwalk-result"
    page.evaluate.return_value = True
    goto = page.goto

    timing = ensure_great_walk_session_ready(
        page,
        shell_timeout_ms=30_000,
        spa_ready_timeout_ms=15_000,
        full_bootstrap_required=False,
    )

    goto.assert_not_called()
    assert timing.shell_navigation_seconds == 0.0


def test_commit_track_selection_delegates_to_transition():
    page = MagicMock()
    recorder = NetworkRecorder()
    expected = _diagnostics("already_matched").to_dict()

    with patch(
        "greatwalkbot.sources.track_transition.transition_track_selection",
        return_value=_diagnostics("already_matched"),
    ) as transition:
        result = commit_track_selection(
            page,
            MILFORD,
            recorder,
            navigation_timeout_ms=30_000,
            app_ready_timeout_ms=15_000,
            selection_commit_timeout_ms=8_000,
            prior_track_slug="routeburn",
        )

    transition.assert_called_once()
    assert result == expected


def test_missing_option_after_recovery_raises_track_selector_error():
    page = MagicMock()
    recorder = NetworkRecorder()

    with patch(
        "greatwalkbot.sources.track_transition.resolve_desktop_great_walk_root",
        return_value=BINDING,
    ), patch(
        "greatwalkbot.sources.track_transition.read_desktop_form_state",
        return_value=_track_state("Routeburn Track", matches=False),
    ), patch(
        "greatwalkbot.sources.track_transition._track_option_metadata",
        return_value={"found": False},
    ), patch(
        "greatwalkbot.sources.track_transition.open_great_walk_view",
    ):
        with pytest.raises(TrackSelectorError):
            transition_track_selection(
                page,
                MILFORD,
                recorder,
                navigation_timeout_ms=30_000,
                app_ready_timeout_ms=15_000,
                selection_commit_timeout_ms=50,
            )
