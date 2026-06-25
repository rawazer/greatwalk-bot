"""DOC Great Walk search form control selectors and semantic read/write."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol
import time

# Stable selectors observed on bookings.doc.govt.nz Great Walk SPA (June 2026).
TRACK_DROPDOWN_BUTTON_IDS: tuple[str, ...] = (
    "great-walk-dropdown-button",
    "great-walk-mobile-dropdown-button",
)
START_DATE_BUTTON_ID = "great-walk-start-date"
NIGHTS_SELECT_ID = "great-walk-nights"
SEARCH_BUTTON_IDS: tuple[str, ...] = (
    "great-walk-search-button",
    "great-walk-search",
    "btn-great-walk-search",
)

PLACEHOLDER_TRACK_LABELS = frozenset({"select great walk", "select a great walk"})

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_DMY_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})")


@dataclass(frozen=True)
class ControlState:
    selector: str
    control_type: str
    raw_value: str | None
    normalized_value: str | None
    selected_option_value: str | None = None
    selected_option_text: str | None = None
    visible_text: str | None = None
    matches_requested: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "selector": self.selector,
            "control_type": self.control_type,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "selected_option_value": self.selected_option_value,
            "selected_option_text": self.selected_option_text,
            "visible_text": self.visible_text,
            "matches_requested": self.matches_requested,
        }


class PlaywrightFormPage(Protocol):
    def locator(self, selector: str) -> Any: ...

    def evaluate(self, expression: str, arg: Any = None) -> Any: ...

    def wait_for_timeout(self, timeout: int) -> None: ...


def normalize_date_string(raw: str | None) -> str | None:
    """Normalize a control value to ISO date (YYYY-MM-DD)."""
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    iso_match = _ISO_DATE_RE.match(value)
    if iso_match:
        return value[:10]
    dmy_match = _DMY_DATE_RE.match(value)
    if dmy_match:
        day, month, year = dmy_match.groups()
        return date(int(year), int(month), int(day)).isoformat()
    if len(value) >= 10 and value[4] == "-" and value[7] == "-":
        return value[:10]
    return None


def _read_control_js() -> str:
    return """
    (requested) => {
        function readSelect(el, selector) {
            if (!el || el.tagName !== 'SELECT') return null;
            const opt = el.options[el.selectedIndex];
            return {
                selector,
                control_type: 'select',
                raw_value: el.value ?? null,
                normalized_value: el.value ?? null,
                selected_option_value: opt ? opt.value : null,
                selected_option_text: opt ? opt.text.trim() : null,
                visible_text: null,
            };
        }

        function readInput(el, selector) {
            if (!el || el.tagName !== 'INPUT') return null;
            return {
                selector,
                control_type: 'input',
                raw_value: el.value ?? null,
                normalized_value: el.value ?? null,
                selected_option_value: null,
                selected_option_text: null,
                visible_text: null,
            };
        }

        function readDateButton(el, selector) {
            if (!el) return null;
            const hidden = document.querySelector(
                'input#great-walk-start-date-input, input[name="startDate"], '
                + 'input[id*="great-walk"][id*="date"][type="hidden"], '
                + 'input[id*="great-walk-arrival"]'
            );
            const backingValue = hidden ? hidden.value : null;
            const dataDate = el.getAttribute('data-date');
            const raw = backingValue || dataDate || (el.tagName === 'INPUT' ? el.value : null);
            const visible = (el.textContent || '').trim().slice(0, 80) || null;
            return {
                selector,
                control_type: el.tagName === 'INPUT' ? 'input' : 'date-button',
                raw_value: raw,
                normalized_value: raw,
                selected_option_value: null,
                selected_option_text: null,
                visible_text: visible,
            };
        }

        const trackBtn = document.getElementById('great-walk-dropdown-button')
            || document.getElementById('great-walk-mobile-dropdown-button');
        const track = trackBtn ? {
            selector: '#' + trackBtn.id,
            control_type: 'dropdown-button',
            raw_value: null,
            normalized_value: null,
            selected_option_value: null,
            selected_option_text: null,
            visible_text: (trackBtn.textContent || '').trim().slice(0, 120) || null,
        } : null;

        const nightsEl = document.getElementById('great-walk-nights');
        const nights = nightsEl
            ? readSelect(nightsEl, '#great-walk-nights')
            : null;

        const startEl = document.getElementById('great-walk-start-date');
        const startDate = startEl
            ? readDateButton(startEl, '#great-walk-start-date')
            : null;

        let searchBtn = null;
        let searchSelector = null;
        for (const id of ['great-walk-search-button', 'great-walk-search', 'btn-great-walk-search']) {
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
            ) || null;
            if (searchBtn) searchSelector = 'button:visible(text=Search)';
        }

        const validation = [];
        const scope = document;
        scope.querySelectorAll(
            '[class*="error"], [class*="validation"], .invalid-feedback, [role="alert"]'
        ).forEach(el => {
            const text = (el.textContent || '').trim();
            if (text && el.offsetParent !== null) validation.push(text.slice(0, 200));
        });

        const overlay = document.querySelector(
            '.loading-overlay, [class*="loading-overlay"], #loading, .gw-loading, [class*="spinner"]'
        );

        return {
            track_control: track,
            start_date_control: startDate,
            nights_control: nights,
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
            requested,
        };
    }
    """


def _attach_match_flags(
    state: dict[str, Any],
    *,
    track_name: str | None = None,
    start_date: date | None = None,
    nights: int | None = None,
) -> dict[str, Any]:
    result = dict(state)
    track_ctrl = dict(state.get("track_control") or {})
    visible = (track_ctrl.get("visible_text") or "").strip()
    if track_name is not None:
        normalized_visible = visible.lower()
        track_ctrl["matches_requested"] = (
            bool(visible)
            and normalized_visible not in PLACEHOLDER_TRACK_LABELS
            and track_name.lower() in normalized_visible.lower()
        )
    result["track_control"] = track_ctrl

    start_ctrl = dict(state.get("start_date_control") or {})
    if start_date is not None:
        normalized = normalize_date_string(
            start_ctrl.get("raw_value") or start_ctrl.get("normalized_value")
        )
        if normalized:
            start_ctrl["normalized_value"] = normalized
        start_ctrl["matches_requested"] = normalized == start_date.isoformat()
    result["start_date_control"] = start_ctrl

    nights_ctrl = dict(state.get("nights_control") or {})
    if nights is not None and nights_ctrl:
        raw = str(nights_ctrl.get("raw_value") or "").strip()
        nights_ctrl["matches_requested"] = raw == str(nights)
    result["nights_control"] = nights_ctrl

    return result


def capture_form_control_state(
    page: PlaywrightFormPage,
    *,
    track_name: str | None = None,
    start_date: date | None = None,
    nights: int | None = None,
) -> dict[str, Any]:
    requested = {
        "track_name": track_name,
        "start_date": start_date.isoformat() if start_date else None,
        "nights": nights,
    }
    raw = page.evaluate(_read_control_js(), requested)
    if not isinstance(raw, dict):
        return {}
    return _attach_match_flags(raw, track_name=track_name, start_date=start_date, nights=nights)


def capture_selection_state(
    page: PlaywrightFormPage,
    track: Any,
    *,
    backend_metadata_confirmed: bool,
) -> dict[str, Any]:
    form_state = capture_form_control_state(page, track_name=track.name)
    track_ctrl = form_state.get("track_control") or {}
    visible_text = (track_ctrl.get("visible_text") or "").strip()
    visible_matches = bool(track_ctrl.get("matches_requested"))
    placeholder = visible_text.lower() in PLACEHOLDER_TRACK_LABELS if visible_text else True
    return {
        "backend_metadata_confirmed": backend_metadata_confirmed,
        "visible_track_label": visible_text or None,
        "visible_track_matches": visible_matches,
        "visible_selection_committed": visible_matches and not placeholder,
        "ui_state_inconsistent": backend_metadata_confirmed and not visible_matches,
    }


def set_start_date(page: PlaywrightFormPage, target: date) -> None:
    iso = target.isoformat()
    button = page.locator(f"#{START_DATE_BUTTON_ID}")
    if button.count() == 0:
        raise ValueError(f"Start date control #{START_DATE_BUTTON_ID} not found")

    button.first.click()
    page.wait_for_timeout(200)

    calendar_cell = page.locator(f'[data-date="{iso}"]')
    if calendar_cell.count() > 0:
        calendar_cell.first.click()
        page.wait_for_timeout(150)
        return

    hidden = page.locator(
        "input#great-walk-start-date-input, "
        "input[name='startDate'], "
        "input[id*='great-walk'][id*='date'][type='hidden']"
    )
    if hidden.count() > 0:
        field = hidden.first
        field.fill(iso)
        field.dispatch_event("input")
        field.dispatch_event("change")
        field.dispatch_event("blur")
        page.wait_for_timeout(150)
        return

    page.evaluate(
        """({ iso }) => {
            const btn = document.getElementById('great-walk-start-date');
            if (!btn) return false;
            btn.setAttribute('data-date', iso);
            const hidden = document.querySelector(
                'input#great-walk-start-date-input, input[name="startDate"], '
                + 'input[id*="great-walk"][id*="date"][type="hidden"]'
            );
            if (hidden) {
                hidden.value = iso;
                hidden.dispatchEvent(new Event('input', { bubbles: true }));
                hidden.dispatchEvent(new Event('change', { bubbles: true }));
                hidden.dispatchEvent(new Event('blur', { bubbles: true }));
            }
            btn.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }""",
        {"iso": iso},
    )
    page.wait_for_timeout(150)


def set_nights(page: PlaywrightFormPage, nights: int) -> None:
    select = page.locator(f"#{NIGHTS_SELECT_ID}")
    if select.count() == 0:
        raise ValueError(f"Nights control #{NIGHTS_SELECT_ID} not found")
    nights_str = str(nights)
    select.first.select_option(value=nights_str)
    select.first.dispatch_event("input")
    select.first.dispatch_event("change")
    select.first.dispatch_event("blur")
    page.wait_for_timeout(150)


def wait_for_form_values(
    page: PlaywrightFormPage,
    *,
    track_name: str,
    start_date: date,
    nights: int,
    timeout_ms: int = 5_000,
) -> dict[str, Any]:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    last_state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_state = capture_form_control_state(
            page,
            track_name=track_name,
            start_date=start_date,
            nights=nights,
        )
        if (
            last_state.get("start_date_control", {}).get("matches_requested")
            and last_state.get("nights_control", {}).get("matches_requested")
        ):
            return last_state
        page.wait_for_timeout(100)
    return last_state
