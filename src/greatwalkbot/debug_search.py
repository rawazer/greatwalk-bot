"""Read-only Great Walk search debugging (single browser attempt)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from greatwalkbot.constants import GREATWALK_HASH
from greatwalkbot.domain.plan import TripPlan
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.infra.errors import GreatWalkControlDiscoveryIncompleteError, RetryableError
from greatwalkbot.inspect_greatwalk_dom import wait_for_selection_metadata
from greatwalkbot.itinerary_form import resolve_form_nights
from greatwalkbot.models import Track
from greatwalkbot.parsing import build_gw_facility_request
from greatwalkbot.sources.diagnostics import DiagnosticArtifacts, save_session_failure_diagnostics
from greatwalkbot.sources.gw_active_form import (
    capture_selection_state,
    inventory_active_form,
    resolve_active_great_walk_form,
)
from greatwalkbot.sources.gw_control_gate import run_control_discovery_gate
from greatwalkbot.sources.search_form import capture_search_form_state, prepare_search_form
from greatwalkbot.sources.session_manager import SessionManager
from greatwalkbot.sources.spa_navigation import (
    commit_track_selection,
    navigate_to_site,
    wait_for_great_walk_ui,
)
from greatwalkbot.sources.spa_timing import (
    DEFAULT_APP_READY_TIMEOUT_MS,
    DEFAULT_CAPTURE_TIMEOUT_MS,
    DEFAULT_NAVIGATION_TIMEOUT_MS,
    DEFAULT_SELECTION_COMMIT_TIMEOUT_MS,
)


@dataclass(frozen=True)
class DebugSearchReport:
    track_slug: str
    track_name: str
    start_date: date
    nights: int
    itinerary_direction: str | None
    selection_state: dict[str, Any] | None
    selection_committed: bool
    control_discovery: dict[str, Any] | None
    dom_diagnostic_path: str | None
    active_form_resolution: dict[str, Any] | None
    active_form_inventory: list[dict[str, Any]] | None
    form_state_before_search: dict[str, Any] | None
    search_outcome: dict[str, Any] | None
    network_timeline: list[dict[str, Any]]
    post_search_timeline: list[dict[str, Any]]
    result: str
    error_type: str | None
    error_message: str | None
    diagnostics: DiagnosticArtifacts | None

    def to_text(self) -> str:
        lines = [
            f"Track: {self.track_name} ({self.track_slug})",
            f"Start date: {self.start_date.isoformat()}  Nights: {self.nights}",
        ]
        if self.itinerary_direction:
            lines.append(f"Itinerary direction: {self.itinerary_direction}")
        lines.extend(
            [
                f"Selection committed (automation): {self.selection_committed}",
                "",
                "Control discovery:",
                json.dumps(self.control_discovery or {}, indent=2),
            ]
        )
        if self.dom_diagnostic_path:
            lines.extend(["", f"DOM diagnostics: {self.dom_diagnostic_path}"])
        lines.extend(
            [
                "",
                "Active form resolution:",
                json.dumps(self.active_form_resolution or {}, indent=2),
                "",
                "Selection state:",
                json.dumps(self.selection_state or {}, indent=2),
                "",
                "Active form inventory:",
                json.dumps(self.active_form_inventory or [], indent=2),
                "",
                "Form state before Search:",
                json.dumps(self.form_state_before_search or {}, indent=2),
                "",
                "Search outcome:",
                json.dumps(self.search_outcome or {}, indent=2),
                "",
                f"Result: {self.result}",
            ]
        )
        if self.error_type:
            lines.extend(
                [
                    f"Error: {self.error_type}: {self.error_message}",
                ]
            )
        lines.extend(
            [
                "",
                "Post-search candidate timeline:",
                json.dumps(self.post_search_timeline or self.network_timeline[-10:], indent=2),
            ]
        )
        if self.diagnostics is not None:
            lines.append(f"\nFailure diagnostics: {self.diagnostics.directory}")
        return "\n".join(lines)


def _resolve_preference(plan: TripPlan, track_slug: str) -> TrackPreference:
    preference = next((pref for pref in plan.trip.tracks if pref.slug == track_slug), None)
    if preference is None:
        raise ValueError(f"Track {track_slug!r} is not configured in the trip plan")
    return preference


def run_debug_search(
    plan: TripPlan,
    track: Track,
    *,
    start_date: date,
    nights_override: int | None = None,
    headed: bool = False,
    navigation_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS,
    app_ready_timeout_ms: int = DEFAULT_APP_READY_TIMEOUT_MS,
    selection_commit_timeout_ms: int = DEFAULT_SELECTION_COMMIT_TIMEOUT_MS,
    capture_timeout_ms: int = DEFAULT_CAPTURE_TIMEOUT_MS,
) -> DebugSearchReport:
    """Run a single read-only search attempt with sanitized diagnostics."""
    preference = _resolve_preference(plan, track.slug)
    bounds = preference.query_bounds(plan.trip.travel_window)
    if not bounds.contains(start_date):
        raise ValueError(
            f"Date {start_date.isoformat()} is outside acceptable range "
            f"{bounds.start.isoformat()}..{bounds.end.isoformat()}"
        )

    nights, direction = resolve_form_nights(
        track.slug,
        complete_itinerary_only=preference.complete_itinerary_only,
        direction=preference.direction,
        fixed_nights=track.fixed_nights,
        fallback_nights=max(1, (bounds.end - bounds.start).days),
    )
    if nights_override is not None:
        nights = nights_override

    to_date = start_date + timedelta(days=(bounds.end - bounds.start).days)
    request_body = build_gw_facility_request(track, start_date, to_date)

    session = SessionManager(headless=not headed)
    selection_state: dict[str, Any] | None = None
    selection_committed = False
    control_discovery: dict[str, Any] | None = None
    dom_diagnostic_path: str | None = None
    active_form_resolution: dict[str, Any] | None = None
    active_form_inventory: list[dict[str, Any]] | None = None
    form_state: dict[str, Any] | None = None
    search_outcome: dict[str, Any] | None = None
    diagnostics: DiagnosticArtifacts | None = None
    error_type: str | None = None
    error_message: str | None = None
    result = "success"
    network_timeline: list[dict[str, Any]] = []
    post_search_timeline: list[dict[str, Any]] = []
    metadata_confirmed = False

    try:
        session.start()
        session.prepare_fetch(request_body)
        page = session.page
        recorder = session.network

        navigate_to_site(page, timeout_ms=navigation_timeout_ms)
        page.evaluate(f"window.location.hash = '{GREATWALK_HASH}'")
        wait_for_great_walk_ui(page, timeout_ms=app_ready_timeout_ms)

        session.begin_capture_cycle(place_id=track.place_id)
        commit_track_selection(
            page,
            track,
            recorder,
            navigation_timeout_ms=navigation_timeout_ms,
            app_ready_timeout_ms=app_ready_timeout_ms,
            selection_commit_timeout_ms=selection_commit_timeout_ms,
        )
        session.mark_selection_committed()
        metadata_confirmed = wait_for_selection_metadata(
            recorder,
            track.place_id,
        ) or recorder.saw_selection_metadata(track.place_id)

        timeline = recorder.timeline_dicts()
        _, assessment, dom_artifacts = run_control_discovery_gate(
            page,
            track_name=track.name,
            track_slug=track.slug,
            selection_metadata_confirmed=metadata_confirmed,
            network_timeline=timeline,
            prefix="debug",
        )
        dom_diagnostic_path = str(dom_artifacts.directory)
        control_discovery = {
            "discovery_complete": assessment.complete,
            "missing_controls": list(assessment.missing),
            "found_controls": {
                key: (value.get("suggested_locator") if value else None)
                for key, value in assessment.found.items()
            },
            "form1_is_only_container": assessment.form1_is_only_container,
            "notes": list(assessment.notes),
        }

        resolution = resolve_active_great_walk_form(page)
        active_form_resolution = {
            "candidate_count": resolution.candidate_count,
            "active_root": resolution.active_root,
            "rejected_candidates": resolution.rejected_candidates[:5],
            "note": (
                "Active root resolution is informational only; control binding "
                "requires evidence from dom_report.json"
            ),
        }
        active_form_inventory = inventory_active_form(page)

        selection_state = capture_selection_state(
            page,
            track,
            resolution,
            backend_metadata_confirmed=metadata_confirmed,
        )
        selection_committed = bool(
            selection_state.get("backend_metadata_confirmed")
            or selection_state.get("visible_selection_committed")
        )

        form_state = capture_search_form_state(
            page,
            track=track,
            start_date=start_date,
            nights=nights,
            resolution=resolution,
        )
        form_state = {
            **form_state,
            "selection": selection_state,
            "backend_metadata_confirmed": metadata_confirmed,
            "dom_diagnostic_path": dom_diagnostic_path,
        }

        prepare_search_form(
            page,
            track,
            start_date=start_date,
            nights=nights,
        )

        session.capture_availability_after_search(
            track=track,
            start_date=start_date,
            nights=nights,
            timeout_ms=capture_timeout_ms,
        )
        search_outcome = session.last_form_state
        result = "success"
    except GreatWalkControlDiscoveryIncompleteError as exc:
        result = "failed"
        error_type = type(exc).__name__
        error_message = str(exc)
        dom_diagnostic_path = exc.diagnostic_path or dom_diagnostic_path
        if exc.assessment is not None:
            assessment = exc.assessment
            control_discovery = {
                "discovery_complete": False,
                "missing_controls": list(assessment.missing),
                "found_controls": {
                    key: (value.get("suggested_locator") if value else None)
                    for key, value in assessment.found.items()
                },
                "form1_is_only_container": assessment.form1_is_only_container,
                "notes": list(assessment.notes),
            }
        if metadata_confirmed and selection_state is not None:
            selection_state = {
                **selection_state,
                "backend_metadata_confirmed": True,
            }
    except RetryableError as exc:
        result = "failed"
        error_type = type(exc).__name__
        error_message = str(exc)
        search_outcome = session.last_form_state
        form_state = form_state or getattr(exc, "form_state", None) or session.last_form_state
        if metadata_confirmed and selection_state is not None:
            selection_state = {
                **selection_state,
                "backend_metadata_confirmed": True,
            }
        diagnostics = save_session_failure_diagnostics(
            page=session.page if session.is_healthy() else None,
            track_name=track.name,
            track_slug=track.slug,
            error=exc,
            network_timeline=session.network.timeline_dicts(),
            form_state=form_state,
            active_form_inventory=active_form_inventory,
        )
    finally:
        network_timeline = session.network.timeline_dicts()
        post_search_timeline = session.network.post_search_timeline_dicts()
        session.close()

    return DebugSearchReport(
        track_slug=track.slug,
        track_name=track.name,
        start_date=start_date,
        nights=nights,
        itinerary_direction=direction,
        selection_state=selection_state,
        selection_committed=selection_committed,
        control_discovery=control_discovery,
        dom_diagnostic_path=dom_diagnostic_path,
        active_form_resolution=active_form_resolution,
        active_form_inventory=active_form_inventory,
        form_state_before_search=form_state,
        search_outcome=search_outcome,
        network_timeline=network_timeline,
        post_search_timeline=post_search_timeline,
        result=result,
        error_type=error_type,
        error_message=error_message,
        diagnostics=diagnostics,
    )
