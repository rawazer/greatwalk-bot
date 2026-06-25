"""Tests for idempotent desktop form preparation (Milestone 9.9)."""

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
from greatwalkbot.infra.errors import (
    GreatWalkDateControlDiscoveryIncompleteError,
    SearchFormValidationError,
)
from greatwalkbot.models import Track
from greatwalkbot.sources.gw_desktop_form import (
    DESKTOP_ROOT_SELECTOR,
    DesktopRootBinding,
    prepare_desktop_search_form,
)
from greatwalkbot.sources.network_recorder import NetworkRecorder
from debug_search_helpers import patch_refresh_desktop_root

MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)
ROUTEBURN = Track("routeburn", "Routeburn Track", 874, 7, fixed_nights=2)


def _milford_live_state() -> dict:
    return {
        "desktop_root_count": 1,
        "desktop_root": {
            "selector": DESKTOP_ROOT_SELECTOR,
            "id": None,
            "class": "themeTopsearch selectedPark",
        },
        "track_control": {"visible_text": "Milford Track", "enabled": True},
        "nights_control": {"visible_text": "3", "enabled": True},
        "people_control": {"visible_text": "1", "enabled": True},
        "start_date_control": {
            "visible_text": "26/06/2026",
            "data_date": "2026-06-26",
            "enabled": True,
        },
        "search_button": {"visible_text": "Search", "enabled": True},
        "validation_messages": [],
        "loading_present": False,
    }


class IdempotentDesktopPage:
    def __init__(self, state: dict) -> None:
        self.state = state
        self.evaluate_results: list[object] = []
        self._locators: dict[str, MagicMock] = {}

    def evaluate(self, expression: str, arg=None) -> object:
        if "elementFromPoint" in expression:
            return {"found": True, "clickable": True, "control_selector": (arg or {}).get("targetSelector")}
        if "desktop_root_count" in expression or "readBtn" in expression:
            return self.state
        if "listSelector" in expression or "matchNumber" in expression:
            return True
        if isinstance(arg, str) and len(arg) == 10 and arg[4] == "-":
            return {"ok": True, "method": "data-date-cell"}
        if "no-date-control-found" in expression or "visible-input" in expression:
            return {"ok": True, "method": "data-date-cell"}
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


def test_already_matching_nights_does_not_invoke_nights_interaction():
    page = IdempotentDesktopPage(_milford_live_state())

    def _date(*_args, **_kwargs) -> None:
        page.state["start_date_control"] = {
            "visible_text": "07/12/2026",
            "data_date": "2026-12-07",
            "enabled": True,
        }

    def _people(*_args, **_kwargs) -> None:
        page.state["people_control"] = {"visible_text": "2", "enabled": True}

    with patch("greatwalkbot.sources.gw_desktop_form.select_desktop_nights") as nights:
        with patch("greatwalkbot.sources.gw_desktop_form.click_desktop_control") as click:
            with patch("greatwalkbot.sources.gw_desktop_form.probe_click_readiness") as probe:
                with patch("greatwalkbot.sources.gw_desktop_form.set_desktop_start_date", side_effect=_date):
                    with patch("greatwalkbot.sources.gw_desktop_form.select_desktop_people", side_effect=_people):
                        prepare_desktop_search_form(
                            page,
                            MILFORD,
                            start_date=date(2026, 12, 7),
                            nights=3,
                            people_size=2,
                        )
    nights.assert_not_called()
    probe.assert_not_called()
    nights_click_calls = [
        c for c in click.call_args_list if len(c.args) >= 4 and c.args[3] == "nights"
    ]
    assert nights_click_calls == []


