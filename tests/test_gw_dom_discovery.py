"""Tests for evidence-driven Great Walk DOM discovery (Milestone 9.6)."""

from __future__ import annotations

import json
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
    GreatWalkControlDiscoveryIncompleteError,
    GreatWalkDateControlDiscoveryIncompleteError,
    GreatWalkDesktopRootError,
)
from greatwalkbot.inspect_greatwalk_dom import run_inspect_greatwalk_dom
from greatwalkbot.models import Track
from greatwalkbot.sources.diagnostics import save_dom_inspection_artifacts
from greatwalkbot.sources.gw_desktop_form import DesktopRootBinding
from greatwalkbot.sources.gw_control_gate import run_control_discovery_gate
from greatwalkbot.sources.gw_dom_discovery import (
    ControlDiscoveryAssessment,
    assess_control_discovery,
    discover_great_walk_dom,
)
from greatwalkbot.sources.gw_active_form import ActiveFormResolution

ROUTEBURN = Track("routeburn", "Routeburn Track", 874, 7, fixed_nights=2)
MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)


def _complete_candidates() -> list[dict]:
    return [
        {
            "tag": "BUTTON",
            "id": "great-walk-dropdown-button",
            "visible": True,
            "enabled": True,
            "text": "Milford Track",
            "suggested_locator": "#great-walk-dropdown-button",
        },
        {
            "tag": "INPUT",
            "id": "great-walk-start-date-input",
            "type": "hidden",
            "visible": False,
            "enabled": True,
            "value": "2026-12-07",
            "suggested_locator": "#great-walk-start-date-input",
        },
        {
            "tag": "SELECT",
            "id": "great-walk-nights",
            "visible": True,
            "enabled": True,
            "value": "3",
            "selected_option_value": "3",
            "selected_option_text": "3 nights",
            "suggested_locator": "#great-walk-nights",
        },
        {
            "tag": "BUTTON",
            "id": "great-walk-search-button",
            "visible": True,
            "enabled": True,
            "text": "Search",
            "suggested_locator": "#great-walk-search-button",
        },
    ]


def _form1_only_report() -> dict:
    return {
        "candidate_count": 2,
        "candidates": [
            {
                "tag": "FORM",
                "id": "form1",
                "visible": True,
                "enabled": True,
                "text": "Search",
                "suggested_locator": "#form1",
            },
            {
                "tag": "BUTTON",
                "id": "btnSearch",
                "visible": True,
                "enabled": True,
                "text": "Search",
                "suggested_locator": "#btnSearch",
            },
        ],
        "visible_controls": [
            {
                "tag": "BUTTON",
                "id": "btnSearch",
                "text": "Search",
                "value": None,
                "enabled": True,
                "suggested_locator": "#btnSearch",
            }
        ],
        "page_containers": {
            "form1_present": True,
            "form1_has_great_walk_descendants": False,
        },
    }


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


class FakeDiscoveryPage:
    def __init__(self, report: dict) -> None:
        self._report = report

    def evaluate(self, expression: str, arg=None) -> object:
        if "form1_present" in expression or "candidate_count" in expression:
            return self._report
        return False


def test_assess_form1_alone_is_not_nested_great_walk_form():
    assessment = assess_control_discovery(_form1_only_report())
    assert not assessment.complete
    assert assessment.form1_is_only_container
    assert "track" in assessment.missing
    assert "nights" in assessment.missing
    assert "start_date" in assessment.missing


def test_assess_complete_discovery_finds_all_controls():
    report = {
        "candidate_count": 4,
        "candidates": _complete_candidates(),
        "visible_controls": [],
        "page_containers": {"form1_present": True, "form1_has_great_walk_descendants": True},
    }
    assessment = assess_control_discovery(report)
    assert assessment.complete
    assert assessment.missing == ()


def test_discover_report_is_bounded():
    page = FakeDiscoveryPage(
        {
            "candidate_count": 1,
            "candidates": _complete_candidates(),
            "visible_controls": _complete_candidates(),
            "page_containers": {},
        }
    )
    report = discover_great_walk_dom(page)
    assert report["candidate_count"] == 1
    assert len(report["candidates"]) <= 80
    assert len(report["visible_controls"]) <= 40


def test_dom_report_includes_semantic_select_values(tmp_path: Path):
    report = {
        "candidate_count": 1,
        "candidates": _complete_candidates(),
        "visible_controls": [],
        "page_containers": {},
    }
    artifacts = save_dom_inspection_artifacts(
        page=None,
        track_name="Milford Track",
        track_slug="milford",
        dom_report=report,
        discovery_summary={"discovery_complete": True},
        diagnostics_dir=tmp_path,
    )
    dom_json = json.loads((artifacts.directory / "dom_report.json").read_text(encoding="utf-8"))
    nights = next(c for c in dom_json["candidates"] if c["id"] == "great-walk-nights")
    assert nights["value"] == "3"
    assert nights["selected_option_text"] == "3 nights"
    assert "cookie" not in json.dumps(dom_json).lower()


