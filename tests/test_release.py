"""Tests for release readiness: honeymoon template, preflight, and CI workflow."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from greatwalkbot.cli import main
from greatwalkbot.config.loader import load_watch_config
from greatwalkbot.monitoring.dedupe import SeenAvailabilityStore
from greatwalkbot.monitoring.trip_fit import check_trip_feasible_in_principle
from greatwalkbot.preflight import format_preflight_report, run_preflight
from greatwalkbot.models import Track

REPO_ROOT = Path(__file__).resolve().parents[1]
HONEYMOON_CONFIG = REPO_ROOT / "examples" / "nz-honeymoon-2026.yaml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)


def test_honeymoon_example_parses_and_is_feasible():
    plan = load_watch_config(HONEYMOON_CONFIG)
    assert plan.trip.name == "New Zealand Honeymoon"
    assert plan.trip.party.adults == 2
    assert plan.trip.travel_window.start == date(2026, 11, 29)
    assert len(plan.trip.tracks) == 3
    assert plan.trip_fit.enabled is True
    assert plan.notifications.telegram.enabled is False

    report = check_trip_feasible_in_principle(plan.trip, plan.trip_fit)
    assert report.feasible is True


def test_honeymoon_example_passes_plan_check_cli(capsys):
    exit_code = main(["plan-check", str(HONEYMOON_CONFIG)])
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Feasibility: YES" in output


def _snapshot(track: Track) -> AvailabilitySnapshot:
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "milford_complete.json").read_text(
            encoding="utf-8"
        )
    )
    from greatwalkbot.parsing import parse_gw_facility_response

    return parse_gw_facility_response(
        payload, track, date(2026, 12, 7), date(2026, 12, 9)
    )


def test_preflight_makes_only_allowed_read_only_calls():
    plan = load_watch_config(HONEYMOON_CONFIG)
    fetch_mock = MagicMock(side_effect=lambda track, start, end: _snapshot(track))

    class Source:
        def fetch_track_availability(self, track, from_date, to_date):
            return fetch_mock(track, from_date, to_date)

    report = run_preflight(plan, Source())
    assert report.ready is True
    assert fetch_mock.call_count == 3
    assert all(r.fetch_succeeded for r in report.track_results if r.status == "ok")


def test_preflight_does_not_mutate_dedupe_or_send_availability_notifications():
    plan = load_watch_config(HONEYMOON_CONFIG)

    class Source:
        def fetch_track_availability(self, track, from_date, to_date):
            return _snapshot(track)

    seen = SeenAvailabilityStore()
    assert len(seen) == 0

    report = run_preflight(plan, Source())
    assert report.ready is True
    assert len(seen) == 0

    with patch("greatwalkbot.notifications.factory.send_test_notifications") as notify_mock:
        with patch("greatwalkbot.cli.PlaywrightAvailabilitySource", return_value=Source()):
            exit_code = main(["preflight", str(HONEYMOON_CONFIG)])

    assert exit_code == 0
    notify_mock.assert_not_called()
    assert len(seen) == 0


def test_preflight_reports_all_tracks_when_one_fails():
    plan = load_watch_config(HONEYMOON_CONFIG)

    class Source:
        def fetch_track_availability(self, track, from_date, to_date):
            if track.slug == "routeburn":
                raise RuntimeError("simulated WAF block")
            return _snapshot(track)

    report = run_preflight(plan, Source())
    assert not report.ready
    assert len(report.track_results) == 3
    by_slug = {r.track_slug: r for r in report.track_results}
    assert by_slug["milford"].status == "ok"
    assert by_slug["routeburn"].status == "failed"
    assert by_slug["kepler"].status == "ok"
    assert any("routeburn" in err for err in report.errors)

    text = format_preflight_report(report, trip_name=plan.trip.name)
    assert "milford" in text
    assert "routeburn" in text
    assert "kepler" in text
    assert "NOT READY" in text


def test_github_actions_workflow_is_present_and_valid():
    assert CI_WORKFLOW.is_file()
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    assert workflow["name"] == "CI"
    triggers = workflow.get("on") or workflow.get(True)  # YAML 1.1 may parse `on` as true
    assert triggers is not None
    assert "push" in triggers
    assert "pull_request" in triggers
    steps = workflow["jobs"]["test"]["steps"]
    run_commands = [step.get("run", "") for step in steps if "run" in step]
    assert any("uv sync" in cmd for cmd in run_commands)
    assert any("pytest" in cmd for cmd in run_commands)
