"""Read-only Great Walk DOM inspection CLI backend."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from greatwalkbot.constants import GREATWALK_HASH
from greatwalkbot.models import Track
from greatwalkbot.sources.diagnostics import DiagnosticArtifacts, save_dom_inspection_artifacts
from greatwalkbot.sources.gw_desktop_date_picker_popup import inspect_date_picker_navigation
from greatwalkbot.sources.gw_desktop_form import (
    discover_date_picker_elements,
    discover_desktop_dropdown_options,
    open_desktop_date_picker,
    resolve_desktop_great_walk_root,
)
from greatwalkbot.sources.gw_dom_discovery import (
    assess_control_discovery,
    build_discovery_summary,
    discover_great_walk_dom,
)
from greatwalkbot.sources.session_manager import SessionManager
from greatwalkbot.sources.spa_navigation import (
    commit_track_selection,
    navigate_to_site,
    wait_for_great_walk_ui,
)
from greatwalkbot.sources.spa_timing import (
    DEFAULT_APP_READY_TIMEOUT_MS,
    DEFAULT_NAVIGATION_TIMEOUT_MS,
    DEFAULT_SELECTION_COMMIT_TIMEOUT_MS,
)

logger = logging.getLogger(__name__)

DEFAULT_METADATA_WAIT_MS = 10_000
MAX_PAUSE_SECONDS = 300


@dataclass(frozen=True)
class DomInspectionReport:
    track_slug: str
    track_name: str
    selection_metadata_confirmed: bool
    desktop_root: dict[str, Any]
    discovery_complete: bool
    diagnostic_path: str
    discovery_summary: dict[str, Any]
    artifacts: DiagnosticArtifacts

    def to_text(self) -> str:
        lines = [
            f"Track: {self.track_name} ({self.track_slug})",
            f"Selection metadata confirmed: {self.selection_metadata_confirmed}",
            f"Desktop root: {self.desktop_root.get('selector')}",
            f"Control discovery complete: {self.discovery_complete}",
            f"Diagnostics: {self.diagnostic_path}",
        ]
        dropdowns = self.discovery_summary.get("desktop_dropdown_options") or {}
        for key in ("track_options", "nights_options", "people_options"):
            opts = dropdowns.get(key) or []
            if opts:
                lines.append(f"{key}: {len(opts)} visible option(s)")
        date_elems = self.discovery_summary.get("date_picker_elements") or []
        if date_elems:
            lines.append(f"date_picker_elements: {len(date_elems)} visible node(s)")
        missing = self.discovery_summary.get("missing_controls") or []
        if missing:
            lines.append(f"Missing controls: {', '.join(missing)}")
        notes = self.discovery_summary.get("notes") or []
        for note in notes:
            lines.append(f"Note: {note}")
        return "\n".join(lines)


def wait_for_selection_metadata(
    recorder: Any,
    place_id: int,
    *,
    timeout_ms: int = DEFAULT_METADATA_WAIT_MS,
) -> bool:
    """Wait until selection metadata is observed or timeout elapses."""
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        if recorder.saw_selection_metadata(place_id):
            return True
        time.sleep(0.15)
    return recorder.saw_selection_metadata(place_id)


def run_inspect_greatwalk_dom(
    track: Track,
    *,
    headed: bool = False,
    pause_seconds: int = 0,
    open_date_picker: bool = False,
    navigation_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS,
    app_ready_timeout_ms: int = DEFAULT_APP_READY_TIMEOUT_MS,
    selection_commit_timeout_ms: int = DEFAULT_SELECTION_COMMIT_TIMEOUT_MS,
    metadata_wait_ms: int = DEFAULT_METADATA_WAIT_MS,
) -> DomInspectionReport:
    """Open Great Walk page, select track, and write sanitized DOM diagnostics."""
    if pause_seconds < 0:
        raise ValueError("pause_seconds must be non-negative")
    if pause_seconds > MAX_PAUSE_SECONDS:
        raise ValueError(f"pause_seconds must be at most {MAX_PAUSE_SECONDS}")

    session = SessionManager(headless=not headed)
    metadata_confirmed = False

    try:
        session.start()
        page = session.page
        recorder = session.network

        navigate_to_site(page, timeout_ms=navigation_timeout_ms)
        page.evaluate(f"window.location.hash = '{GREATWALK_HASH}'")
        wait_for_great_walk_ui(page, timeout_ms=app_ready_timeout_ms)

        recorder.begin_cycle(place_id=track.place_id)
        commit_track_selection(
            page,
            track,
            recorder,
            navigation_timeout_ms=navigation_timeout_ms,
            app_ready_timeout_ms=app_ready_timeout_ms,
            selection_commit_timeout_ms=selection_commit_timeout_ms,
        )
        metadata_confirmed = wait_for_selection_metadata(
            recorder,
            track.place_id,
            timeout_ms=metadata_wait_ms,
        )

        binding = resolve_desktop_great_walk_root(page)
        desktop_root = {
            "selector": binding.selector,
            "count": binding.count,
            "id": binding.root_id,
            "class": binding.root_class,
        }

        dropdown_options = discover_desktop_dropdown_options(page)
        date_picker_elements: list[dict[str, Any]] = []
        if open_date_picker:
            open_desktop_date_picker(page)
            page.wait_for_timeout(400)
            date_picker_elements = discover_date_picker_elements(page)
            date_picker_inspection = inspect_date_picker_navigation(page)
        else:
            date_picker_inspection = {}

        dom_report = discover_great_walk_dom(page)
        dom_report["desktop_root"] = desktop_root
        dom_report["desktop_dropdown_options"] = dropdown_options
        if date_picker_elements:
            dom_report["date_picker_elements"] = date_picker_elements
        if date_picker_inspection:
            dom_report.update(date_picker_inspection)

        assessment = assess_control_discovery(dom_report)
        summary = build_discovery_summary(
            dom_report,
            assessment,
            selection_metadata_confirmed=metadata_confirmed,
        )
        summary["desktop_root"] = desktop_root
        summary["desktop_dropdown_options"] = dropdown_options
        if date_picker_elements:
            summary["date_picker_elements"] = date_picker_elements
        if date_picker_inspection:
            summary["date_picker_popup"] = date_picker_inspection.get("date_picker_popup")
            summary["date_picker_navigation"] = date_picker_inspection.get(
                "date_picker_navigation"
            )

        if pause_seconds > 0:
            print(
                f"Browser will remain open for {pause_seconds}s for manual inspection "
                "(DevTools / visual review). Search and booking actions are disabled."
            )
            page.wait_for_timeout(pause_seconds * 1000)

        artifacts = save_dom_inspection_artifacts(
            page=page,
            track_name=track.name,
            track_slug=track.slug,
            dom_report=dom_report,
            discovery_summary=summary,
            network_timeline=recorder.timeline_dicts(),
            prefix="inspect",
        )

        return DomInspectionReport(
            track_slug=track.slug,
            track_name=track.name,
            selection_metadata_confirmed=metadata_confirmed,
            desktop_root=desktop_root,
            discovery_complete=assessment.complete,
            diagnostic_path=str(artifacts.directory),
            discovery_summary=summary,
            artifacts=artifacts,
        )
    finally:
        session.close()
