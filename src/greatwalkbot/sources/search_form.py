"""Great Walk search form state capture and semantic submission."""

from __future__ import annotations

import time
from datetime import date
from typing import Any, Protocol

from greatwalkbot.infra.errors import (
    GreatWalkControlNotFoundError,
    GreatWalkFormNotReadyError,
    SearchFormValidationError,
    UIReadinessError,
)
from greatwalkbot.models import Track
from greatwalkbot.sources.gw_active_form import (
    _require_controls,
    click_active_search_button,
    inventory_active_form,
    read_active_form_state,
    resolve_active_great_walk_form,
    set_active_nights,
    set_active_start_date,
    wait_for_active_form_ready,
    wait_for_active_form_values,
)
from greatwalkbot.sources.network_recorder import NetworkRecorder
from greatwalkbot.sources.spa_timing import DEFAULT_FORM_READY_TIMEOUT_MS

_RESULTS_VISIBLE_JS = """() => {
    const root = document.querySelector('[data-gwbot-active-root="1"]') || document;
    const selectors = [
        '[id*="great-walk"][id*="result"]',
        '[id*="great-walk"][id*="grid"]',
        '.great-walk-results',
        '[class*="greatwalk"][class*="result"]',
    ];
    for (const sel of selectors) {
        const el = root.querySelector(sel);
        if (el && el.offsetParent && (el.textContent || '').trim().length > 0) {
            return true;
        }
    }
    return false;
}"""


class SpaPage(Protocol):
    def locator(self, selector: str) -> Any: ...

    def evaluate(self, expression: str, arg: Any = None) -> Any: ...

    def wait_for_timeout(self, timeout: int) -> None: ...


def capture_search_form_state(
    page: SpaPage,
    *,
    track: Track | None = None,
    start_date: date | None = None,
    nights: int | None = None,
    resolution: Any | None = None,
) -> dict[str, Any]:
    """Return sanitized semantic control state scoped to the active form root."""
    active_resolution = resolution or resolve_active_great_walk_form(page)
    state = read_active_form_state(
        page,
        active_resolution,
        track_name=track.name if track else None,
        start_date=start_date,
        nights=nights,
    )
    inventory = inventory_active_form(page)
    return {
        key: value
        for key, value in state.items()
        if key not in ("validation_messages",)
    } | {
        "validation_messages": list(state.get("validation_messages") or [])[:5],
        "active_form_inventory": inventory,
    }


def _raise_if_not_actionable(state: dict[str, Any], *, phase: str) -> None:
    if state.get("loading_present"):
        raise GreatWalkFormNotReadyError(
            f"Active Great Walk form still loading {phase}",
            form_state=state,
        )
    if state.get("validation_messages"):
        raise SearchFormValidationError(
            f"Validation messages present {phase}",
            form_state=state,
        )
    if state.get("search_button_visible") and not state.get("search_button_enabled"):
        raise SearchFormValidationError(
            f"Great Walk Search button is visible but disabled {phase}",
            form_state=state,
        )


def prepare_search_form(
    page: SpaPage,
    track: Track,
    *,
    start_date: date,
    nights: int,
    form_ready_timeout_ms: int = DEFAULT_FORM_READY_TIMEOUT_MS,
) -> dict[str, Any]:
    """Wait for active form, fill controls, and verify semantic values."""
    resolution, ready_state = wait_for_active_form_ready(
        page,
        timeout_ms=form_ready_timeout_ms,
    )
    _require_controls(ready_state, resolution)

    state = capture_search_form_state(
        page,
        track=track,
        start_date=start_date,
        nights=nights,
        resolution=resolution,
    )
    _raise_if_not_actionable(state, phase="before search")

    try:
        set_active_start_date(page, start_date)
        set_active_nights(page, nights)
    except GreatWalkControlNotFoundError as exc:
        raise GreatWalkControlNotFoundError(
            str(exc),
            control=exc.control,
            form_state=capture_search_form_state(
                page, track=track, start_date=start_date, nights=nights, resolution=resolution
            ),
        ) from exc

    state = wait_for_active_form_values(
        page,
        resolution,
        track_name=track.name,
        start_date=start_date,
        nights=nights,
    )
    state["active_form_inventory"] = inventory_active_form(page)

    if not state.get("start_date_control", {}).get("matches_requested"):
        raise SearchFormValidationError(
            f"Start date not reflected in active form control "
            f"(expected {start_date.isoformat()})",
            form_state=state,
        )
    if not state.get("nights_control", {}).get("matches_requested"):
        raise SearchFormValidationError(
            f"Nights not reflected in active form select value (expected {nights})",
            form_state=state,
        )

    _raise_if_not_actionable(state, phase="after setting form values")
    return state


def click_great_walk_search_button(page: SpaPage) -> None:
    if not click_active_search_button(page):
        raise UIReadinessError(
            "Could not click an enabled Great Walk Search button in active form root"
        )


def wait_for_search_click_transition(
    page: SpaPage,
    recorder: NetworkRecorder,
    *,
    timeout_ms: int,
    track: Track | None = None,
    resolution: Any | None = None,
) -> str | None:
    """Wait for an observable post-click transition (not a fixed sleep)."""
    active_resolution = resolution or resolve_active_great_walk_form(page)
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        if recorder.saw_post_search_activity():
            return "network"
        state = capture_search_form_state(
            page,
            track=track,
            resolution=active_resolution,
        )
        if state.get("loading_present"):
            return "loading"
        if state.get("validation_messages"):
            raise SearchFormValidationError(
                "Validation message appeared after Search click",
                form_state=state,
            )
        if page.evaluate(_RESULTS_VISIBLE_JS):
            return "results"
        page.wait_for_timeout(100)
    return None


def submit_great_walk_search(
    page: SpaPage,
    recorder: NetworkRecorder,
    track: Track,
    *,
    start_date: date,
    nights: int,
    transition_timeout_ms: int = 3_000,
    form_ready_timeout_ms: int = DEFAULT_FORM_READY_TIMEOUT_MS,
) -> dict[str, Any]:
    """Prepare active form, click Search, and verify an observable transition began."""
    resolution = resolve_active_great_walk_form(page)
    form_state = prepare_search_form(
        page,
        track,
        start_date=start_date,
        nights=nights,
        form_ready_timeout_ms=form_ready_timeout_ms,
    )
    recorder.mark_search_submitted()
    click_great_walk_search_button(page)
    transition = wait_for_search_click_transition(
        page,
        recorder,
        timeout_ms=transition_timeout_ms,
        track=track,
        resolution=resolution,
    )
    return {
        **form_state,
        "search_click_transition": transition,
    }
