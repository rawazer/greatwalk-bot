"""Deterministic tests for Great Walk search submission (Milestone 9.3+)."""

from __future__ import annotations

from contextlib import contextmanager
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
    AvailabilitySearchNotDispatchedError,
    SearchFormValidationError,
    WafChallengeSuspectedError,
)
from greatwalkbot.models import Track
from greatwalkbot.sources.availability_capture import classify_capture_failure
from greatwalkbot.sources.gw_active_form import ActiveFormResolution
from greatwalkbot.sources.network_recorder import NetworkRecorder
from greatwalkbot.sources.search_form import prepare_search_form, submit_great_walk_search
from greatwalkbot.sources.session_manager import SessionManager
from test_form_controls import ACTIVE_RESOLUTION, FakeFormPage, _ready_state

KEPLER = Track("kepler", "Kepler Track", 872, 2, fixed_nights=3)
ROUTEBURN = Track("routeburn", "Routeburn Track", 874, 7, fixed_nights=2)


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
    page = FakeFormPage()
    ready = _ready_state()
    ready["search_button_enabled"] = False
    with patch(
        "greatwalkbot.sources.search_form.wait_for_active_form_ready",
        return_value=(ACTIVE_RESOLUTION, ready),
    ):
        with patch(
            "greatwalkbot.sources.search_form.capture_search_form_state",
            return_value=ready,
        ):
            with pytest.raises(SearchFormValidationError, match="disabled"):
                prepare_search_form(
                    page,
                    ROUTEBURN,
                    start_date=date(2026, 12, 3),
                    nights=2,
                )


def test_form_values_verified_before_search():
    page = FakeFormPage()
    ready = _ready_state(start_date_value="2026-06-26", nights_value="20")
    ready["start_date_control"]["matches_requested"] = False
    with patch(
        "greatwalkbot.sources.search_form.wait_for_active_form_ready",
        return_value=(ACTIVE_RESOLUTION, ready),
    ):
        with patch(
            "greatwalkbot.sources.search_form.wait_for_active_form_values",
            return_value=ready,
        ):
            with pytest.raises(SearchFormValidationError, match="not reflected"):
                prepare_search_form(
                    page,
                    ROUTEBURN,
                    start_date=date(2026, 12, 3),
                    nights=2,
                )


def test_click_verified_by_post_click_transition():
    from greatwalkbot.sources.search_form import wait_for_search_click_transition

    page = FakeFormPage()
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
    with patch(
        "greatwalkbot.sources.search_form.capture_search_form_state",
        return_value=_ready_state(),
    ):
        outcome = wait_for_search_click_transition(
            page, recorder, timeout_ms=500, resolution=ACTIVE_RESOLUTION
        )
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
    assert recorder.post_search_timeline_dicts()[0]["path"] == "search/grid"


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
        session.capture_availability_after_search = MagicMock(return_value={"GreatWalkFacilityData": []})
        session_cls.return_value = session
        with patch("greatwalkbot.debug_search.commit_track_selection"):
            with patch("greatwalkbot.debug_search.navigate_to_site"):
                with patch("greatwalkbot.debug_search.wait_for_great_walk_ui"):
                    with patch(
                        "greatwalkbot.debug_search.wait_for_selection_metadata",
                        return_value=True,
                    ):
                        with patch(
                            "greatwalkbot.debug_search.run_control_discovery_gate",
                            return_value=({}, MagicMock(complete=True, missing=(), found={}, notes=(), form1_is_only_container=False), MagicMock(directory=Path("logs/diag"))),
                        ):
                            with patch(
                                "greatwalkbot.debug_search.resolve_active_great_walk_form",
                                return_value=ACTIVE_RESOLUTION,
                            ):
                                with patch(
                                    "greatwalkbot.debug_search.capture_selection_state",
                                    return_value={"visible_selection_committed": True},
                                ):
                                    with patch(
                                        "greatwalkbot.debug_search.inventory_active_form",
                                        return_value=[],
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

    assert report.result == "success"
    assert report.nights == 2
    session.close.assert_called_once()


def test_submit_search_records_form_state():
    page = FakeFormPage()
    recorder = NetworkRecorder()
    recorder.begin_cycle(place_id=ROUTEBURN.place_id)
    ready = _ready_state()

    with patch(
        "greatwalkbot.sources.search_form.wait_for_active_form_ready",
        return_value=(ACTIVE_RESOLUTION, ready),
    ):
        with patch(
            "greatwalkbot.sources.search_form.wait_for_active_form_values",
            return_value=ready,
        ):
            with patch(
                "greatwalkbot.sources.search_form.wait_for_search_click_transition",
                return_value=None,
            ):
                with patch(
                    "greatwalkbot.sources.search_form.inventory_active_form",
                    return_value=[],
                ):
                    outcome = submit_great_walk_search(
                        page,
                        recorder,
                        ROUTEBURN,
                        start_date=date(2026, 12, 3),
                        nights=2,
                        transition_timeout_ms=50,
                    )

    assert outcome["nights_control"]["raw_value"] == "2"
    recorder._append(
        phase="request",
        method="POST",
        path="search/greatwalkplacefacility",
        status=None,
        content_type=None,
    )
    assert recorder.saw_post_search_activity()
