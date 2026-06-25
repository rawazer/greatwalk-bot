"""Great Walk search form state capture and semantic submission."""

from __future__ import annotations

import time
from datetime import date
from typing import Any, Protocol

from greatwalkbot.infra.errors import SearchFormValidationError, UIReadinessError
from greatwalkbot.models import Track
from greatwalkbot.sources.gw_form_controls import (
    capture_form_control_state,
    set_nights,
    set_start_date,
    wait_for_form_values,
)
from greatwalkbot.sources.network_recorder import NetworkRecorder

_RESULTS_VISIBLE_JS = """() => {
    const selectors = [
        '[id*="great-walk"][id*="result"]',
        '[id*="great-walk"][id*="grid"]',
        '.great-walk-results',
        '[class*="greatwalk"][class*="result"]',
    ];
    for (const sel of selectors) {
        const el = document.querySelector(sel);
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
) -> dict[str, Any]:
    """Return sanitized semantic control state for Great Walk search fields."""
    state = capture_form_control_state(
        page,
        track_name=track.name if track else None,
        start_date=start_date,
        nights=nights,
    )
    return {
        key: value
        for key, value in state.items()
        if key != "validation_messages"
    } | {
        "validation_messages": list(state.get("validation_messages") or [])[:5],
    }


def _raise_if_not_actionable(state: dict[str, Any], *, phase: str) -> None:
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
) -> dict[str, Any]:
    """Fill and verify search form values using Playwright control interactions."""
    state = capture_search_form_state(
        page,
        track=track,
        start_date=start_date,
        nights=nights,
    )
    _raise_if_not_actionable(state, phase="before search")

    set_start_date(page, start_date)
    set_nights(page, nights)

    state = wait_for_form_values(
        page,
        track_name=track.name,
        start_date=start_date,
        nights=nights,
    )
    if not state.get("start_date_control", {}).get("matches_requested"):
        raise SearchFormValidationError(
            f"Start date not reflected in control "
            f"(expected {start_date.isoformat()})",
            form_state=state,
        )
    if not state.get("nights_control", {}).get("matches_requested"):
        raise SearchFormValidationError(
            f"Nights not reflected in select value (expected {nights})",
            form_state=state,
        )

    _raise_if_not_actionable(state, phase="after setting form values")
    return state


def click_great_walk_search_button(page: SpaPage) -> None:
    clicked = page.evaluate(
        """() => {
            const ids = [
                'great-walk-search-button',
                'great-walk-search',
                'btn-great-walk-search',
            ];
            for (const id of ids) {
                const btn = document.getElementById(id);
                if (btn && btn.offsetParent && !btn.disabled) {
                    btn.click();
                    return true;
                }
            }
            const btn = Array.from(document.querySelectorAll('button')).find(
                b => /^search$/i.test((b.textContent || '').trim()) && b.offsetParent && !b.disabled
            );
            if (btn) {
                btn.click();
                return true;
            }
            return false;
        }"""
    )
    if not clicked:
        raise UIReadinessError("Could not click an enabled Great Walk Search button")


def wait_for_search_click_transition(
    page: SpaPage,
    recorder: NetworkRecorder,
    *,
    timeout_ms: int,
    track: Track | None = None,
) -> str | None:
    """Wait for an observable post-click transition (not a fixed sleep)."""
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        if recorder.saw_post_search_activity():
            return "network"
        state = capture_search_form_state(page, track=track)
        if state.get("loading_overlay_present"):
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
) -> dict[str, Any]:
    """Prepare form, click Search, and verify an observable transition began."""
    form_state = prepare_search_form(
        page,
        track,
        start_date=start_date,
        nights=nights,
    )
    recorder.mark_search_submitted()
    click_great_walk_search_button(page)
    transition = wait_for_search_click_transition(
        page,
        recorder,
        timeout_ms=transition_timeout_ms,
        track=track,
    )
    return {
        **form_state,
        "search_click_transition": transition,
    }
