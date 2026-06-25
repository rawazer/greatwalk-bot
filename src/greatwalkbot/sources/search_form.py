"""Great Walk search form state capture and semantic submission."""

from __future__ import annotations

import time
from datetime import date
from typing import Any, Protocol

from greatwalkbot.infra.errors import SearchFormValidationError, UIReadinessError
from greatwalkbot.models import Track
from greatwalkbot.sources.network_recorder import NetworkRecorder

_READ_FORM_STATE_JS = """() => {
    const dropdown = document.getElementById('great-walk-dropdown-button')
        || document.getElementById('great-walk-mobile-dropdown-button');
    const startDate = document.getElementById('great-walk-start-date');
    const nights = document.getElementById('great-walk-nights')
        || document.getElementById('great-walk-number-of-nights')
        || document.querySelector('[id*="great-walk"][id*="night"]');

    const searchIds = [
        'great-walk-search-button',
        'great-walk-search',
        'btn-great-walk-search',
    ];
    let searchBtn = null;
    let searchSelector = null;
    for (const id of searchIds) {
        const el = document.getElementById(id);
        if (el) {
            searchBtn = el;
            searchSelector = '#' + id;
            break;
        }
    }
    if (!searchBtn) {
        searchBtn = Array.from(document.querySelectorAll('button')).find(
            b => /^search$/i.test((b.textContent || '').trim()) && b.offsetParent
        );
        if (searchBtn) searchSelector = 'button:visible(text=Search)';
    }

    const validation = [];
    const gwRoot = document.querySelector('[id*="great-walk"]')?.closest('form, section, div');
    const scope = gwRoot || document;
    scope.querySelectorAll(
        '[class*="error"], [class*="validation"], .invalid-feedback, [role="alert"]'
    ).forEach(el => {
        const text = (el.textContent || '').trim();
        if (text && el.offsetParent !== null) validation.push(text.slice(0, 200));
    });

    const overlay = document.querySelector(
        '.loading-overlay, [class*="loading-overlay"], #loading, .gw-loading, [class*="spinner"]'
    );

    const startValue = startDate
        ? (startDate.getAttribute('data-date')
            || startDate.getAttribute('value')
            || (startDate.textContent || '').trim()).slice(0, 40)
        : null;
    const nightsValue = nights
        ? String(nights.value || (nights.textContent || '').trim()).slice(0, 20)
        : null;

    return {
        selected_track_label: dropdown
            ? (dropdown.textContent || '').trim().slice(0, 120)
            : null,
        start_date_value: startValue,
        nights_value: nightsValue,
        search_button_selector: searchSelector,
        search_button_text: searchBtn ? (searchBtn.textContent || '').trim().slice(0, 40) : null,
        search_button_enabled: searchBtn
            ? !(
                searchBtn.disabled
                || searchBtn.getAttribute('aria-disabled') === 'true'
                || searchBtn.classList.contains('disabled')
            )
            : false,
        search_button_visible: !!(searchBtn && searchBtn.offsetParent),
        validation_messages: validation.slice(0, 5),
        loading_overlay_present: !!(overlay && overlay.offsetParent),
    };
}"""

