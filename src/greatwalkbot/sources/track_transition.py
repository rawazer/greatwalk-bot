"""Bounded desktop track selection transitions for shared Playwright sessions."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from greatwalkbot.infra.errors import (
    TrackSelectionNotCommittedError,
    TrackSelectorError,
)
from greatwalkbot.models import Track
from greatwalkbot.sources.gw_desktop_form import (
    desktop_track_option_id,
    read_desktop_form_state,
    refresh_desktop_root_binding,
    resolve_desktop_great_walk_root,
    select_desktop_track,
)
from greatwalkbot.sources.network_recorder import NetworkRecorder
from greatwalkbot.sources.spa_navigation import SpaPage, open_great_walk_view

logger = logging.getLogger(__name__)

TransitionOutcome = Literal["already_matched", "changed_and_verified", "failed"]
TransitionFailureStage = Literal[
    "pre_transition",
    "dropdown_open",
    "option_click",
    "wait_for_commit",
    "visible_verification",
    "post_recovery",
]

_POST_SEARCH_ACTIVITY_JS = """() => {
    const root = Array.from(document.querySelectorAll('div[role="search"]'))
        .find(el => (el.className || '').toString().includes('themeTopsearch')
            && el.getBoundingClientRect().width > 0);
    if (!root) return { loading_present: false, results_visible: false };
    const LOADING = ['fetching content', 'loading', 'please wait'];
    const loading = LOADING.some(m => (root.textContent || '').toLowerCase().includes(m));
    const selectors = [
        '[id*="great-walk"][id*="result"]',
        '[id*="great-walk"][id*="grid"]',
        '.great-walk-results',
        '[class*="greatwalk"][class*="result"]',
    ];
    let resultsVisible = false;
    for (const sel of selectors) {
        const el = root.querySelector(sel);
        if (el && el.offsetParent && (el.textContent || '').trim().length > 0) {
            resultsVisible = true;
            break;
        }
    }
    return { loading_present: loading, results_visible: resultsVisible };
}"""


@dataclass
class TrackTransitionLifecycle:
    requested_track_slug: str
    requested_track_name: str
    prior_visible_track: str | None = None
    prior_track_slug: str | None = None
    outcome: TransitionOutcome | None = None
    failure_stage: TransitionFailureStage | None = None
    attempt: int = 1
    session_restarted: bool = False
    root_re_resolved: bool = False
    dropdown_opened: bool = False
    option_clicked: bool = False
    backend_metadata_confirmed: bool = False
    visible_trigger_matches: bool = False
    recovery_attempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_track_slug": self.requested_track_slug,
            "requested_track_name": self.requested_track_name,
            "prior_visible_track": self.prior_visible_track,
            "prior_track_slug": self.prior_track_slug,
            "outcome": self.outcome,
            "failure_stage": self.failure_stage,
            "attempt": self.attempt,
            "session_restarted": self.session_restarted,
            "root_re_resolved": self.root_re_resolved,
            "dropdown_opened": self.dropdown_opened,
            "option_clicked": self.option_clicked,
            "backend_metadata_confirmed": self.backend_metadata_confirmed,
            "visible_trigger_matches": self.visible_trigger_matches,
            "recovery_attempted": self.recovery_attempted,
        }


@dataclass
class TrackTransitionDiagnostics:
    lifecycle: TrackTransitionLifecycle
    pre_transition: dict[str, Any] = field(default_factory=dict)
    during_selection: dict[str, Any] = field(default_factory=dict)
    post_selection: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transition_lifecycle": self.lifecycle.to_dict(),
            "pre_transition": self.pre_transition,
            "during_selection": self.during_selection,
            "post_selection": self.post_selection,
        }


def _bounded_track_control(track_ctrl: dict[str, Any] | None) -> dict[str, Any]:
    if not track_ctrl:
        return {}
    return {
        "visible_text": (track_ctrl.get("visible_text") or "")[:120] or None,
        "aria_expanded": track_ctrl.get("aria_expanded"),
        "enabled": track_ctrl.get("enabled"),
        "matches_requested": track_ctrl.get("matches_requested"),
    }


def _bounded_root_metadata(state: dict[str, Any]) -> dict[str, Any]:
    root = state.get("desktop_root") or {}
    return {
        "selector": root.get("selector"),
        "id": root.get("id"),
        "class": (root.get("class") or "")[:120] or None,
        "desktop_root_count": state.get("desktop_root_count"),
    }


def capture_pre_transition_snapshot(
    page: SpaPage,
    track: Track,
    *,
    prior_track_slug: str | None = None,
) -> tuple[dict[str, Any], Any]:
    binding = resolve_desktop_great_walk_root(page)
    state = read_desktop_form_state(page, binding, track_name=track.name)
    activity = page.evaluate(_POST_SEARCH_ACTIVITY_JS)
    if not isinstance(activity, dict):
        activity = {}
    snapshot = {
        "visible_track_label": _bounded_track_control(state.get("track_control")).get(
            "visible_text"
        ),
        "track_control": _bounded_track_control(state.get("track_control")),
        "desktop_root": _bounded_root_metadata(state),
        "loading_present": bool(state.get("loading_present")),
        "post_search_activity": {
            "loading_present": bool(activity.get("loading_present")),
            "results_visible": bool(activity.get("results_visible")),
        },
        "prior_track_slug": prior_track_slug,
    }
    return snapshot, binding


def wait_for_inter_track_quiescence(
    page: SpaPage,
    *,
    timeout_ms: int,
) -> dict[str, Any]:
    """Wait for post-search loading/results to stop blocking the desktop widget."""
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    last_activity: dict[str, Any] = {}
    while time.monotonic() < deadline:
        activity = page.evaluate(_POST_SEARCH_ACTIVITY_JS)
        if not isinstance(activity, dict):
            activity = {}
        last_activity = activity
        binding = resolve_desktop_great_walk_root(page)
        state = read_desktop_form_state(page, binding)
        if not state.get("loading_present") and not activity.get("loading_present"):
            track_ctrl = state.get("track_control") or {}
            if track_ctrl.get("enabled", True):
                return {
                    "settled": True,
                    "loading_present": False,
                    "results_visible": bool(activity.get("results_visible")),
                }
        page.wait_for_timeout(100)
    return {
        "settled": False,
        "loading_present": bool(last_activity.get("loading_present")),
        "results_visible": bool(last_activity.get("results_visible")),
    }


def _visible_track_matches(page: SpaPage, track: Track, binding: Any) -> bool:
    state = read_desktop_form_state(page, binding, track_name=track.name)
    return bool(state.get("track_control", {}).get("matches_requested"))


def _track_option_metadata(page: SpaPage, track: Track) -> dict[str, Any]:
    option_id = desktop_track_option_id(track)
    meta = page.evaluate(
        """({ optionId }) => {
            const root = Array.from(document.querySelectorAll('div[role="search"]'))
                .find(el => (el.className || '').toString().includes('themeTopsearch')
                    && el.getBoundingClientRect().width > 0);
            if (!root) return { found: false };
            const list = root.querySelector('#great-walk-dropdown-box');
            if (!list) return { found: false, list_present: false };
            const el = list.querySelector('#' + optionId);
            if (!el) return { found: false, list_present: true, option_id: optionId };
            return {
                found: true,
                option_id: optionId,
                text: (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 80),
                aria_selected: el.getAttribute('aria-selected'),
                visible: el.getBoundingClientRect().width > 0,
            };
        }""",
        {"optionId": option_id},
    )
    return meta if isinstance(meta, dict) else {"found": False}


def _dropdown_open_state(page: SpaPage) -> dict[str, Any]:
    return page.evaluate(
        """() => {
            const root = Array.from(document.querySelectorAll('div[role="search"]'))
                .find(el => (el.className || '').toString().includes('themeTopsearch')
                    && el.getBoundingClientRect().width > 0);
            if (!root) return { open: false };
            const btn = root.querySelector('#great-walk-dropdown-button');
            const list = root.querySelector('#great-walk-dropdown-box');
            return {
                open: btn && btn.getAttribute('aria-expanded') === 'true',
                aria_expanded: btn ? btn.getAttribute('aria-expanded') : null,
                list_visible: !!(list && list.getBoundingClientRect().width > 0),
            };
        }"""
    ) or {}


def wait_for_track_transition_committed(
    page: SpaPage,
    track: Track,
    recorder: NetworkRecorder,
    binding: Any,
    *,
    timeout_ms: int,
) -> tuple[bool, bool, bool]:
    """Wait until visible trigger matches; return (visible, metadata, settled)."""
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    visible = False
    metadata = False
    while time.monotonic() < deadline:
        visible = _visible_track_matches(page, track, binding)
        metadata = recorder.saw_selection_metadata(track.place_id)
        if visible and metadata:
            return True, True, True
        if visible and not metadata:
            # Visible label is authoritative once settled; metadata may lag.
            return True, metadata, True
        if metadata and not visible:
            # Backend moved but trigger stale — keep waiting for UI to settle.
            binding, _ = refresh_desktop_root_binding(page, binding)
            visible = _visible_track_matches(page, track, binding)
            if visible:
                return True, True, True
        page.wait_for_timeout(100)
    visible = _visible_track_matches(page, track, binding)
    metadata = recorder.saw_selection_metadata(track.place_id)
    return visible, metadata, visible


def transition_track_selection(
    page: SpaPage,
    track: Track,
    recorder: NetworkRecorder,
    *,
    navigation_timeout_ms: int,
    app_ready_timeout_ms: int,
    selection_commit_timeout_ms: int,
    prior_track_slug: str | None = None,
    attempt: int = 1,
    session_restarted: bool = False,
    inter_track_quiescence_ms: int = 5_000,
) -> TrackTransitionDiagnostics:
    """Select and verify the requested track on the live desktop widget."""
    lifecycle = TrackTransitionLifecycle(
        requested_track_slug=track.slug,
        requested_track_name=track.name,
        prior_track_slug=prior_track_slug,
        attempt=attempt,
        session_restarted=session_restarted,
    )
    diagnostics = TrackTransitionDiagnostics(lifecycle=lifecycle)

    if prior_track_slug is not None:
        diagnostics.pre_transition["quiescence"] = wait_for_inter_track_quiescence(
            page,
            timeout_ms=inter_track_quiescence_ms,
        )

    pre_snapshot, binding = capture_pre_transition_snapshot(
        page,
        track,
        prior_track_slug=prior_track_slug,
    )
    diagnostics.pre_transition.update(pre_snapshot)
    lifecycle.prior_visible_track = pre_snapshot.get("visible_track_label")

    if pre_snapshot.get("track_control", {}).get("matches_requested"):
        lifecycle.outcome = "already_matched"
        lifecycle.visible_trigger_matches = True
        lifecycle.backend_metadata_confirmed = recorder.saw_selection_metadata(track.place_id)
        diagnostics.post_selection["visible_track_label"] = pre_snapshot.get(
            "visible_track_label"
        )
        return diagnostics

    for recovery in range(2):
        if recovery == 1:
            lifecycle.recovery_attempted = True
            lifecycle.failure_stage = "post_recovery"
            logger.warning(
                "Track transition stale for %s; re-applying Great Walk route",
                track.slug,
            )
            open_great_walk_view(
                page,
                navigation_timeout_ms=navigation_timeout_ms,
                app_ready_timeout_ms=app_ready_timeout_ms,
                recorder=recorder,
            )
            binding = resolve_desktop_great_walk_root(page)
            lifecycle.root_re_resolved = True

        try:
            option_meta = _track_option_metadata(page, track)
            diagnostics.during_selection["target_option"] = option_meta
            if not option_meta.get("found"):
                lifecycle.failure_stage = "option_click"
                if recovery == 0:
                    continue
                raise TrackSelectorError(
                    f"Desktop track option not found for {track.name!r}",
                    track_slug=track.slug,
                    element_id=desktop_track_option_id(track),
                )

            dropdown_before = _dropdown_open_state(page)
            diagnostics.during_selection["dropdown_before"] = dropdown_before
            select_desktop_track(page, track, binding)
            lifecycle.dropdown_opened = True
            lifecycle.option_clicked = True
            diagnostics.during_selection["dropdown_after_click"] = _dropdown_open_state(
                page
            )

            binding, root_change = refresh_desktop_root_binding(page, binding)
            lifecycle.root_re_resolved = True
            diagnostics.during_selection["root_change"] = root_change

            visible, metadata, settled = wait_for_track_transition_committed(
                page,
                track,
                recorder,
                binding,
                timeout_ms=selection_commit_timeout_ms,
            )
            lifecycle.backend_metadata_confirmed = metadata
            lifecycle.visible_trigger_matches = visible

            post_state = read_desktop_form_state(page, binding, track_name=track.name)
            diagnostics.post_selection = {
                "visible_track_label": _bounded_track_control(
                    post_state.get("track_control")
                ).get("visible_text"),
                "track_control": _bounded_track_control(post_state.get("track_control")),
                "desktop_root": _bounded_root_metadata(post_state),
                "root_change": root_change,
            }

            if visible:
                lifecycle.outcome = "changed_and_verified"
                return diagnostics

            lifecycle.failure_stage = "visible_verification"
            if metadata and not visible and recovery == 0:
                continue
        except TrackSelectorError:
            if recovery == 0:
                lifecycle.failure_stage = "dropdown_open"
                continue
            raise

    lifecycle.outcome = "failed"
    if lifecycle.failure_stage is None:
        lifecycle.failure_stage = "wait_for_commit"
    raise TrackSelectionNotCommittedError(
        f"Track {track.name!r} transition did not commit: "
        f"visible_trigger_matches={lifecycle.visible_trigger_matches}, "
        f"backend_metadata_confirmed={lifecycle.backend_metadata_confirmed}",
        place_id=track.place_id,
        transition_diagnostics=diagnostics.to_dict(),
        failure_stage=lifecycle.failure_stage,
        requested_track_slug=track.slug,
        prior_track_slug=prior_track_slug,
        attempt=attempt,
        session_restarted=session_restarted,
    )
