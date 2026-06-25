"""Deterministic tests for availability capture correctness (Milestone 9.2)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from greatwalkbot.infra.errors import (
    AvailabilityRequestNotObservedError,
    AvailabilitySearchNotDispatchedError,
    TrackSelectionNotCommittedError,
    WafChallengeSuspectedError,
)
from greatwalkbot.models import Track
from greatwalkbot.sources.availability_capture import (
    classify_capture_failure,
    wait_for_availability_response,
)
from greatwalkbot.sources.diagnostics import save_session_failure_diagnostics
from greatwalkbot.sources.network_recorder import (
    GREAT_WALK_CANDIDATE_PATHS,
    NetworkRecorder,
    path_matches_candidate,
    sanitize_url_path,
)
from greatwalkbot.sources.session_manager import SessionManager

KEPLER = Track("kepler", "Kepler Track", 872, 2, fixed_nights=3)
MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)
ROUTEBURN = Track("routeburn", "Routeburn Track", 874, 7, fixed_nights=2)


class ImmediateResponse:
    def __init__(self, payload: dict) -> None:
        self.status = 200
        self._payload = payload
        self.headers = {"content-type": "application/json; charset=utf-8"}
        self.url = (
            "https://prod-nz-rdr.recreation-management.tylerapp.com/nzrdr/rdr/"
            "search/greatwalkplacefacility"
        )

    def json(self) -> dict:
        return self._payload


def test_capture_listener_registered_before_click():
    page = MagicMock()
    click_order: list[str] = []

    @contextmanager
    def fake_expect_response(_predicate, timeout):
        click_order.append("listener_registered")
        info = MagicMock()
        info.value = ImmediateResponse({"GreatWalkFacilityData": []})
        yield info

    page.expect_response = fake_expect_response

    def click_search() -> None:
        click_order.append("search_clicked")

    wait_for_availability_response(
        page,
        click_search=click_search,
        timeout_ms=1_000,
    )

    assert click_order == ["listener_registered", "search_clicked"]


def test_response_emitted_during_click_is_captured():
    page = MagicMock()
    payload = {"GreatWalkFacilityData": [{"FacilityName": "Clinton Hut"}]}

    @contextmanager
    def fake_expect_response(_predicate, timeout):
        info = MagicMock()
        info.value = ImmediateResponse(payload)
        yield info

    page.expect_response = fake_expect_response

    result = wait_for_availability_response(
        page,
        click_search=lambda: None,
        timeout_ms=500,
    )

    assert result == payload


def test_selection_visible_but_not_committed_classified():
    recorder = NetworkRecorder()
    recorder.begin_cycle(place_id=MILFORD.place_id)
    error = classify_capture_failure(
        recorder,
        selection_committed=False,
        search_submitted=False,
        place_id=MILFORD.place_id,
        timeout_ms=20_000,
    )
    assert isinstance(error, TrackSelectionNotCommittedError)


def test_candidate_discovery_distinguishes_kepler_from_milford_flow():
    kepler_recorder = NetworkRecorder()
    kepler_recorder.begin_cycle(place_id=KEPLER.place_id)
    kepler_recorder._append(
        phase="response",
        method="GET",
        path="search/getgreatwalksearchdata/placeId/{id}",
        status=200,
        content_type="application/json",
        selection_metadata_match=True,
    )
    kepler_recorder._append(
        phase="response",
        method="POST",
        path="search/greatwalkplacefacility",
        status=200,
        content_type="application/json",
    )

    milford_recorder = NetworkRecorder()
    milford_recorder.begin_cycle(place_id=MILFORD.place_id)
    milford_recorder._append(
        phase="response",
        method="GET",
        path="search/getgreatwalksearchdata/placeId/{id}",
        status=200,
        content_type="application/json",
        selection_metadata_match=True,
    )

    assert kepler_recorder.saw_availability_response()
    assert not milford_recorder.saw_availability_response()
    assert milford_recorder.saw_selection_metadata(MILFORD.place_id)


def test_no_capture_without_waf_evidence_is_not_waf_error():
    recorder = NetworkRecorder()
    recorder.begin_cycle(place_id=ROUTEBURN.place_id)
    error = classify_capture_failure(
        recorder,
        selection_committed=True,
        search_submitted=True,
        place_id=ROUTEBURN.place_id,
        timeout_ms=20_000,
    )
    assert isinstance(error, AvailabilitySearchNotDispatchedError)
    assert "WAF" not in str(error)
    assert not isinstance(error, WafChallengeSuspectedError)


def test_waf_error_only_with_concrete_signals():
    recorder = NetworkRecorder()
    recorder.begin_cycle(place_id=MILFORD.place_id)
    recorder._waf_signals.append("header:x-amzn-waf-action")
    error = classify_capture_failure(
        recorder,
        selection_committed=True,
        search_submitted=True,
        place_id=MILFORD.place_id,
        timeout_ms=20_000,
    )
    assert isinstance(error, WafChallengeSuspectedError)


def test_diagnostics_timeline_sanitized_no_secrets(tmp_path):
    recorder = NetworkRecorder()
    recorder.begin_cycle(place_id=MILFORD.place_id)
    recorder._append(
        phase="request",
        method="POST",
        path=sanitize_url_path(
            "https://prod-nz-rdr.recreation-management.tylerapp.com/nzrdr/rdr/"
            "search/greatwalkplacefacility?token=secret"
        ),
        status=None,
        content_type=None,
    )
    recorder._append(
        phase="response",
        method="POST",
        path="search/greatwalkplacefacility",
        status=200,
        content_type="application/json; charset=utf-8",
    )

    artifacts = save_session_failure_diagnostics(
        page=None,
        track_name="Milford Track",
        track_slug="milford",
        error=AvailabilityRequestNotObservedError("no request"),
        diagnostics_dir=tmp_path,
        network_timeline=recorder.timeline_dicts(),
    )
    assert artifacts is not None
    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    timeline = summary["network_timeline"]
    assert len(timeline) == 2
    assert timeline[0]["path"] == "/nzrdr/rdr/search/greatwalkplacefacility?…"
    assert timeline[0]["candidate_match"] is True
    serialized = json.dumps(summary)
    assert "secret" not in serialized
    assert "cookie" not in serialized.lower()
    assert "authorization" not in serialized.lower()


def test_sanitize_url_path_redacts_ids_and_query():
    path = sanitize_url_path(
        "https://prod-nz-rdr.recreation-management.tylerapp.com/nzrdr/rdr/"
        "search/getgreatwalksearchdata/placeId/873?foo=bar"
    )
    assert path == "/nzrdr/rdr/search/getgreatwalksearchdata/placeId/{id}?…"
    assert "873" not in path
    assert "bar" not in path


def test_all_candidate_paths_recognized():
    for marker in GREAT_WALK_CANDIDATE_PATHS:
        assert path_matches_candidate(f"/nzrdr/rdr/{marker}")


def test_capture_failure_after_search_uses_typed_error():
    session = SessionManager.__new__(SessionManager)
    session._captured_payload = None
    session._selection_committed = True
    session._current_request_body = {"placeId": MILFORD.place_id}
    session._search_submitted = True
    session._last_form_state = {"search_button_enabled": True}
    session._network = NetworkRecorder()
    session._network.begin_cycle(place_id=MILFORD.place_id)
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
                track=MILFORD,
                start_date=date(2026, 12, 3),
                nights=3,
                people_size=2,
                timeout_ms=100,
            )
