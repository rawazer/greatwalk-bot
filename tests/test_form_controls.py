"""Tests for Great Walk form control binding (Milestone 9.4)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from greatwalkbot.debug_search import run_debug_search
from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.plan import TripPlan
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.domain.trip import Trip
from greatwalkbot.infra.errors import SearchFormValidationError
from greatwalkbot.itinerary_form import resolve_form_nights
from greatwalkbot.models import Track
from greatwalkbot.sources.gw_form_controls import (
    capture_form_control_state,
    capture_selection_state,
    normalize_date_string,
)
from greatwalkbot.sources.search_form import prepare_search_form

KEPLER = Track("kepler", "Kepler Track", 872, 2, fixed_nights=3)
ROUTEBURN = Track("routeburn", "Routeburn Track", 874, 7, fixed_nights=2)
MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)


class FakeLocator:
    def __init__(self, page: "FakeFormPage", selector: str) -> None:
        self._page = page
        self._selector = selector

    @property
    def first(self) -> "FakeLocator":
        return self

    def count(self) -> int:
        if "great-walk-start-date" in self._selector:
            return 1
        if "great-walk-nights" in self._selector:
            return 1
        if "data-date" in self._selector:
            return 1 if self._page._calendar_has_date else 0
        if "hidden" in self._selector:
            return 0
        return 0

    def click(self) -> None:
        self._page._events.append(("click", self._selector))

    def fill(self, value: str) -> None:
        self._page._events.append(("fill", self._selector, value))
        if "date" in self._selector:
            self._page._start_date_value = value

    def select_option(self, *, value: str) -> None:
        self._page._events.append(("select_option", self._selector, value))
        self._page._nights_value = value

    def dispatch_event(self, event: str) -> None:
        self._page._events.append(("dispatch_event", self._selector, event))


class FakeFormPage:
    def __init__(
        self,
        *,
        start_date_value: str = "2026-12-03",
        nights_value: str = "2",
        track_label: str = "Routeburn Track",
        calendar_has_date: bool = True,
    ) -> None:
        self._start_date_value = start_date_value
        self._nights_value = nights_value
        self._track_label = track_label
        self._calendar_has_date = calendar_has_date
        self._events: list[tuple] = []
        self._set_calls = 0

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    def evaluate(self, expression: str, arg=None) -> object:
        if "readSelect" in expression or "track_control" in expression:
            return {
                "track_control": {
                    "selector": "#great-walk-dropdown-button",
                    "control_type": "dropdown-button",
                    "raw_value": None,
                    "normalized_value": None,
                    "selected_option_value": None,
                    "selected_option_text": None,
                    "visible_text": self._track_label,
                },
                "start_date_control": {
                    "selector": "#great-walk-start-date",
                    "control_type": "date-button",
                    "raw_value": self._start_date_value,
                    "normalized_value": normalize_date_string(self._start_date_value),
                    "selected_option_value": None,
                    "selected_option_text": None,
                    "visible_text": "03/12/2026",
                },
                "nights_control": {
                    "selector": "#great-walk-nights",
                    "control_type": "select",
                    "raw_value": self._nights_value,
                    "normalized_value": self._nights_value,
                    "selected_option_value": self._nights_value,
                    "selected_option_text": f"{self._nights_value} nights",
                    "visible_text": None,
                },
                "search_button_selector": "#great-walk-search-button",
                "search_button_text": "Search",
                "search_button_enabled": True,
                "search_button_visible": True,
                "validation_messages": [],
                "loading_overlay_present": False,
                "requested": arg,
            }
        if "setAttribute" in expression or "hidden.value" in expression:
            self._set_calls += 1
            if arg and "iso" in arg:
                self._start_date_value = arg["iso"]
            return True
        if "great-walk-search-button" in expression or (
            "Search" in expression and "getElementById" in expression
        ):
            return True
        return False

    def wait_for_timeout(self, timeout: int) -> None:
        self._events.append(("wait_for_timeout", timeout))


def test_select_reports_value_not_concatenated_option_text():
    page = FakeFormPage(nights_value="3")
    state = capture_form_control_state(page, nights=3)
    nights = state["nights_control"]
    assert nights["raw_value"] == "3"
    assert nights["selected_option_text"] == "3 nights"
    assert nights["raw_value"] != "11234567891011121314"


def test_date_normalized_to_iso():
    assert normalize_date_string("26/06/2026") == "2026-06-26"
    assert normalize_date_string("2026-12-07") == "2026-12-07"


def test_prepare_search_dispatches_input_change_blur_events():
    page = FakeFormPage(start_date_value="2026-12-03", nights_value="2")
    prepare_search_form(
        page,
        ROUTEBURN,
        start_date=date(2026, 12, 3),
        nights=2,
    )
    assert ("select_option", "#great-walk-nights", "2") in page._events
    assert any(
        event[0] == "dispatch_event" and event[2] in ("input", "change", "blur")
        for event in page._events
    )


def test_routeburn_debug_defaults_to_two_nights():
    nights, direction = resolve_form_nights(
        "routeburn",
        complete_itinerary_only=True,
    )
    assert nights == 2
    assert direction == "routeburn-shelter-to-divide"


def test_kepler_debug_defaults_to_three_nights():
    nights, _ = resolve_form_nights("kepler", complete_itinerary_only=True)
    assert nights == 3


def test_selection_state_distinguishes_backend_and_visible_label():
    page = FakeFormPage(track_label="Select Great Walk")
    state = capture_selection_state(
        page,
        ROUTEBURN,
        backend_metadata_confirmed=True,
    )
    assert state["backend_metadata_confirmed"] is True
    assert state["visible_track_label"] == "Select Great Walk"
    assert state["visible_selection_committed"] is False
    assert state["ui_state_inconsistent"] is True


def test_failed_value_reflection_includes_control_diagnostics():
    page = FakeFormPage(start_date_value="2026-06-26", nights_value="20")
    with pytest.raises(SearchFormValidationError, match="Start date not reflected"):
        prepare_search_form(
            page,
            ROUTEBURN,
            start_date=date(2026, 12, 3),
            nights=2,
        )


def test_debug_cli_uses_registry_nights_not_date_range():
    plan = TripPlan(
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

    with patch("greatwalkbot.debug_search.SessionManager") as session_cls:
        session = MagicMock()
        session.is_healthy.return_value = True
        session.network.timeline_dicts.return_value = []
        session.network.post_search_timeline_dicts.return_value = []
        session_cls.return_value = session
        with patch("greatwalkbot.debug_search.commit_track_selection"):
            with patch("greatwalkbot.debug_search.navigate_to_site"):
                with patch("greatwalkbot.debug_search.wait_for_great_walk_ui"):
                    with patch(
                        "greatwalkbot.debug_search.capture_selection_state",
                        return_value={
                            "backend_metadata_confirmed": True,
                            "visible_selection_committed": True,
                        },
                    ):
                        with patch(
                            "greatwalkbot.sources.search_form.capture_search_form_state",
                            return_value={"nights_control": {"raw_value": "2"}},
                        ):
                            with patch.object(
                                session,
                                "capture_availability_after_search",
                                return_value={"GreatWalkFacilityData": []},
                            ) as capture:
                                report = run_debug_search(
                                    plan,
                                    ROUTEBURN,
                                    start_date=date(2026, 12, 3),
                                )

    assert report.nights == 2
    capture.assert_called_once()
    assert capture.call_args.kwargs["nights"] == 2
