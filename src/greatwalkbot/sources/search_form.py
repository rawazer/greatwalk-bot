"""Great Walk search form state capture and semantic submission."""

from __future__ import annotations

import time
from datetime import date
from typing import Any, Protocol

from greatwalkbot.infra.errors import (
    GreatWalkFormNotReadyError,
    SearchFormValidationError,
    UIReadinessError,
)
from greatwalkbot.models import Track
from greatwalkbot.sources.gw_desktop_form import (
    click_desktop_search_button,
    prepare_desktop_search_form,
    read_desktop_form_state,
    resolve_desktop_great_walk_root,
)
from greatwalkbot.sources.network_recorder import NetworkRecorder
from greatwalkbot.sources.spa_timing import DEFAULT_FORM_READY_TIMEOUT_MS

_RESULTS_VISIBLE_JS = """() => {
    const root = Array.from(document.querySelectorAll('div[role="search"]'))
        .find(el => (el.className || '').toString().includes('themeTopsearch')
            && el.getBoundingClientRect().width > 0) || document;
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
    people_size: int | None = None,
    binding: Any | None = None,
) -> dict[str, Any]:
    """Return sanitized semantic control state scoped to the desktop widget root."""
    desktop_binding = binding or resolve_desktop_great_walk_root(page)
    state = read_desktop_form_state(
        page,
        desktop_binding,
        track_name=track.name if track else None,
        start_date=start_date,
        nights=nights,
        people_size=people_size,
    )
    return {
        key: value
        for key, value in state.items()
        if key not in ("validation_messages",)
    } | {
        "validation_messages": list(state.get("validation_messages") or [])[:5],
    }


def _raise_if_not_actionable(state: dict[str, Any], *, phase: str) -> None:
    if state.get("loading_present"):
        raise GreatWalkFormNotReadyError(
            f"Desktop Great Walk widget still loading {phase}",
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
    people_size: int,
    form_ready_timeout_ms: int = DEFAULT_FORM_READY_TIMEOUT_MS,
) -> dict[str, Any]:
    """Fill desktop controls and verify visible values before Search."""
    del form_ready_timeout_ms  # desktop binding is explicit; no root-scoring wait
    return prepare_desktop_search_form(
        page,
        track,
        start_date=start_date,
        nights=nights,
        people_size=people_size,
    )


def click_great_walk_search_button(page: SpaPage) -> None:
    click_desktop_search_button(page)


def wait_for_search_click_transition(
    page: SpaPage,
    recorder: NetworkRecorder,
    *,
    timeout_ms: int,
    track: Track | None = None,
    binding: Any | None = None,
) -> str | None:
    """Wait for an observable post-click transition (not a fixed sleep)."""
    desktop_binding = binding or resolve_desktop_great_walk_root(page)
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        if recorder.saw_post_search_activity():
            return "network"
        state = capture_search_form_state(
            page,
            track=track,
            binding=desktop_binding,
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
    people_size: int,
    transition_timeout_ms: int = 3_000,
    form_ready_timeout_ms: int = DEFAULT_FORM_READY_TIMEOUT_MS,
) -> dict[str, Any]:
    """Prepare desktop form, click Search, and verify an observable transition began."""
    binding = resolve_desktop_great_walk_root(page)
    form_state = prepare_search_form(
        page,
        track,
        start_date=start_date,
        nights=nights,
        people_size=people_size,
        form_ready_timeout_ms=form_ready_timeout_ms,
    )
    recorder.mark_search_submitted()
    click_great_walk_search_button(page)
    transition = wait_for_search_click_transition(
        page,
        recorder,
        timeout_ms=transition_timeout_ms,
        track=track,
        binding=binding,
    )
    return {
        **form_state,
        "search_click_transition": transition,
    }
