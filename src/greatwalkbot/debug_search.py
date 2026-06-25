"""Read-only Great Walk search debugging (single browser attempt)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from greatwalkbot.domain.plan import TripPlan
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.infra.errors import (
    GreatWalkDateControlDiscoveryIncompleteError,
    GreatWalkDatePickerError,
    GreatWalkDateUnavailableError,
    RetryableError,
)
from greatwalkbot.inspect_greatwalk_dom import wait_for_selection_metadata
from greatwalkbot.itinerary_form import resolve_form_nights
from greatwalkbot.models import Track
from greatwalkbot.parsing import build_gw_facility_request
from greatwalkbot.sources.diagnostics import (
    DiagnosticArtifacts,
    save_dom_inspection_artifacts,
    save_session_failure_diagnostics,
)
from greatwalkbot.sources.gw_desktop_form import (
    capture_desktop_selection_state,
    discover_date_picker_elements,
    discover_desktop_dropdown_options,
    refresh_desktop_root_binding,
    resolve_desktop_great_walk_root,
)
from greatwalkbot.sources.search_form import capture_search_form_state, prepare_search_form
from greatwalkbot.sources.session_manager import SessionManager
from greatwalkbot.sources.spa_navigation import (
    bootstrap_great_walk_ui,
    commit_track_selection,
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
    people_size: int
    itinerary_direction: str | None
    selection_state: dict[str, Any] | None
    selection_committed: bool
    desktop_root: dict[str, Any] | None
    dom_diagnostic_path: str | None
    form_state_before_search: dict[str, Any] | None
    search_outcome: dict[str, Any] | None
    network_timeline: list[dict[str, Any]]
    post_search_timeline: list[dict[str, Any]]
    result: str
    error_type: str | None
    error_message: str | None
    diagnostics: DiagnosticArtifacts | None
    navigation_timing: dict[str, Any] | None = None

    def to_text(self) -> str:
        lines = [
            f"Track: {self.track_name} ({self.track_slug})",
            f"Start date: {self.start_date.isoformat()}  Nights: {self.nights}  People: {self.people_size}",
        ]
        if self.itinerary_direction:
            lines.append(f"Itinerary direction: {self.itinerary_direction}")
        lines.extend(
            [
                f"Selection committed (automation): {self.selection_committed}",
                "",
                "Desktop root:",
                json.dumps(self.desktop_root or {}, indent=2),
            ]
        )
        if self.dom_diagnostic_path:
            lines.extend(["", f"DOM diagnostics: {self.dom_diagnostic_path}"])
        lines.extend(
            [
                "",
                "Selection state:",
                json.dumps(self.selection_state or {}, indent=2),
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
            lines.extend([f"Error: {self.error_type}: {self.error_message}"])
        if self.navigation_timing:
            lines.extend(
                [
                    "",
                    "Navigation timing:",
                    json.dumps(self.navigation_timing, indent=2),
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


def _save_date_picker_diagnostics(
    page: Any,
    *,
    track: Track,
    metadata_confirmed: bool,
    network_timeline: list[dict[str, Any]],
    form_state: dict[str, Any] | None = None,
) -> DiagnosticArtifacts:
    dropdowns = discover_desktop_dropdown_options(page) if page is not None else {}
    date_picker = discover_date_picker_elements(page) if page is not None else []
    summary: dict[str, Any] = {
        "selection_metadata_confirmed": metadata_confirmed,
        "desktop_dropdown_options": dropdowns,
        "date_picker_elements": date_picker,
        "form_state": form_state,
        "notes": ["Date picker binding incomplete; review date_picker_elements"],
    }
    return save_dom_inspection_artifacts(
        page=page,
        track_name=track.name,
        track_slug=track.slug,
        dom_report={
            "desktop_dropdown_options": dropdowns,
            "date_picker_elements": date_picker,
            "form_state": form_state,
        },
        discovery_summary=summary,
        network_timeline=network_timeline,
        prefix="debug-date",
    )


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

    people_size = plan.trip.party.size
    to_date = start_date + timedelta(days=(bounds.end - bounds.start).days)
    request_body = build_gw_facility_request(track, start_date, to_date)

    session = SessionManager(headless=not headed)
    selection_state: dict[str, Any] | None = None
    selection_committed = False
    desktop_root: dict[str, Any] | None = None
    dom_diagnostic_path: str | None = None
    form_state: dict[str, Any] | None = None
    search_outcome: dict[str, Any] | None = None
    diagnostics: DiagnosticArtifacts | None = None
    error_type: str | None = None
    error_message: str | None = None
    result = "success"
    network_timeline: list[dict[str, Any]] = []
    post_search_timeline: list[dict[str, Any]] = []
    metadata_confirmed = False
    navigation_timing: dict[str, Any] | None = None

    try:
        browser_started = time.monotonic()
        session.start()
        browser_start_seconds = time.monotonic() - browser_started
        session.prepare_fetch(request_body)
        page = session.page
        recorder = session.network

        stage_timing = bootstrap_great_walk_ui(
            page,
            shell_timeout_ms=navigation_timeout_ms,
            spa_ready_timeout_ms=app_ready_timeout_ms,
            recorder=recorder,
            browser_start_seconds=browser_start_seconds,
        )
        navigation_timing = stage_timing.to_dict()

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

        binding = resolve_desktop_great_walk_root(page)

        selection_state = capture_desktop_selection_state(
            page,
            track,
            backend_metadata_confirmed=metadata_confirmed,
        )
        binding, root_refresh = refresh_desktop_root_binding(page, binding)
        desktop_root = {
            "selector": binding.selector,
            "count": binding.count,
            "id": binding.root_id,
            "class": binding.root_class,
            "root_refresh": root_refresh,
        }
        selection_committed = bool(
            selection_state.get("backend_metadata_confirmed")
            or selection_state.get("visible_selection_committed")
        )

        form_state = capture_search_form_state(
            page,
            track=track,
            start_date=start_date,
            nights=nights,
            people_size=people_size,
            binding=binding,
        )
        form_state = {
            **form_state,
            "selection": selection_state,
            "backend_metadata_confirmed": metadata_confirmed,
        }

        form_state = prepare_search_form(
            page,
            track,
            start_date=start_date,
            nights=nights,
            people_size=people_size,
        )
        form_state = {
            **form_state,
            "selection": selection_state,
            "backend_metadata_confirmed": metadata_confirmed,
        }

        session.capture_availability_after_search(
            track=track,
            start_date=start_date,
            nights=nights,
            people_size=people_size,
            timeout_ms=capture_timeout_ms,
        )
        search_outcome = session.last_form_state
        result = "success"
    except (
        GreatWalkDateControlDiscoveryIncompleteError,
        GreatWalkDateUnavailableError,
        GreatWalkDatePickerError,
    ) as exc:
        result = "failed"
        error_type = type(exc).__name__
        error_message = str(exc)
        form_state = getattr(exc, "form_state", None) or form_state
        timeline = session.network.timeline_dicts() if session.is_healthy() else []
        artifacts = _save_date_picker_diagnostics(
            session.page if session.is_healthy() else None,
            track=track,
            metadata_confirmed=metadata_confirmed,
            network_timeline=timeline,
            form_state=form_state,
        )
        dom_diagnostic_path = str(artifacts.directory)
        exc.diagnostic_path = dom_diagnostic_path  # type: ignore[attr-defined]
    except RetryableError as exc:
        result = "failed"
        error_type = type(exc).__name__
        error_message = str(exc)
        if navigation_timing is None and getattr(exc, "timing", None):
            navigation_timing = exc.timing
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
        people_size=people_size,
        itinerary_direction=direction,
        selection_state=selection_state,
        selection_committed=selection_committed,
        desktop_root=desktop_root,
        dom_diagnostic_path=dom_diagnostic_path,
        form_state_before_search=form_state,
        search_outcome=search_outcome,
        network_timeline=network_timeline,
        post_search_timeline=post_search_timeline,
        result=result,
        error_type=error_type,
        error_message=error_message,
        diagnostics=diagnostics,
        navigation_timing=navigation_timing,
    )