def test_already_matching_track_does_not_reselect():
    page = IdempotentDesktopPage(_milford_live_state())

    def _date(*_args, **_kwargs) -> None:
        page.state["start_date_control"] = {
            "visible_text": "07/12/2026",
            "data_date": "2026-12-07",
            "enabled": True,
        }

    def _people(*_args, **_kwargs) -> None:
        page.state["people_control"] = {"visible_text": "2", "enabled": True}

    with patch("greatwalkbot.sources.gw_desktop_form.select_desktop_track") as track:
        with patch("greatwalkbot.sources.gw_desktop_form.set_desktop_start_date", side_effect=_date):
            with patch("greatwalkbot.sources.gw_desktop_form.select_desktop_people", side_effect=_people):
                state = prepare_desktop_search_form(
                    page,
                    MILFORD,
                    start_date=date(2026, 12, 7),
                    nights=3,
                    people_size=2,
                )
    track.assert_not_called()
    assert state["control_actions"]["track"] == "already_matched"
    assert state["control_actions"]["nights"] == "already_matched"


def test_mismatched_people_and_date_are_still_acted_upon():
    page = IdempotentDesktopPage(_milford_live_state())

    def _date(*_args, **_kwargs) -> None:
        page.state["start_date_control"] = {
            "visible_text": "07/12/2026",
            "data_date": "2026-12-07",
            "enabled": True,
        }

    def _people(*_args, **_kwargs) -> None:
        page.state["people_control"] = {"visible_text": "2", "enabled": True}

    with patch("greatwalkbot.sources.gw_desktop_form.set_desktop_start_date", side_effect=_date) as set_date:
        with patch("greatwalkbot.sources.gw_desktop_form.select_desktop_people", side_effect=_people) as set_people:
            with patch("greatwalkbot.sources.gw_desktop_form.select_desktop_nights") as set_nights:
                prepare_desktop_search_form(
                    page,
                    MILFORD,
                    start_date=date(2026, 12, 7),
                    nights=3,
                    people_size=2,
                )
    set_date.assert_called_once()
    set_people.assert_called_once()
    set_nights.assert_not_called()


def test_interaction_order_track_date_nights_people():
    state = {
        **_milford_live_state(),
        "track_control": {"visible_text": "Routeburn Track", "enabled": True},
        "nights_control": {"visible_text": "2 nights", "enabled": True},
        "people_control": {"visible_text": "1", "enabled": True},
        "start_date_control": {
            "visible_text": "26/06/2026",
            "data_date": "2026-06-26",
            "enabled": True,
        },
    }
    page = IdempotentDesktopPage(state)
    call_order: list[str] = []

    def _track(*_args, **_kwargs) -> None:
        call_order.append("track")
        page.state["track_control"] = {"visible_text": "Milford Track", "enabled": True}

    def _date(*_args, **_kwargs) -> None:
        call_order.append("date")
        page.state["start_date_control"] = {
            "visible_text": "07/12/2026",
            "data_date": "2026-12-07",
            "enabled": True,
        }

    def _nights(*_args, **_kwargs) -> None:
        call_order.append("nights")
        page.state["nights_control"] = {"visible_text": "3", "enabled": True}

    def _people(*_args, **_kwargs) -> None:
        call_order.append("people")
        page.state["people_control"] = {"visible_text": "2", "enabled": True}

    with patch("greatwalkbot.sources.gw_desktop_form.select_desktop_track", side_effect=_track):
        with patch("greatwalkbot.sources.gw_desktop_form.set_desktop_start_date", side_effect=_date):
            with patch("greatwalkbot.sources.gw_desktop_form.select_desktop_nights", side_effect=_nights):
                with patch("greatwalkbot.sources.gw_desktop_form.select_desktop_people", side_effect=_people):
                    prepare_desktop_search_form(
                        page,
                        MILFORD,
                        start_date=date(2026, 12, 7),
                        nights=3,
                        people_size=2,
                    )
    assert call_order == ["track", "date", "nights", "people"]


def test_final_verification_fails_when_date_remains_wrong():
    page = IdempotentDesktopPage(_milford_live_state())
    with patch(
        "greatwalkbot.sources.gw_desktop_form.set_desktop_start_date",
        side_effect=GreatWalkDateControlDiscoveryIncompleteError(
            "date picker unknown",
            date_iso="2026-12-07",
        ),
    ):
        with pytest.raises(GreatWalkDateControlDiscoveryIncompleteError):
            prepare_desktop_search_form(
                page,
                MILFORD,
                start_date=date(2026, 12, 7),
                nights=3,
                people_size=2,
            )


