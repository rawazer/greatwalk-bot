"""Evidence-based control discovery gate for Great Walk automation."""

from __future__ import annotations

from typing import Any

from greatwalkbot.infra.errors import GreatWalkControlDiscoveryIncompleteError
from greatwalkbot.sources.diagnostics import DiagnosticArtifacts, save_dom_inspection_artifacts
from greatwalkbot.sources.gw_dom_discovery import (
    ControlDiscoveryAssessment,
    assess_control_discovery,
    build_discovery_summary,
    discover_great_walk_dom,
)


def run_control_discovery_gate(
    page: Any,
    *,
    track_name: str,
    track_slug: str,
    selection_metadata_confirmed: bool,
    network_timeline: list[dict[str, Any]] | None = None,
    prefix: str = "debug",
) -> tuple[dict[str, Any], ControlDiscoveryAssessment, DiagnosticArtifacts]:
    """Discover controls, save diagnostics, and require all required controls."""
    dom_report = discover_great_walk_dom(page)
    assessment = assess_control_discovery(dom_report)
    summary = build_discovery_summary(
        dom_report,
        assessment,
        selection_metadata_confirmed=selection_metadata_confirmed,
    )
    artifacts = save_dom_inspection_artifacts(
        page=page,
        track_name=track_name,
        track_slug=track_slug,
        dom_report=dom_report,
        discovery_summary=summary,
        network_timeline=network_timeline,
        prefix=prefix,
    )

    if not assessment.complete:
        raise GreatWalkControlDiscoveryIncompleteError(
            "Required Great Walk controls were not identified from live DOM evidence. "
            f"Review diagnostics at {artifacts.directory}",
            diagnostic_path=artifacts.directory,
            discovery_report=dom_report,
            assessment=assessment,
        )

    return dom_report, assessment, artifacts
