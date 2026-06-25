"""Tests for Great Walk form control binding (Milestones 9.4–9.5)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from greatwalkbot.debug_search import run_debug_search
from debug_search_helpers import patch_refresh_desktop_root
from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.plan import TripPlan
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.domain.trip import Trip
from greatwalkbot.infra.errors import SearchFormValidationError
from greatwalkbot.itinerary_form import resolve_form_nights
from greatwalkbot.models import Track
from greatwalkbot.sources.gw_desktop_form import DESKTOP_ROOT_SELECTOR, DesktopRootBinding
from greatwalkbot.sources.gw_form_controls import capture_selection_state, normalize_date_string
from greatwalkbot.sources.search_form import prepare_search_form

KEPLER = Track("kepler", "Kepler Track", 872, 2, fixed_nights=3)
ROUTEBURN = Track("routeburn", "Routeburn Track", 874, 7, fixed_nights=2)

DESKTOP_BINDING = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)


def _desktop_read_state(ready: dict) -> dict:
    return {
        "desktop_root_count": 1,
        "desktop_root": ready.get("desktop_root"),
        "track_control": ready.get("track_control", {}),
        "nights_control": ready.get("nights_control", {}),
        "people_control": ready.get("people_control", {}),
        "start_date_control": ready.get("start_date_control", {}),
        "search_button": {"visible_text": "Search", "enabled": ready.get("search_button_enabled", True)},
        "validation_messages": [],
        "loading_present": False,
    }


def _ready_state(
    *,
    start_date_value: str = "2026-12-03",
    nights_value: str = "2 nights",
    people_value: str = "2 people",
    track_label: str = "Routeburn Track",
    search_enabled: bool = True,
) -> dict:
    return {
        "desktop_root": {"selector": DESKTOP_ROOT_SELECTOR, "count": 1},
        "track_control": {
            "visible_text": track_label,
            "matches_requested": track_label in track_label and "Select" not in track_label,
        },
        "start_date_control": {
            "raw_value": start_date_value,
            "data_date": start_date_value if start_date_value.startswith("2026") else None,
            "normalized_value": normalize_date_string(start_date_value),
            "matches_requested": start_date_value.startswith("2026-12"),
        },
        "nights_control": {
            "visible_text": nights_value,
            "raw_value": nights_value.split()[0] if nights_value else None,
            "matches_requested": nights_value.startswith("2") or nights_value.startswith("3"),
        },
        "people_control": {
            "visible_text": people_value,
            "matches_requested": people_value.startswith("2"),
        },
        "search_button_visible": True,
        "search_button_enabled": search_enabled,
        "validation_messages": [],
        "loading_present": False,
    }


class FakeLocator:
    def __init__(self, page: "FakeFormPage", selector: str) -> None:
        self._page = page
        self._selector = selector

    @property
    def first(self) -> "FakeLocator":
        return self

    def locator(self, selector: str) -> "FakeLocator":
        return FakeLocator(self._page, f"{self._selector} >> {selector}")

    def count(self) -> int:
        if "data-gwbot-active-root" in self._selector or "night" in self._selector:
            return 1
        if "date" in self._selector:
            return 1
        return 0

    def click(self) -> None:
        self._page._events.append(("click", self._selector))

    def fill(self, value: str) -> None:
        self._page._events.append(("fill", self._selector, value))
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
    ) -> None:
        self._start_date_value = start_date_value
        self._nights_value = nights_value
        self._track_label = track_label
        self._events: list[tuple] = []

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    def evaluate(self, expression: str, arg=None) -> object:
        if "search-button" in expression:
            return True
        return False

    def wait_for_timeout(self, timeout: int) -> None:
        self._events.append(("wait_for_timeout", timeout))


def test_select_reports_value_not_concatenated_option_text():
    state = _ready_state(nights_value="3 nights")
    assert state["nights_control"]["raw_value"] == "3"
    assert state["nights_control"]["raw_value"] != "11234567891011121314"


def test_date_normalized_to_iso():
    assert normalize_date_string("26/06/2026") == "2026-06-26"
    assert normalize_date_string("2026-12-07") == "2026-12-07"


def test_prepare_search_calls_desktop_prepare_with_people_size():
    page = FakeFormPage()
    ready = _ready_state()
    with patch(
        "greatwalkbot.sources.search_form.prepare_desktop_search_form",
        return_value=ready,
    ) as prepare:
        prepare_search_form(
            page,
            ROUTEBURN,
            start_date=date(2026, 12, 3),
            nights=2,
            people_size=2,
        )
    prepare.assert_called_once_with(
        page,
        ROUTEBURN,
        start_date=date(2026, 12, 3),
        nights=2,
        people_size=2,
    )


def test_routeburn_debug_defaults_to_two_nights():
    nights, direction = resolve_form_nights("routeburn", complete_itinerary_only=True)
    assert nights == 2
    assert direction == "routeburn-shelter-to-divide"


def test_kepler_debug_defaults_to_three_nights():
    nights, _ = resolve_form_nights("kepler", complete_itinerary_only=True)
    assert nights == 3


def test_selection_state_distinguishes_backend_and_visible_label():
    page = FakeFormPage(track_label="Select Great Walk")
    with patch(
        "greatwalkbot.sources.gw_desktop_form.resolve_desktop_great_walk_root",
        return_value=DESKTOP_BINDING,
    ):
        with patch(
            "greatwalkbot.sources.gw_desktop_form.read_desktop_form_state",
            return_value=_desktop_read_state(_ready_state(track_label="Select Great Walk")),
        ):
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
    page = FakeFormPage()
    ready = _ready_state(start_date_value="2026-06-26", nights_value="20 nights")
    ready["start_date_control"]["matches_requested"] = False
    with patch(
        "greatwalkbot.sources.search_form.prepare_desktop_search_form",
        side_effect=SearchFormValidationError(
            "Desktop form values not verified",
            form_state=ready,
        ),
    ):
        with pytest.raises(SearchFormValidationError, match="not verified"):
            prepare_search_form(
                page,
                ROUTEBURN,
                start_date=date(2026, 12, 3),
                nights=2,
                people_size=2,
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
        session.network.saw_selection_metadata.return_value = True
        capture = MagicMock(return_value={"GreatWalkFacilityData": []})
        session.capture_availability_after_search = capture
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
                            return_value=DESKTOP_BINDING,
                        ):
                            with patch_refresh_desktop_root(DESKTOP_BINDING):
                                with patch(
                                    "greatwalkbot.debug_search.capture_desktop_selection_state",
                                    return_value={
                                        "backend_metadata_confirmed": True,
                                        "visible_selection_committed": True,
                                    },
                                ):
                                    with patch(
                                        "greatwalkbot.debug_search.capture_search_form_state",
                                        return_value={"nights_control": {"raw_value": "2"}},
                                    ):
                                        with patch(
                                            "greatwalkbot.debug_search.prepare_search_form",
                                            return_value={"nights_control": {"raw_value": "2"}},
                                        ):
                                            report = run_debug_search(
                                                plan,
                                                ROUTEBURN,
                                                start_date=date(2026, 12, 3),
                                            )

    assert report.nights == 2
    capture.assert_called_once()
    assert capture.call_args.kwargs["nights"] == 2
