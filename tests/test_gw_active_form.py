"""Tests for active Great Walk form discovery (Milestone 9.5)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from greatwalkbot.infra.errors import (
    GreatWalkControlNotFoundError,
    GreatWalkFormNotReadyError,
    SearchFormValidationError,
)
from greatwalkbot.models import Track
from greatwalkbot.sources.gw_active_form import (
    ActiveFormResolution,
    capture_selection_state,
    read_active_form_state,
    resolve_active_great_walk_form,
    wait_for_active_form_ready,
)
from greatwalkbot.sources.search_form import prepare_search_form

ROUTEBURN = Track("routeburn", "Routeburn Track", 874, 7, fixed_nights=2)
MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)


def _is_loading_text(text: str) -> bool:
    from greatwalkbot.sources.gw_active_form import LOADING_TEXT_MARKERS

    lowered = text.lower()
    return any(marker in lowered for marker in LOADING_TEXT_MARKERS)


ACTIVE_RESOLUTION = ActiveFormResolution(
    candidate_count=2,
    active_root={
        "index": 1,
        "id": "great-walk-search-panel",
        "selector": "#great-walk-search-panel",
        "controls_found": {
            "track": True,
            "start_date": True,
            "nights": True,
            "search": True,
        },
        "loading_present": False,
    },
    rejected_candidates=[
        {
            "index": 0,
            "id": "great-walk-mobile-panel",
            "rejected_because": "lower score than active root",
        }
    ],
)

READY_STATE = {
    "active_root": {"id": "great-walk-search-panel", "selector": "#great-walk-search-panel"},
    "track_control": {
        "visible_text": "Routeburn Track",
        "matches_requested": True,
    },
    "start_date_control": {
        "raw_value": "2026-12-03",
        "normalized_value": "2026-12-03",
        "matches_requested": True,
    },
    "nights_control": {
        "raw_value": "2",
        "selected_option_value": "2",
        "matches_requested": True,
    },
    "search_button_visible": True,
    "search_button_enabled": True,
    "validation_messages": [],
    "loading_present": False,
}


class ScriptedPage:
    def __init__(self) -> None:
        self.evaluate_results: list[object] = []
        self._locators: dict[str, MagicMock] = {}

    def evaluate(self, expression: str, arg=None) -> object:
        if "candidateRoots" in expression or "RESOLVE" in expression:
            return {
                "candidate_count": 2,
                "active_root": ACTIVE_RESOLUTION.active_root,
                "rejected_candidates": ACTIVE_RESOLUTION.rejected_candidates,
            }
        if "READ_SCOPED" in expression or "readDate" in expression:
            return dict(READY_STATE, requested=arg)
        if "INVENTORY" in expression or "items.push" in expression:
            return [
                {"tag": "SELECT", "id": "great-walk-nights", "value": "2", "visible": True},
                {"tag": "INPUT", "id": "great-walk-start-date-input", "value": "2026-12-03"},
            ]
        return False

    def locator(self, selector: str) -> MagicMock:
        if selector not in self._locators:
            loc = MagicMock()
            loc.count.return_value = 1
            loc.first = loc
            self._locators[selector] = loc
        return self._locators[selector]

    def wait_for_timeout(self, timeout: int) -> None:
        return None


def test_resolve_active_root_reports_rejected_candidates():
    page = ScriptedPage()
    resolution = resolve_active_great_walk_form(page)
    assert resolution.candidate_count == 2
    assert resolution.active_root is not None
    assert len(resolution.rejected_candidates) == 1


def test_fetching_content_is_loading_not_validation():
    assert _is_loading_text("Fetching Content...")
    state = dict(READY_STATE)
    state["validation_messages"] = []
    state["loading_present"] = True
    with pytest.raises(GreatWalkFormNotReadyError):
        from greatwalkbot.sources.search_form import _raise_if_not_actionable

        _raise_if_not_actionable(state, phase="before search")


def test_missing_nights_raises_control_not_found():
    page = ScriptedPage()
    resolution = ActiveFormResolution(
        candidate_count=1,
        active_root={
            "controls_found": {"track": True, "start_date": True, "nights": False, "search": True},
        },
    )
    state = dict(READY_STATE)
    state["nights_control"] = {}
    with pytest.raises(GreatWalkControlNotFoundError, match="Nights control"):
        from greatwalkbot.sources.gw_active_form import _require_controls

        _require_controls(state, resolution)


def test_wait_for_active_form_ready_succeeds():
    page = ScriptedPage()
    resolution, state = wait_for_active_form_ready(page, timeout_ms=500)
    assert resolution.active_root is not None
    assert state["nights_control"]["raw_value"] == "2"


def test_selection_state_uses_same_active_root_and_metadata():
    page = ScriptedPage()
    state = capture_selection_state(
        page,
        ROUTEBURN,
        ACTIVE_RESOLUTION,
        backend_metadata_confirmed=True,
    )
    assert state["backend_metadata_confirmed"] is True
    assert state["active_root"]["id"] == "great-walk-search-panel"
    assert state["visible_track_label"] == "Routeburn Track"


def test_prepare_search_delegates_to_desktop_form():
    page = ScriptedPage()
    with patch(
        "greatwalkbot.sources.search_form.prepare_desktop_search_form",
        return_value=READY_STATE,
    ) as prepare:
        state = prepare_search_form(
            page,
            ROUTEBURN,
            start_date=date(2026, 12, 3),
            nights=2,
            people_size=2,
        )
    prepare.assert_called_once()
    assert state == READY_STATE


def test_desktop_root_loading_raises_form_not_ready():
    page = ScriptedPage()
    with patch(
        "greatwalkbot.sources.search_form.prepare_desktop_search_form",
        side_effect=GreatWalkFormNotReadyError("still loading", form_state=READY_STATE),
    ):
        with pytest.raises(GreatWalkFormNotReadyError):
            prepare_search_form(
                page,
                MILFORD,
                start_date=date(2026, 12, 7),
                nights=3,
                people_size=2,
            )


def test_debug_inventory_bounded():
    page = ScriptedPage()
    from greatwalkbot.sources.gw_active_form import inventory_active_form

    items = inventory_active_form(page)
    assert len(items) <= 40
    assert items[0]["id"] == "great-walk-nights"
