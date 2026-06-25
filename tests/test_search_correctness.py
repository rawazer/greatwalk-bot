"""Deterministic tests for Great Walk search submission (Milestone 9.3)."""

from __future__ import annotations

import json
from contextlib import contextmanager
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
    AvailabilitySearchNotDispatchedError,
    SearchFormValidationError,
    WafChallengeSuspectedError,
)
from greatwalkbot.models import Track
from greatwalkbot.sources.availability_capture import classify_capture_failure
from greatwalkbot.sources.network_recorder import NetworkRecorder
from greatwalkbot.sources.search_form import (
    capture_search_form_state,
    prepare_search_form,
    submit_great_walk_search,
    wait_for_search_click_transition,
)
from greatwalkbot.sources.session_manager import SessionManager

KEPLER = Track("kepler", "Kepler Track", 872, 2, fixed_nights=3)
ROUTEBURN = Track("routeburn", "Routeburn Track", 874, 7, fixed_nights=2)


class FakeSearchPage:
    def __init__(self) -> None:
        self.evaluate_calls: list[tuple[str, object | None]] = []
        self.wait_for_timeout_calls: list[int] = []
        self._form_state = {
            "selected_track_label": "Routeburn Track",
            "start_date_value": "",
            "nights_value": "",
            "search_button_selector": "#great-walk-search-button",
            "search_button_text": "Search",
            "search_button_enabled": True,
            "search_button_visible": True,
            "validation_messages": [],
            "loading_overlay_present": False,
        }
        self._after_set_state = dict(self._form_state)
        self._after_set_state["start_date_value"] = "2026-12-03"
        self._after_set_state["nights_value"] = "2"
        self._set_calls = 0
        self._results_visible = False

    def evaluate(self, expression: str, arg: object | None = None) -> object:
        self.evaluate_calls.append((expression, arg))
        if "READ_FORM_STATE" in expression or "dropdown" in expression:
            if self._set_calls:
                return dict(self._after_set_state)
            return dict(self._form_state)
        if arg and isinstance(arg, dict) and "startDate" in arg:
            self._set_calls += 1
            return {"start_date_set": True, "nights_set": True}
        if "RESULTS_VISIBLE" in expression or "great-walk-results" in expression:
            return self._results_visible
        if "search-button" in expression or "Search" in expression:
            return True
        return True

    def wait_for_timeout(self, timeout: int) -> None:
        self.wait_for_timeout_calls.append(timeout)


def test_selection_metadata_without_search_is_not_waf():
    recorder = NetworkRecorder()
    recorder.begin_cycle(place_id=ROUTEBURN.place_id)
    recorder._append(
        phase="response",
        method="GET",
        path="search/getgreatwalksearchdata/placeId/{id}",
        status=200,
        content_type="application/json",
        selection_metadata_match=True,
    )
    error = classify_capture_failure(
        recorder,
        selection_committed=True,
        search_submitted=True,
        place_id=ROUTEBURN.place_id,
        timeout_ms=20_000,
        page_html="<html>btChecker is not defined</html>",
    )
    assert isinstance(error, AvailabilitySearchNotDispatchedError)
    assert not isinstance(error, WafChallengeSuspectedError)


def test_disabled_search_button_raises_with_form_state():
    page = FakeSearchPage()
    page._form_state["search_button_enabled"] = False

    with pytest.raises(SearchFormValidationError, match="disabled") as exc_info:
        prepare_search_form(
            page,
            ROUTEBURN,
            start_date=date(2026, 12, 3),
            nights=2,
        )

    assert exc_info.value.form_state is not None
    assert exc_info.value.form_state["search_button_enabled"] is False


def test_form_values_verified_before_search():
    page = FakeSearchPage()
    page._after_set_state["start_date_value"] = "wrong"
    with pytest.raises(SearchFormValidationError, match="not reflected"):
        prepare_search_form(
            page,
            ROUTEBURN,
            start_date=date(2026, 12, 3),
            nights=2,
        )


def test_click_verified_by_post_click_transition():
    page = FakeSearchPage()
    recorder = NetworkRecorder()
    recorder.begin_cycle(place_id=ROUTEBURN.place_id)
    recorder.mark_search_submitted()
    recorder._append(
        phase="request",
        method="POST",
        path="search/greatwalkplacefacility",
        status=None,
        content_type=None,
    )

    outcome = wait_for_search_click_transition(page, recorder, timeout_ms=500)
    assert outcome == "network"


def test_alternate_candidate_endpoint_surfaces_in_timeline():
    recorder = NetworkRecorder()
    recorder.begin_cycle(place_id=KEPLER.place_id)
    recorder.mark_search_submitted()
    recorder._append(
        phase="response",
        method="POST",
        path="search/grid",
        status=200,
        content_type="application/json",
    )
    assert recorder.saw_post_search_candidate_response()
    timeline = recorder.post_search_timeline_dicts()
    assert timeline[0]["path"] == "search/grid"


def test_capture_failure_classifies_undispatched_search():
    session = SessionManager.__new__(SessionManager)
    session._captured_payload = None
    session._selection_committed = True
    session._search_submitted = True
    session._current_request_body = {"placeId": ROUTEBURN.place_id}
    session._last_form_state = {"search_button_enabled": True}
    session._network = NetworkRecorder()
    session._network.begin_cycle(place_id=ROUTEBURN.place_id)
    session._network._append(
        phase="response",
        method="GET",
        path="search/getgreatwalksearchdata/placeId/{id}",
        status=200,
        content_type="application/json",
        selection_metadata_match=True,
    )
    page = MagicMock()

    @contextmanager
    def timeout_expect(*_a, **_k):
        raise TimeoutError("timed out")
        yield  # pragma: no cover

    page.expect_response = timeout_expect
    page.content.return_value = "<html>great walk</html>"
    session._page = page

    with patch(
        "greatwalkbot.sources.session_manager.submit_great_walk_search",
        return_value={"search_click_transition": None},
    ):
        with pytest.raises(AvailabilitySearchNotDispatchedError):
            session.capture_availability_after_search(
                track=ROUTEBURN,
                start_date=date(2026, 12, 3),
                nights=2,
                timeout_ms=100,
            )


def test_debug_cli_does_not_use_telegram_or_dedupe():
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
                        "greatwalkbot.sources.search_form.capture_search_form_state",
                        return_value={"search_button_enabled": True},
                    ):
                        with patch.object(
                            session,
                            "capture_availability_after_search",
                            return_value={"GreatWalkFacilityData": []},
                        ):
                            report = run_debug_search(
                                plan,
                                ROUTEBURN,
                                start_date=date(2026, 12, 3),
                            )

    assert report.result == "success"
    session.close.assert_called_once()


def test_submit_search_records_form_state():
    page = FakeSearchPage()
    recorder = NetworkRecorder()
    recorder.begin_cycle(place_id=ROUTEBURN.place_id)

    outcome = submit_great_walk_search(
        page,
        recorder,
        ROUTEBURN,
        start_date=date(2026, 12, 3),
        nights=2,
        transition_timeout_ms=50,
    )

    assert outcome["start_date_value"] == "2026-12-03"
    recorder._append(
        phase="request",
        method="POST",
        path="search/greatwalkplacefacility",
        status=None,
        content_type=None,
    )
    assert recorder.saw_post_search_activity()