def test_control_gate_raises_incomplete_with_diagnostic_path(tmp_path: Path):
    page = MagicMock()
    page.url = "https://example.com"
    with patch(
        "greatwalkbot.sources.gw_control_gate.discover_great_walk_dom",
        return_value=_form1_only_report(),
    ):
        with patch(
            "greatwalkbot.sources.gw_control_gate.save_dom_inspection_artifacts"
        ) as save_artifacts:
            from greatwalkbot.sources.diagnostics import DiagnosticArtifacts

            save_artifacts.return_value = DiagnosticArtifacts(
                directory=tmp_path / "dom_diag",
                summary_path=tmp_path / "dom_diag" / "summary.json",
                screenshot_path=None,
            )
            with pytest.raises(GreatWalkControlDiscoveryIncompleteError) as exc_info:
                run_control_discovery_gate(
                    page,
                    track_name="Milford Track",
                    track_slug="milford",
                    selection_metadata_confirmed=True,
                )
    assert exc_info.value.diagnostic_path == str(tmp_path / "dom_diag")


def test_inspect_cli_has_no_telegram_dedupe_or_search_side_effects():
    with patch("greatwalkbot.inspect_greatwalk_dom.SessionManager") as session_cls:
        session = MagicMock()
        session.network.timeline_dicts.return_value = []
        session_cls.return_value = session
        with patch("greatwalkbot.inspect_greatwalk_dom.navigate_to_site"):
            with patch("greatwalkbot.inspect_greatwalk_dom.wait_for_great_walk_ui"):
                with patch("greatwalkbot.inspect_greatwalk_dom.commit_track_selection"):
                    with patch(
                        "greatwalkbot.inspect_greatwalk_dom.wait_for_selection_metadata",
                        return_value=True,
                    ):
                        with patch(
                            "greatwalkbot.inspect_greatwalk_dom.resolve_desktop_great_walk_root",
                        ) as resolve_root:
                            from greatwalkbot.sources.gw_desktop_form import DesktopRootBinding

                            resolve_root.return_value = DesktopRootBinding(
                                selector='div[role="search"].themeTopsearch:visible',
                                count=1,
                            )
                            with patch(
                                "greatwalkbot.inspect_greatwalk_dom.discover_desktop_dropdown_options",
                                return_value={"track_options": [], "nights_options": [], "people_options": []},
                            ):
                                with patch(
                                    "greatwalkbot.inspect_greatwalk_dom.discover_great_walk_dom",
                                    return_value={
                                        "candidate_count": 4,
                                        "candidates": _complete_candidates(),
                                        "visible_controls": [],
                                        "page_containers": {},
                                    },
                                ):
                                    with patch(
                                        "greatwalkbot.inspect_greatwalk_dom.save_dom_inspection_artifacts"
                                    ) as save_artifacts:
                                        from greatwalkbot.sources.diagnostics import DiagnosticArtifacts

                                        save_artifacts.return_value = DiagnosticArtifacts(
                                            directory=Path("logs/diagnostics/test_milford"),
                                            summary_path=Path("logs/diagnostics/test_milford/summary.json"),
                                            screenshot_path=None,
                                        )
                                        report = run_inspect_greatwalk_dom(MILFORD)

    session.prepare_fetch.assert_not_called()
    session.capture_availability_after_search.assert_not_called()
    assert report.diagnostic_path.endswith("test_milford")
    session.close.assert_called_once()


def test_inspect_headed_pause_is_bounded():
    with pytest.raises(ValueError, match="at most"):
        run_inspect_greatwalk_dom(MILFORD, pause_seconds=999)


def test_debug_search_reports_date_discovery_incomplete(tmp_path: Path):
    plan = _trip_plan()
    with patch("greatwalkbot.debug_search.SessionManager") as session_cls:
        session = MagicMock()
        session.is_healthy.return_value = True
        session.network.timeline_dicts.return_value = []
        session.network.post_search_timeline_dicts.return_value = []
        session.network.saw_selection_metadata.return_value = True
        session.last_form_state = None
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
                            return_value=DesktopRootBinding(
                                selector='div[role="search"].themeTopsearch:visible',
                                count=1,
                            ),
                        ):
                            with patch(
                                "greatwalkbot.debug_search.capture_desktop_selection_state",
                                return_value={"visible_selection_committed": True},
                            ):
                                with patch(
                                    "greatwalkbot.debug_search.prepare_search_form",
                                    side_effect=GreatWalkDateControlDiscoveryIncompleteError(
                                        "date unknown",
                                        date_iso="2026-12-03",
                                    ),
                                ):
                                    with patch(
                                        "greatwalkbot.debug_search._save_date_picker_diagnostics"
                                    ) as save_diag:
                                        from greatwalkbot.sources.diagnostics import DiagnosticArtifacts

                                        save_diag.return_value = DiagnosticArtifacts(
                                            directory=tmp_path / "dom_diag",
                                            summary_path=tmp_path / "dom_diag" / "summary.json",
                                            screenshot_path=None,
                                        )
                                        report = run_debug_search(
                                            plan,
                                            ROUTEBURN,
                                            start_date=date(2026, 12, 3),
                                        )

    assert report.result == "failed"
    assert report.error_type == "GreatWalkDateControlDiscoveryIncompleteError"
    assert report.dom_diagnostic_path == str(tmp_path / "dom_diag")
    session.capture_availability_after_search.assert_not_called()


def test_debug_search_success_when_desktop_form_ready():
    plan = _trip_plan()
    from greatwalkbot.sources.gw_desktop_form import DesktopRootBinding

    binding = DesktopRootBinding(selector='div[role="search"].themeTopsearch:visible', count=1)

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
    session.capture_availability_after_search.assert_called_once()
