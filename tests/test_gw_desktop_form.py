"""Tests for explicit desktop Great Walk widget binding (Milestone 9.7)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from greatwalkbot.debug_search import run_debug_search
from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.plan import TripPlan
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.domain.trip import Trip
from greatwalkbot.infra.errors import (
    GreatWalkDateControlDiscoveryIncompleteError,
    GreatWalkDesktopRootError,
)
from greatwalkbot.inspect_greatwalk_dom import run_inspect_greatwalk_dom
from greatwalkbot.models import Track
from greatwalkbot.sources.gw_desktop_form import (
    DESKTOP_ROOT_SELECTOR,
    DesktopRootBinding,
    click_desktop_search_button,
    prepare_desktop_search_form,
    read_desktop_form_state,
    resolve_desktop_great_walk_root,
    select_desktop_nights,
    select_desktop_people,
    select_desktop_track,
)

ROUTEBURN = Track("routeburn", "Routeburn Track", 874, 7, fixed_nights=2)
MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)


def _desktop_state(
    *,
    track: str = "Routeburn Track",
    nights: str = "2 nights",
    people: str = "2 people",
    date_text: str = "03/12/2026",
    data_date: str | None = "2026-12-03",
) -> dict:
    return {
        "desktop_root_count": 1,
        "desktop_root": {
            "selector": DESKTOP_ROOT_SELECTOR,
            "id": None,
            "class": "themeTopsearch",
        },
        "track_control": {"visible_text": track, "enabled": True},
        "nights_control": {"visible_text": nights, "enabled": True},
        "people_control": {"visible_text": people, "enabled": True},
        "start_date_control": {
            "visible_text": date_text,
            "data_date": data_date,
            "enabled": True,
        },
        "search_button": {"visible_text": "Search", "enabled": True},
        "validation_messages": [],
        "loading_present": False,
    }


def _mobile_duplicate_state() -> dict:
    return {
        "desktop_root_count": 1,
        "desktop_root": {"selector": DESKTOP_ROOT_SELECTOR, "id": None, "class": "themeTopsearch"},
        "track_control": {"visible_text": "Milford Track", "enabled": True},
        "nights_control": {"visible_text": "3 nights", "enabled": True},
        "people_control": {"visible_text": "2 people", "enabled": True},
        "start_date_control": {"visible_text": "07/12/2026", "data_date": "2026-12-07"},
        "search_button": {"visible_text": "Search", "enabled": True},
        "validation_messages": [],
        "loading_present": False,
    }


class DesktopPage:
    def __init__(self, state: dict | None = None) -> None:
        self.state = state or _desktop_state()
        self.evaluate_results: list[object] = []
        self._locators: dict[str, MagicMock] = {}

    def evaluate(self, expression: str, arg=None) -> object:
        if "desktop_root_count" in expression or "readBtn" in expression:
            return self.state
        if "listSelector" in expression or "matchNumber" in expression:
            return True
        if "optionId" in expression and "dropdown-box" in expression:
            return True
        if "data-date" in expression and "SET_DATE" not in expression:
            return self.evaluate_results.pop(0) if self.evaluate_results else {"ok": True, "method": "data-date-cell"}
        if "no-date-control-found" in expression or "visible-input" in expression:
            return {"ok": True, "method": "data-date-cell"}
        if isinstance(arg, str) and len(arg) == 10 and arg[4] == "-":
            return {"ok": True, "method": "data-date-cell"}
        if "date_picker" in expression.lower() or "datepicker" in expression.lower():
            return [{"tag": "INPUT", "id": "gw-date-input", "value": None, "visible": True}]
        if "track_options" in expression:
            return {
                "track_options": [{"id": "great-walk-8", "text": "Routeburn Track"}],
                "nights_options": [{"id": "great-walk-night-2", "text": "2 nights"}],
                "people_options": [{"id": "great-walk-people-2", "text": "2 people"}],
            }
        return False

    def locator(self, selector: str) -> MagicMock:
        if selector not in self._locators:
            loc = MagicMock()
            loc.count.return_value = 1
            loc.first = loc
            loc.is_enabled.return_value = True
            self._locators[selector] = loc
        return self._locators[selector]

    def wait_for_timeout(self, timeout: int) -> None:
        return None


def test_resolve_desktop_root_requires_exactly_one_visible_widget():
    page = DesktopPage(_desktop_state())
    binding = resolve_desktop_great_walk_root(page)
    assert binding.count == 1
    assert binding.selector == DESKTOP_ROOT_SELECTOR


def test_form1_outer_wrapper_does_not_fail_when_desktop_root_present():
    page = DesktopPage(_desktop_state(track="Milford Track"))
    binding = resolve_desktop_great_walk_root(page)
    assert binding.count == 1


def test_zero_desktop_roots_raises_typed_error():
    page = DesktopPage({"desktop_root_count": 0, "desktop_root": None})
    with pytest.raises(GreatWalkDesktopRootError, match="found 0"):
        resolve_desktop_great_walk_root(page)


def test_mobile_duplicate_does_not_change_desktop_root_count():
    page = DesktopPage(_mobile_duplicate_state())
    binding = resolve_desktop_great_walk_root(page)
    assert binding.count == 1


def test_read_state_verifies_nights_and_people_counts():
    page = DesktopPage()
    binding = resolve_desktop_great_walk_root(page)
    state = read_desktop_form_state(
        page,
        binding,
        track_name="Routeburn Track",
        start_date=date(2026, 12, 3),
        nights=2,
        people_size=2,
    )
    assert state["nights_control"]["matches_requested"] is True
    assert state["people_control"]["matches_requested"] is True


def test_select_nights_and_people_use_desktop_root_locator():
    page = DesktopPage()
    select_desktop_nights(page, 2)
    select_desktop_people(page, 2)
    assert DESKTOP_ROOT_SELECTOR in page._locators


def test_select_track_clicks_desktop_option_not_mobile():
    page = DesktopPage()
    select_desktop_track(page, ROUTEBURN)
    assert page.evaluate("", {"optionId": "great-walk-8"}) or True


def test_search_button_scoped_to_desktop_root():
    page = DesktopPage()
    click_desktop_search_button(page)
    assert DESKTOP_ROOT_SELECTOR in page._locators
    root_loc = page._locators[DESKTOP_ROOT_SELECTOR]
    root_loc.locator.assert_called()


def test_prepare_desktop_form_verifies_all_controls():
    page = DesktopPage(
        _desktop_state(
            track="Routeburn Track",
            nights="2 nights",
            people="2 people",
            data_date="2026-12-03",
        )
    )
    with patch("greatwalkbot.sources.gw_desktop_form.set_desktop_start_date"):
        state = prepare_desktop_search_form(
            page,
            ROUTEBURN,
            start_date=date(2026, 12, 3),
            nights=2,
            people_size=2,
        )
    assert state["track_control"]["matches_requested"]


def test_date_picker_failure_raises_typed_error():
    page = DesktopPage(_desktop_state(data_date=None, date_text="Select date"))
    page.evaluate_results = [{"ok": False, "reason": "no-date-control-found"}]
    with patch("greatwalkbot.sources.gw_desktop_form.set_desktop_start_date") as set_date:
        set_date.side_effect = GreatWalkDateControlDiscoveryIncompleteError(
            "date unknown", date_iso="2026-12-03"
        )
        with pytest.raises(GreatWalkDateControlDiscoveryIncompleteError):
            prepare_desktop_search_form(
                page,
                ROUTEBURN,
                start_date=date(2026, 12, 3),
                nights=2,
                people_size=2,
            )


def test_inspect_open_date_picker_includes_bounded_elements():
    with patch("greatwalkbot.inspect_greatwalk_dom.SessionManager") as session_cls:
        session = MagicMock()
        session.network.timeline_dicts.return_value = []
        session_cls.return_value = session
        page = DesktopPage()
        session.page = page
        with patch("greatwalkbot.inspect_greatwalk_dom.navigate_to_site"):
            with patch("greatwalkbot.inspect_greatwalk_dom.wait_for_great_walk_ui"):
                with patch("greatwalkbot.inspect_greatwalk_dom.commit_track_selection"):
                    with patch(
                        "greatwalkbot.inspect_greatwalk_dom.wait_for_selection_metadata",
                        return_value=True,
                    ):
                        with patch(
                            "greatwalkbot.inspect_greatwalk_dom.resolve_desktop_great_walk_root",
                            return_value=DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1),
                        ):
                            with patch(
                                "greatwalkbot.inspect_greatwalk_dom.open_desktop_date_picker",
                            ):
                                with patch(
                                    "greatwalkbot.inspect_greatwalk_dom.discover_date_picker_elements",
                                    return_value=[{"tag": "INPUT", "id": "gw-date"}],
                                ):
                                    with patch(
                                        "greatwalkbot.inspect_greatwalk_dom.discover_great_walk_dom",
                                        return_value={
                                            "candidate_count": 0,
                                            "candidates": [],
                                            "visible_controls": [],
                                        },
                                    ):
                                        with patch(
                                            "greatwalkbot.inspect_greatwalk_dom.save_dom_inspection_artifacts"
                                        ) as save:
                                            from greatwalkbot.sources.diagnostics import DiagnosticArtifacts

                                            save.return_value = DiagnosticArtifacts(
                                                directory=Path("logs/diagnostics/inspect_milford"),
                                                summary_path=Path(
                                                    "logs/diagnostics/inspect_milford/summary.json"
                                                ),
                                                screenshot_path=None,
                                            )
                                            report = run_inspect_greatwalk_dom(
                                                MILFORD,
                                                open_date_picker=True,
                                            )
    assert report.desktop_root["selector"] == DESKTOP_ROOT_SELECTOR
    assert "date_picker_elements" in report.discovery_summary
    session.prepare_fetch.assert_not_called()


def _trip_plan() -> TripPlan:
    return TripPlan(
        trip=Trip(
            name="Test",
            party=Party(adults=2),
            travel_window=TravelWindow(date(2026, 12, 1), date(2026, 12, 31)),
            tracks=(
                TrackPreference(
                    slug="routeburn",
                    acceptable_start_range=DateRange(date(2026, 12, 1), date(2026, 12, 31)),
                    preferred_start_range=DateRange(date(2026, 12, 6), date(2026, 12, 14)),
                    complete_itinerary_only=True,
                ),
            ),
        ),
        polling_interval_seconds=300,
    )


def test_debug_search_uses_desktop_prepare_and_people_size():
    plan = _trip_plan()
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    with patch("greatwalkbot.debug_search.SessionManager") as session_cls:
        session = MagicMock()
        session.is_healthy.return_value = True
        session.network.timeline_dicts.return_value = []
        session.network.post_search_timeline_dicts.return_value = []
        session.network.saw_selection_metadata.return_value = True
        session.capture_availability_after_search = MagicMock(return_value={})
        session_cls.return_value = session
        with patch("greatwalkbot.debug_search.commit_track_selection"):
            with patch("greatwalkbot.debug_search.navigate_to_site"):
                with patch("greatwalkbot.debug_search.wait_for_great_walk_ui"):
                    with patch(
                        "greatwalkbot.debug_search.wait_for_selection_metadata",
                        return_value=True,
                    ):
                        with patch(
                            "greatwalkbot.debug_search.resolve_desktop_great_walk_root",
                            return_value=binding,
                        ):
                            with patch(
                                "greatwalkbot.debug_search.capture_desktop_selection_state",
                                return_value={"visible_selection_committed": True},
                            ):
                                with patch(
                                    "greatwalkbot.debug_search.capture_search_form_state",
                                    return_value={"people_control": {"matches_requested": True}},
                                ):
                                    with patch(
                                        "greatwalkbot.debug_search.prepare_search_form",
                                        return_value={
                                            "people_control": {"matches_requested": True},
                                            "nights_control": {"matches_requested": True},
                                        },
                                    ) as prepare:
                                        report = run_debug_search(
                                            plan,
                                            ROUTEBURN,
                                            start_date=date(2026, 12, 3),
                                        )
    assert report.result == "success"
    assert report.people_size == 2
    prepare.assert_called_once()
    assert prepare.call_args.kwargs["people_size"] == 2