def test_final_verification_fails_when_people_remains_wrong():
    page = IdempotentDesktopPage(_milford_live_state())

    def _noop_date(*_args, **_kwargs) -> None:
        page.state["start_date_control"] = {
            "visible_text": "07/12/2026",
            "data_date": "2026-12-07",
            "enabled": True,
        }

    with patch("greatwalkbot.sources.gw_desktop_form.set_desktop_start_date", side_effect=_noop_date):
        with patch("greatwalkbot.sources.gw_desktop_form.select_desktop_people"):
            with pytest.raises(SearchFormValidationError, match="people"):
                prepare_desktop_search_form(
                    page,
                    MILFORD,
                    start_date=date(2026, 12, 7),
                    nights=3,
                    people_size=2,
                )


def test_metadata_response_200_produces_backend_metadata_confirmed():
    recorder = NetworkRecorder()
    recorder.begin_cycle(place_id=MILFORD.place_id)
    recorder._append(
        phase="response",
        method="GET",
        path="search/getgreatwalksearchdata/placeId/{id}",
        status=200,
        content_type="application/json",
    )
    assert recorder.saw_selection_metadata(MILFORD.place_id) is True

    from greatwalkbot.inspect_greatwalk_dom import wait_for_selection_metadata

    assert wait_for_selection_metadata(recorder, MILFORD.place_id, timeout_ms=1) is True


def test_debug_search_metadata_not_false_when_timeline_has_200():
    plan = TripPlan(
        trip=Trip(
            name="Test",
            party=Party(adults=2),
            travel_window=TravelWindow(date(2026, 12, 1), date(2026, 12, 31)),
            tracks=(
                TrackPreference(
                    slug="milford",
                    acceptable_start_range=DateRange(date(2026, 12, 1), date(2026, 12, 31)),
                    preferred_start_range=DateRange(date(2026, 12, 6), date(2026, 12, 14)),
                    complete_itinerary_only=True,
                ),
            ),
        ),
        polling_interval_seconds=300,
    )
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    recorder = NetworkRecorder()
    recorder.begin_cycle(place_id=MILFORD.place_id)
    recorder._append(
        phase="response",
        method="GET",
        path="search/getgreatwalksearchdata/placeId/{id}",
        status=200,
        content_type="application/json",
    )

    with patch("greatwalkbot.debug_search.SessionManager") as session_cls:
        session = MagicMock()
        session.is_healthy.return_value = True
        session.network = recorder
        session.capture_availability_after_search = MagicMock(return_value={})
        session_cls.return_value = session
        with patch("greatwalkbot.debug_search.commit_track_selection"):
            with patch("greatwalkbot.debug_search.bootstrap_great_walk_ui"):
                    with patch(
                        "greatwalkbot.debug_search.wait_for_selection_metadata",
                        return_value=False,
                    ):
                        with patch(
                            "greatwalkbot.debug_search.resolve_desktop_great_walk_root",
                            return_value=binding,
                        ):
                            with patch_refresh_desktop_root(binding):
                                with patch(
                                    "greatwalkbot.debug_search.capture_desktop_selection_state",
                                    side_effect=lambda page, track, backend_metadata_confirmed: {
                                        "backend_metadata_confirmed": backend_metadata_confirmed,
                                        "visible_selection_committed": True,
                                    },
                                ) as capture_selection:
                                    with patch(
                                        "greatwalkbot.debug_search.capture_search_form_state",
                                        return_value={"nights_control": {"matches_requested": True}},
                                    ):
                                        with patch(
                                            "greatwalkbot.debug_search.prepare_search_form",
                                            return_value={"nights_control": {"matches_requested": True}},
                                        ):
                                            report = run_debug_search(
                                                plan,
                                                MILFORD,
                                                start_date=date(2026, 12, 7),
                                            )
    capture_selection.assert_called_once()
    assert capture_selection.call_args.kwargs["backend_metadata_confirmed"] is True
    assert report.result == "success"