_SET_FORM_VALUES_JS = """({ startDate, nights }) => {
    const result = { start_date_set: false, nights_set: false };

    const startBtn = document.getElementById('great-walk-start-date');
    if (startBtn) {
        startBtn.click();
        const cell = document.querySelector('[data-date="' + startDate + '"]')
            || document.querySelector('td[data-date="' + startDate + '"]')
            || document.querySelector('[data-value="' + startDate + '"]');
        if (cell) {
            cell.click();
            result.start_date_set = true;
            result.start_date_method = 'calendar';
        } else {
            startBtn.setAttribute('data-date', startDate);
            const hidden = document.querySelector(
                'input[id*="great-walk"][id*="date"], input[name*="startDate"], input[name*="arrival"]'
            );
            if (hidden) {
                hidden.value = startDate;
                hidden.dispatchEvent(new Event('input', { bubbles: true }));
                hidden.dispatchEvent(new Event('change', { bubbles: true }));
            }
            startBtn.dispatchEvent(new Event('change', { bubbles: true }));
            result.start_date_set = true;
            result.start_date_method = 'attribute';
        }
    }

    const nightsEl = document.getElementById('great-walk-nights')
        || document.getElementById('great-walk-number-of-nights')
        || document.querySelector('select[id*="great-walk"][id*="night"], input[id*="great-walk"][id*="night"]');
    if (nightsEl) {
        const nightsStr = String(nights);
        if (nightsEl.tagName === 'SELECT' || nightsEl.tagName === 'INPUT') {
            nightsEl.value = nightsStr;
            nightsEl.dispatchEvent(new Event('input', { bubbles: true }));
            nightsEl.dispatchEvent(new Event('change', { bubbles: true }));
            result.nights_set = true;
        } else {
            const opt = document.getElementById('great-walk-nights-' + nights)
                || document.querySelector('[data-nights="' + nights + '"]');
            if (opt) {
                opt.click();
                result.nights_set = true;
            }
        }
    } else {
        result.nights_set = true;
        result.nights_skipped = true;
    }

    return result;
}"""

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
    def evaluate(self, expression: str, arg: Any = None) -> Any: ...

    def wait_for_timeout(self, timeout: int) -> None: ...


def capture_search_form_state(page: SpaPage) -> dict[str, Any]:
    """Return a sanitized summary of Great Walk search controls."""
    state = page.evaluate(_READ_FORM_STATE_JS)
    if not isinstance(state, dict):
        return {}
    return {
        key: value
        for key, value in state.items()
        if key != "validation_messages"
    } | {
        "validation_messages": list(state.get("validation_messages") or [])[:5],
    }


def _form_values_match(
    state: dict[str, Any],
    *,
    start_date: date,
    nights: int,
) -> bool:
    iso = start_date.isoformat()
    start_value = str(state.get("start_date_value") or "")
    if iso not in start_value and start_value != iso:
        return False
    nights_value = str(state.get("nights_value") or "").strip()
    if nights_value and nights_value != str(nights):
        return False
    return True


def prepare_search_form(
    page: SpaPage,
    track: Track,
    *,
    start_date: date,
    nights: int,
) -> dict[str, Any]:
    """Fill and verify search form values; raise if Search is not actionable."""
    state = capture_search_form_state(page)
    if state.get("validation_messages"):
        raise SearchFormValidationError(
            "Validation messages present before search",
            form_state=state,
        )
    if state.get("search_button_visible") and not state.get("search_button_enabled"):
        raise SearchFormValidationError(
            "Great Walk Search button is visible but disabled",
            form_state=state,
        )

    page.evaluate(
        _SET_FORM_VALUES_JS,
        {"startDate": start_date.isoformat(), "nights": nights},
    )
    page.wait_for_timeout(150)

    state = capture_search_form_state(page)
    if not _form_values_match(state, start_date=start_date, nights=nights):
        raise SearchFormValidationError(
            f"Search form values not reflected in DOM "
            f"(expected start={start_date.isoformat()}, nights={nights})",
            form_state=state,
        )
    if state.get("validation_messages"):
        raise SearchFormValidationError(
            "Validation messages after setting search form",
            form_state=state,
        )
    if state.get("search_button_visible") and not state.get("search_button_enabled"):
        raise SearchFormValidationError(
            "Great Walk Search button disabled after setting form values",
            form_state=state,
        )
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
) -> str | None:
    """Wait for an observable post-click transition (not a fixed sleep)."""
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        if recorder.saw_post_search_activity():
            return "network"
        state = capture_search_form_state(page)
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
    )
    return {
        **form_state,
        "search_click_transition": transition,
    }
