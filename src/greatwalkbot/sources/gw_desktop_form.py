"""Explicit desktop Great Walk search widget binding (Milestone 9.7)."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol

from greatwalkbot.infra.errors import (
    GreatWalkControlNotClickableError,
    GreatWalkControlNotFoundError,
    GreatWalkDateControlDiscoveryIncompleteError,
    GreatWalkDesktopRootError,
    SearchFormValidationError,
)
from greatwalkbot.models import Track
from greatwalkbot.sources.gw_active_form import normalize_date_string
from greatwalkbot.sources.spa_timing import DEFAULT_CONTROL_CLICKABLE_TIMEOUT_MS

DESKTOP_ROOT_SELECTOR = 'div[role="search"].themeTopsearch:visible'

TRACK_BUTTON_SELECTOR = "#great-walk-dropdown-button"
TRACK_LIST_SELECTOR = "#great-walk-dropdown-box"
DATE_BUTTON_SELECTOR = "#great-walk-start-date"
NIGHTS_BUTTON_SELECTOR = "#great-walk-night-dropdown-button"
NIGHTS_LIST_SELECTOR = "#great-walk-night-dropdown-box"
PEOPLE_BUTTON_SELECTOR = "#great-walk-people-dropdown-button"
PEOPLE_LIST_SELECTOR = "#great-walk-people-dropdown-box"
SEARCH_BUTTON_SELECTOR = 'button:has-text("Search")'

LOADING_TEXT_RE = re.compile(r"fetching content|loading\.{0,3}|please wait", re.IGNORECASE)

ControlActionOutcome = Literal["already_matched", "changed_and_verified", "change_failed"]

_COUNT_RE = re.compile(r"(\d+)")

_READ_DESKTOP_STATE_JS = """
() => {
    const LOADING = ['fetching content', 'loading', 'please wait'];
    const roots = Array.from(document.querySelectorAll('div[role="search"]'))
        .filter(el => {
            const cls = (el.className || '').toString();
            if (!cls.includes('themeTopsearch')) return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        });

    function readBtn(root, sel) {
        const el = root.querySelector(sel);
        if (!el) return {};
        const text = (el.textContent || '').replace(/\\s+/g, ' ').trim();
        return {
            selector: sel,
            visible_text: text.slice(0, 120) || null,
            data_date: el.getAttribute('data-date'),
            aria_label: el.getAttribute('aria-label'),
            aria_expanded: el.getAttribute('aria-expanded'),
            enabled: !el.disabled && el.getAttribute('aria-disabled') !== 'true',
        };
    }

    function readSearch(root) {
        const buttons = Array.from(root.querySelectorAll('button')).filter(b => {
            const style = window.getComputedStyle(b);
            return style.display !== 'none' && b.getBoundingClientRect().width > 0;
        });
        const btn = buttons.find(b => /^search$/i.test((b.textContent || '').trim()));
        return btn ? {
            selector: 'button:has-text("Search")',
            visible_text: (btn.textContent || '').trim(),
            enabled: !btn.disabled && btn.getAttribute('aria-disabled') !== 'true',
        } : {};
    }

    const root = roots.length === 1 ? roots[0] : null;
    if (!root) {
        return { desktop_root_count: roots.length, desktop_root: null };
    }

    const validation = [];
    root.querySelectorAll('[role="alert"], .invalid-feedback, .field-validation-error').forEach(el => {
        const text = (el.textContent || '').trim();
        if (!text) return;
        if (LOADING.some(m => text.toLowerCase().includes(m))) return;
        validation.push(text.slice(0, 200));
    });

    return {
        desktop_root_count: roots.length,
        desktop_root: {
            selector: 'div[role="search"].themeTopsearch:visible',
            id: root.id || null,
            class: (root.className || '').toString().slice(0, 120),
        },
        track_control: readBtn(root, '#great-walk-dropdown-button'),
        nights_control: readBtn(root, '#great-walk-night-dropdown-button'),
        people_control: readBtn(root, '#great-walk-people-dropdown-button'),
        start_date_control: readBtn(root, '#great-walk-start-date'),
        search_button: readSearch(root),
        validation_messages: validation.slice(0, 5),
        loading_present: LOADING.some(m => (root.textContent || '').toLowerCase().includes(m)),
    };
}
"""

_DISCOVER_DROPDOWN_OPTIONS_JS = """
() => {
    const root = Array.from(document.querySelectorAll('div[role="search"]'))
        .find(el => (el.className || '').toString().includes('themeTopsearch')
            && el.getBoundingClientRect().width > 0);
    if (!root) return { track_options: [], nights_options: [], people_options: [] };

    function collect(listSel) {
        const list = root.querySelector(listSel);
        if (!list) return [];
        const items = [];
        list.querySelectorAll('[id^="great-walk-"], [role="option"], li, button, a').forEach(el => {
            if (items.length >= 20) return;
            const style = window.getComputedStyle(el);
            const visible = style.display !== 'none' && el.getBoundingClientRect().width > 0;
            if (!visible) return;
            if (el.id && el.id.includes('-mobile')) return;
            items.push({
                id: el.id || null,
                tag: el.tagName,
                role: el.getAttribute('role'),
                text: (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 80) || null,
                aria_selected: el.getAttribute('aria-selected'),
            });
        });
        return items;
    }

    return {
        track_options: collect('#great-walk-dropdown-box'),
        nights_options: collect('#great-walk-night-dropdown-box'),
        people_options: collect('#great-walk-people-dropdown-box'),
    };
}
"""

_DISCOVER_DATE_PICKER_JS = """
() => {
    const MAX = 30;
    const items = [];
    const selectors = [
        '.react-datepicker',
        '.react-datepicker__month-container',
        '.react-datepicker__day',
        '[class*="datepicker"]',
        '[role="dialog"]',
        'input[type="date"]',
        'input[type="text"]',
    ];
    selectors.forEach(sel => {
        document.querySelectorAll(sel).forEach(el => {
            if (items.length >= MAX) return;
            const style = window.getComputedStyle(el);
            const visible = style.display !== 'none' && el.getBoundingClientRect().width > 0;
            if (!visible) return;
            if (el.id === 'arrivaldate') return;
            items.push({
                tag: el.tagName,
                id: el.id || null,
                class: (el.className || '').toString().slice(0, 80) || null,
                type: el.getAttribute('type'),
                role: el.getAttribute('role'),
                aria_label: el.getAttribute('aria-label'),
                data_date: el.getAttribute('data-date'),
                value: el.value !== undefined && el.value !== '' ? el.value : null,
                text: (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 40) || null,
            });
        });
    });
    return items.slice(0, MAX);
}
"""

_CLICK_DROPDOWN_OPTION_JS = """
({ listSelector, matchText, matchNumber }) => {
    const root = Array.from(document.querySelectorAll('div[role="search"]'))
        .find(el => (el.className || '').toString().includes('themeTopsearch')
            && el.getBoundingClientRect().width > 0);
    if (!root) return false;
    const list = root.querySelector(listSelector);
    if (!list) return false;
    const nodes = list.querySelectorAll('[id^="great-walk-"], [role="option"], li, button, a, div');
    const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    for (const el of nodes) {
        if (el.id && el.id.includes('-mobile')) continue;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || el.getBoundingClientRect().width === 0) continue;
        const text = norm(el.textContent);
        if (matchText && text === norm(matchText)) { el.click(); return true; }
        if (matchNumber != null) {
            const num = (text.match(/\\d+/) || [])[0];
            if (num && parseInt(num, 10) === matchNumber) { el.click(); return true; }
        }
    }
    return false;
}
"""

_SET_DATE_JS = """
(iso) => {
    const LOADING = ['fetching content'];
    const root = Array.from(document.querySelectorAll('div[role="search"]'))
        .find(el => (el.className || '').toString().includes('themeTopsearch')
            && el.getBoundingClientRect().width > 0);
    if (!root) return { ok: false, reason: 'no-desktop-root' };

    function isVisible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        return el.getBoundingClientRect().width > 0;
    }

    const cells = document.querySelectorAll(`[data-date="${iso}"]`);
    for (const cell of cells) {
        if (!isVisible(cell)) continue;
        if (cell.closest('[id*="-mobile"]')) continue;
        cell.click();
        return { ok: true, method: 'data-date-cell' };
    }

    const inputs = document.querySelectorAll(
        'input[type="date"], input[type="text"], input.react-datepicker-ignore-onclickoutside'
    );
    for (const input of inputs) {
        if (!isVisible(input)) continue;
        if (input.id === 'arrivaldate') continue;
        if (!input.closest('.react-datepicker, [class*="datepicker"], [role="dialog"]')
            && !root.contains(input)) continue;
        input.value = iso;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        return { ok: true, method: 'visible-input', id: input.id || null };
    }

    const labelled = document.querySelectorAll('[aria-label]');
    for (const el of labelled) {
        if (!isVisible(el)) continue;
        const label = (el.getAttribute('aria-label') || '').toLowerCase();
        if (!label.includes(iso) && !label.includes(iso.replace(/-/g, '/'))) continue;
        el.click();
        return { ok: true, method: 'aria-label', aria_label: el.getAttribute('aria-label') };
    }

    return { ok: false, reason: 'no-date-control-found' };
}
"""

_PROBE_CLICK_READINESS_JS = """
({ rootSelector, targetSelector }) => {
    const MAX_ANCESTOR = 5;
    const LOADING_MARKERS = ['fetching content', 'loading', 'please wait'];

    function isVisible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function describe(el) {
        if (!el) return null;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return {
            tag: el.tagName,
            id: el.id || null,
            class: (el.className || '').toString().slice(0, 120) || null,
            role: el.getAttribute('role'),
            aria_label: el.getAttribute('aria-label'),
            aria_busy: el.getAttribute('aria-busy'),
            text: (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 80) || null,
            pointer_events: style.pointerEvents,
            position: style.position,
            z_index: style.zIndex,
            opacity: style.opacity,
            display: style.display,
            visibility: style.visibility,
            rect: {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
            },
        };
    }

    function ancestors(el) {
        const chain = [];
        let node = el;
        for (let i = 0; i < MAX_ANCESTOR && node; i++) {
            chain.push({
                tag: node.tagName,
                id: node.id || null,
                class: (node.className || '').toString().slice(0, 80) || null,
                role: node.getAttribute('role'),
            });
            node = node.parentElement;
        }
        return chain;
    }

    const roots = Array.from(document.querySelectorAll('div[role="search"]'))
        .filter(el => {
            const cls = (el.className || '').toString();
            return cls.includes('themeTopsearch') && isVisible(el);
        });

    const root = roots.length === 1 ? roots[0] : null;
    if (!root) {
        return { found: false, clickable: false, desktop_root_count: roots.length };
    }

    let target = null;
    if (targetSelector.includes('has-text')) {
        const buttons = Array.from(root.querySelectorAll('button')).filter(isVisible);
        target = buttons.find(b => /^search$/i.test((b.textContent || '').trim())) || null;
    } else {
        target = root.querySelector(targetSelector);
    }

    if (!target || !isVisible(target)) {
        return {
            found: false,
            clickable: false,
            target: target ? describe(target) : null,
            desktop_root_count: roots.length,
            root_class: (root.className || '').toString().slice(0, 120),
            control_selector: targetSelector,
        };
    }

    const rect = target.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const hit = document.elementFromPoint(cx, cy);
    const clickable = !!(hit && (target === hit || target.contains(hit)));

    let loadingOverlay = null;
    const overlays = root.querySelectorAll(
        '[aria-busy="true"], .loading, .spinner, [class*="loading"]'
    );
    for (const el of overlays) {
        if (!isVisible(el)) continue;
        const text = (el.textContent || '').toLowerCase();
        if (LOADING_MARKERS.some(m => text.includes(m))) {
            loadingOverlay = describe(el);
            break;
        }
    }
    if (!loadingOverlay && LOADING_MARKERS.some(m => (root.textContent || '').toLowerCase().includes(m))) {
        loadingOverlay = { type: 'root-text-loading' };
    }

    let interceptor = null;
    if (!clickable && hit && !target.contains(hit)) {
        interceptor = describe(hit);
    }

    return {
        found: true,
        clickable: clickable && !loadingOverlay,
        control_selector: targetSelector,
        center: { x: Math.round(cx), y: Math.round(cy) },
        target: describe(target),
        hit: hit ? describe(hit) : null,
        interceptor,
        target_ancestors: ancestors(target),
        interceptor_ancestors: hit ? ancestors(hit) : [],
        loading_overlay: loadingOverlay,
        root_class: (root.className || '').toString().slice(0, 120),
        desktop_root_count: roots.length,
    };
}
"""


class DesktopFormPage(Protocol):
    def locator(self, selector: str) -> Any: ...

    def evaluate(self, expression: str, arg: Any = None) -> Any: ...

    def wait_for_timeout(self, timeout: int) -> None: ...


@dataclass(frozen=True)
class DesktopRootBinding:
    selector: str
    count: int
    root_id: str | None = None
    root_class: str | None = None


def resolve_desktop_great_walk_root(page: DesktopFormPage) -> DesktopRootBinding:
    """Require exactly one visible desktop Great Walk search widget."""
    raw = page.evaluate(_READ_DESKTOP_STATE_JS)
    if not isinstance(raw, dict):
        raise GreatWalkDesktopRootError("Could not evaluate desktop Great Walk root state")
    count = int(raw.get("desktop_root_count") or 0)
    root_info = raw.get("desktop_root")
    if count != 1 or not root_info:
        raise GreatWalkDesktopRootError(
            f"Expected exactly one visible desktop Great Walk root "
            f"({DESKTOP_ROOT_SELECTOR}), found {count}",
            root_count=count,
        )
    return DesktopRootBinding(
        selector=str(root_info.get("selector") or DESKTOP_ROOT_SELECTOR),
        count=count,
        root_id=root_info.get("id"),
        root_class=root_info.get("class"),
    )


def discover_desktop_dropdown_options(page: DesktopFormPage) -> dict[str, list[dict[str, Any]]]:
    raw = page.evaluate(_DISCOVER_DROPDOWN_OPTIONS_JS)
    if not isinstance(raw, dict):
        return {"track_options": [], "nights_options": [], "people_options": []}
    return {
        "track_options": list(raw.get("track_options") or [])[:20],
        "nights_options": list(raw.get("nights_options") or [])[:20],
        "people_options": list(raw.get("people_options") or [])[:20],
    }


def discover_date_picker_elements(page: DesktopFormPage) -> list[dict[str, Any]]:
    raw = page.evaluate(_DISCOVER_DATE_PICKER_JS)
    return list(raw) if isinstance(raw, list) else []


def _sanitize_click_diagnostics(diag: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "found",
        "clickable",
        "control_selector",
        "center",
        "target",
        "hit",
        "interceptor",
        "target_ancestors",
        "interceptor_ancestors",
        "loading_overlay",
        "root_class",
        "desktop_root_count",
    )
    return {key: diag[key] for key in allowed if key in diag}


def probe_click_readiness(
    page: DesktopFormPage,
    binding: DesktopRootBinding,
    target_selector: str,
) -> dict[str, Any]:
    raw = page.evaluate(
        _PROBE_CLICK_READINESS_JS,
        {"rootSelector": binding.selector, "targetSelector": target_selector},
    )
    return raw if isinstance(raw, dict) else {"found": False, "clickable": False}


def _interceptor_is_benign_widget_overlay(diag: dict[str, Any]) -> bool:
    if diag.get("loading_overlay"):
        return True
    root_class = (diag.get("root_class") or "").lower()
    if "selectedpark" in root_class:
        return True
    for key in ("interceptor", "hit"):
        el = diag.get(key) or {}
        cls = (el.get("class") or "").lower()
        role = el.get("role") or ""
        text = (el.get("text") or "").lower()
        if role == "search" and "themeTopsearch" in cls:
            return True
        if any(marker in text for marker in ("fetching content", "loading", "please wait")):
            return True
        if "loading" in cls or "spinner" in cls:
            return True
        if el.get("aria_busy") == "true":
            return True
    return False


def _is_pointer_interception_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "intercepts pointer" in msg or ("intercept" in msg and "pointer" in msg)


def wait_for_control_clickable(
    page: DesktopFormPage,
    binding: DesktopRootBinding,
    target_selector: str,
    control_name: str,
    *,
    timeout_ms: int | None = None,
    root_change: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timeout = timeout_ms or DEFAULT_CONTROL_CLICKABLE_TIMEOUT_MS
    deadline = time.monotonic() + (timeout / 1000.0)
    last_diag: dict[str, Any] = {"found": False, "clickable": False}
    while time.monotonic() < deadline:
        last_diag = probe_click_readiness(page, binding, target_selector)
        if last_diag.get("clickable"):
            return last_diag
        page.wait_for_timeout(100)
    raise GreatWalkControlNotClickableError(
        f"Desktop control {control_name!r} is not clickable at center after {timeout}ms",
        control=control_name,
        click_diagnostics=_sanitize_click_diagnostics(last_diag),
        root_change=root_change,
    )


def click_desktop_control(
    page: DesktopFormPage,
    binding: DesktopRootBinding,
    target_selector: str,
    control_name: str,
    *,
    timeout_ms: int | None = None,
    root_change: dict[str, Any] | None = None,
) -> None:
    timeout = timeout_ms or DEFAULT_CONTROL_CLICKABLE_TIMEOUT_MS
    wait_for_control_clickable(
        page,
        binding,
        target_selector,
        control_name,
        timeout_ms=timeout,
        root_change=root_change,
    )
    root = page.locator(binding.selector)
    locator = (
        root.locator(target_selector)
        if target_selector == SEARCH_BUTTON_SELECTOR
        else root.locator(target_selector).first
    )
    for attempt in range(2):
        try:
            locator.click(timeout=min(5_000, timeout))
            return
        except Exception as exc:
            if not _is_pointer_interception_error(exc) and "Timeout" not in str(exc):
                raise
            last_diag = probe_click_readiness(page, binding, target_selector)
            if attempt == 0 and _interceptor_is_benign_widget_overlay(last_diag):
                wait_for_control_clickable(
                    page,
                    binding,
                    target_selector,
                    control_name,
                    timeout_ms=timeout,
                    root_change=root_change,
                )
                binding = resolve_desktop_great_walk_root(page)
                root = page.locator(binding.selector)
                locator = (
                    root.locator(target_selector)
                    if target_selector == SEARCH_BUTTON_SELECTOR
                    else root.locator(target_selector).first
                )
                continue
            raise GreatWalkControlNotClickableError(
                f"Desktop control {control_name!r} click blocked by overlay",
                control=control_name,
                click_diagnostics=_sanitize_click_diagnostics(last_diag),
                root_change=root_change,
            ) from exc


def refresh_desktop_root_binding(
    page: DesktopFormPage,
    prior: DesktopRootBinding | None,
) -> tuple[DesktopRootBinding, dict[str, Any]]:
    new = resolve_desktop_great_walk_root(page)
    current = {
        "selector": new.selector,
        "id": new.root_id,
        "class": new.root_class,
    }
    prior_info: dict[str, Any] | None = None
    root_replaced = False
    if prior is not None:
        prior_info = {
            "selector": prior.selector,
            "id": prior.root_id,
            "class": prior.root_class,
        }
        root_replaced = (
            prior.root_id != new.root_id or prior.root_class != new.root_class
        )
    return new, {
        "root_replaced": root_replaced,
        "prior_root": prior_info,
        "current_root": current,
    }


def open_desktop_date_picker(
    page: DesktopFormPage,
    binding: DesktopRootBinding | None = None,
    *,
    root_change: dict[str, Any] | None = None,
) -> None:
    binding = binding or resolve_desktop_great_walk_root(page)
    root = page.locator(binding.selector)
    if root.locator(DATE_BUTTON_SELECTOR).count() == 0:
        raise GreatWalkControlNotFoundError(
            "Desktop start date button not found",
            control="start_date",
        )
    click_desktop_control(
        page,
        binding,
        DATE_BUTTON_SELECTOR,
        "start_date",
        root_change=root_change,
    )
    page.wait_for_timeout(300)


def _extract_count(text: str | None) -> int | None:
    if not text:
        return None
    match = _COUNT_RE.search(text)
    return int(match.group(1)) if match else None


def _attach_match_flags(
    state: dict[str, Any],
    *,
    track_name: str | None = None,
    start_date: date | None = None,
    nights: int | None = None,
    people_size: int | None = None,
) -> dict[str, Any]:
    result = dict(state)
    track_ctrl = dict(state.get("track_control") or {})
    visible = (track_ctrl.get("visible_text") or "").strip()
    if track_name is not None:
        track_ctrl["matches_requested"] = bool(visible) and track_name.lower() in visible.lower()
    result["track_control"] = track_ctrl

    nights_ctrl = dict(state.get("nights_control") or {})
    if nights is not None and nights_ctrl:
        count = _extract_count(nights_ctrl.get("visible_text"))
        nights_ctrl["normalized_value"] = str(count) if count is not None else None
        nights_ctrl["matches_requested"] = count == nights
    result["nights_control"] = nights_ctrl

    people_ctrl = dict(state.get("people_control") or {})
    if people_size is not None and people_ctrl:
        count = _extract_count(people_ctrl.get("visible_text"))
        people_ctrl["normalized_value"] = str(count) if count is not None else None
        people_ctrl["matches_requested"] = count == people_size
    result["people_control"] = people_ctrl

    start_ctrl = dict(state.get("start_date_control") or {})
    if start_date is not None and start_ctrl:
        normalized = normalize_date_string(start_ctrl.get("data_date"))
        if not normalized:
            normalized = normalize_date_string(start_ctrl.get("visible_text"))
        if not normalized and start_ctrl.get("aria_label"):
            normalized = normalize_date_string(start_ctrl.get("aria_label"))
        if normalized:
            start_ctrl["normalized_value"] = normalized
        start_ctrl["matches_requested"] = normalized == start_date.isoformat()
    result["start_date_control"] = start_ctrl

    search = dict(state.get("search_button") or {})
    result["search_button_visible"] = bool(search.get("visible_text"))
    result["search_button_enabled"] = bool(search.get("enabled", True))
    return result


def read_desktop_form_state(
    page: DesktopFormPage,
    binding: DesktopRootBinding | None = None,
    *,
    track_name: str | None = None,
    start_date: date | None = None,
    nights: int | None = None,
    people_size: int | None = None,
) -> dict[str, Any]:
    binding = binding or resolve_desktop_great_walk_root(page)
    raw = page.evaluate(_READ_DESKTOP_STATE_JS)
    if not isinstance(raw, dict):
        raw = {}
    state = _attach_match_flags(
        raw,
        track_name=track_name,
        start_date=start_date,
        nights=nights,
        people_size=people_size,
    )
    state["desktop_root"] = {
        "selector": binding.selector,
        "count": binding.count,
        "id": binding.root_id,
        "class": binding.root_class,
    }
    return state


def desktop_track_option_id(track: Track) -> str:
    return f"great-walk-{track.list_index + 1}"


def select_desktop_track(
    page: DesktopFormPage,
    track: Track,
    binding: DesktopRootBinding | None = None,
    *,
    root_change: dict[str, Any] | None = None,
) -> None:
    binding = binding or resolve_desktop_great_walk_root(page)
    click_desktop_control(
        page,
        binding,
        TRACK_BUTTON_SELECTOR,
        "track",
        root_change=root_change,
    )
    page.wait_for_timeout(200)
    option_id = desktop_track_option_id(track)
    clicked = page.evaluate(
        """({ optionId }) => {
            const root = Array.from(document.querySelectorAll('div[role="search"]'))
                .find(el => (el.className || '').toString().includes('themeTopsearch')
                    && el.getBoundingClientRect().width > 0);
            if (!root) return false;
            const list = root.querySelector('#great-walk-dropdown-box');
            if (!list) return false;
            const el = list.querySelector('#' + optionId) || document.getElementById(optionId);
            if (!el || el.id.includes('-mobile')) return false;
            el.click();
            return true;
        }""",
        {"optionId": option_id},
    )
    if not clicked:
        raise GreatWalkControlNotFoundError(
            f"Could not click desktop track option #{option_id} in {TRACK_LIST_SELECTOR}",
            control="track",
        )
    page.wait_for_timeout(200)


def _click_dropdown_option(
    page: DesktopFormPage,
    *,
    list_selector: str,
    match_number: int,
) -> None:
    clicked = page.evaluate(
        _CLICK_DROPDOWN_OPTION_JS,
        {"listSelector": list_selector, "matchText": None, "matchNumber": match_number},
    )
    if not clicked:
        raise GreatWalkControlNotFoundError(
            f"Could not select dropdown option {match_number} in {list_selector}",
            control=list_selector,
        )
    page.wait_for_timeout(200)


def select_desktop_nights(
    page: DesktopFormPage,
    nights: int,
    binding: DesktopRootBinding | None = None,
    *,
    root_change: dict[str, Any] | None = None,
) -> None:
    binding = binding or resolve_desktop_great_walk_root(page)
    click_desktop_control(
        page,
        binding,
        NIGHTS_BUTTON_SELECTOR,
        "nights",
        root_change=root_change,
    )
    page.wait_for_timeout(200)
    _click_dropdown_option(page, list_selector=NIGHTS_LIST_SELECTOR, match_number=nights)


def select_desktop_people(
    page: DesktopFormPage,
    people_size: int,
    binding: DesktopRootBinding | None = None,
    *,
    root_change: dict[str, Any] | None = None,
) -> None:
    binding = binding or resolve_desktop_great_walk_root(page)
    click_desktop_control(
        page,
        binding,
        PEOPLE_BUTTON_SELECTOR,
        "people",
        root_change=root_change,
    )
    page.wait_for_timeout(200)
    _click_dropdown_option(page, list_selector=PEOPLE_LIST_SELECTOR, match_number=people_size)


def set_desktop_start_date(
    page: DesktopFormPage,
    target: date,
    binding: DesktopRootBinding | None = None,
    *,
    root_change: dict[str, Any] | None = None,
) -> None:
    binding = binding or resolve_desktop_great_walk_root(page)
    open_desktop_date_picker(page, binding, root_change=root_change)
    result = page.evaluate(_SET_DATE_JS, target.isoformat())
    if not isinstance(result, dict) or not result.get("ok"):
        reason = result.get("reason") if isinstance(result, dict) else "unknown"
        raise GreatWalkDateControlDiscoveryIncompleteError(
            f"Could not set desktop start date via date picker ({reason}). "
            "Run inspect-greatwalk-dom --open-date-picker for evidence.",
            date_iso=target.isoformat(),
        )
    page.wait_for_timeout(300)


def click_desktop_search_button(
    page: DesktopFormPage,
    binding: DesktopRootBinding | None = None,
    *,
    root_change: dict[str, Any] | None = None,
) -> None:
    binding = binding or resolve_desktop_great_walk_root(page)
    root = page.locator(binding.selector)
    btn = root.locator(SEARCH_BUTTON_SELECTOR)
    if btn.count() == 0:
        raise GreatWalkControlNotFoundError(
            "Search button not found within desktop Great Walk root",
            control="search",
        )
    if not btn.first.is_enabled():
        raise SearchFormValidationError("Desktop Great Walk Search button is disabled")
    click_desktop_control(
        page,
        binding,
        SEARCH_BUTTON_SELECTOR,
        "search",
        root_change=root_change,
    )


def _raise_if_not_actionable(state: dict[str, Any], *, phase: str) -> None:
    if state.get("loading_present"):
        from greatwalkbot.infra.errors import GreatWalkFormNotReadyError

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
            f"Desktop Search button visible but disabled {phase}",
            form_state=state,
        )


def wait_for_desktop_form_values(
    page: DesktopFormPage,
    binding: DesktopRootBinding,
    *,
    track_name: str,
    start_date: date,
    nights: int,
    people_size: int,
    timeout_ms: int = 5_000,
) -> dict[str, Any]:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    last_state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_state = read_desktop_form_state(
            page,
            binding,
            track_name=track_name,
            start_date=start_date,
            nights=nights,
            people_size=people_size,
        )
        if (
            last_state.get("track_control", {}).get("matches_requested")
            and last_state.get("nights_control", {}).get("matches_requested")
            and last_state.get("people_control", {}).get("matches_requested")
            and last_state.get("start_date_control", {}).get("matches_requested")
        ):
            return last_state
        page.wait_for_timeout(100)
    return last_state


def _control_needs_change(state: dict[str, Any], control_key: str) -> bool:
    return not bool(state.get(control_key, {}).get("matches_requested"))


def _wait_for_first_needed_control_clickable(
    page: DesktopFormPage,
    binding: DesktopRootBinding,
    state: dict[str, Any],
    *,
    root_change: dict[str, Any] | None = None,
) -> None:
    checks = (
        ("start_date_control", DATE_BUTTON_SELECTOR, "start_date"),
        ("nights_control", NIGHTS_BUTTON_SELECTOR, "nights"),
        ("people_control", PEOPLE_BUTTON_SELECTOR, "people"),
    )
    for control_key, selector, control_name in checks:
        if _control_needs_change(state, control_key):
            wait_for_control_clickable(
                page,
                binding,
                selector,
                control_name,
                root_change=root_change,
            )
            return


def _verify_control_changed(
    page: DesktopFormPage,
    binding: DesktopRootBinding,
    *,
    track_name: str | None = None,
    start_date: date | None = None,
    nights: int | None = None,
    people_size: int | None = None,
    control_key: str,
) -> bool:
    state = read_desktop_form_state(
        page,
        binding,
        track_name=track_name,
        start_date=start_date,
        nights=nights,
        people_size=people_size,
    )
    return bool(state.get(control_key, {}).get("matches_requested"))


def _ensure_desktop_date(
    page: DesktopFormPage,
    binding: DesktopRootBinding,
    start_date: date,
    state: dict[str, Any],
    *,
    root_change: dict[str, Any] | None = None,
) -> ControlActionOutcome:
    if not _control_needs_change(state, "start_date_control"):
        return "already_matched"
    try:
        set_desktop_start_date(page, start_date, binding, root_change=root_change)
    except GreatWalkDateControlDiscoveryIncompleteError:
        raise
    except GreatWalkControlNotFoundError as exc:
        raise GreatWalkDateControlDiscoveryIncompleteError(
            str(exc),
            date_iso=start_date.isoformat(),
        ) from exc
    if _verify_control_changed(
        page,
        binding,
        start_date=start_date,
        control_key="start_date_control",
    ):
        return "changed_and_verified"
    return "change_failed"


def _ensure_desktop_nights(
    page: DesktopFormPage,
    binding: DesktopRootBinding,
    nights: int,
    state: dict[str, Any],
    *,
    root_change: dict[str, Any] | None = None,
) -> ControlActionOutcome:
    if not _control_needs_change(state, "nights_control"):
        return "already_matched"
    select_desktop_nights(page, nights, binding, root_change=root_change)
    if _verify_control_changed(
        page,
        binding,
        nights=nights,
        control_key="nights_control",
    ):
        return "changed_and_verified"
    return "change_failed"


def _ensure_desktop_people(
    page: DesktopFormPage,
    binding: DesktopRootBinding,
    people_size: int,
    state: dict[str, Any],
    *,
    root_change: dict[str, Any] | None = None,
) -> ControlActionOutcome:
    if not _control_needs_change(state, "people_control"):
        return "already_matched"
    select_desktop_people(page, people_size, binding, root_change=root_change)
    if _verify_control_changed(
        page,
        binding,
        people_size=people_size,
        control_key="people_control",
    ):
        return "changed_and_verified"
    return "change_failed"


def prepare_desktop_search_form(
    page: DesktopFormPage,
    track: Track,
    *,
    start_date: date,
    nights: int,
    people_size: int,
) -> dict[str, Any]:
    """Fill and verify all desktop Great Walk controls before Search."""
    binding = resolve_desktop_great_walk_root(page)
    state = read_desktop_form_state(
        page,
        binding,
        track_name=track.name,
        start_date=start_date,
        nights=nights,
        people_size=people_size,
    )
    _raise_if_not_actionable(state, phase="before search")

    control_actions: dict[str, str] = {}
    root_change: dict[str, Any] | None = None
    track_changed = False

    if state.get("track_control", {}).get("matches_requested"):
        control_actions["track"] = "already_matched"
    else:
        select_desktop_track(page, track, binding, root_change=root_change)
        track_changed = True
        binding, root_change = refresh_desktop_root_binding(page, binding)
        state = read_desktop_form_state(
            page,
            binding,
            track_name=track.name,
            start_date=start_date,
            nights=nights,
            people_size=people_size,
        )
        if state.get("track_control", {}).get("matches_requested"):
            control_actions["track"] = "changed_and_verified"
        else:
            control_actions["track"] = "change_failed"

    binding, refresh_info = refresh_desktop_root_binding(page, binding)
    if root_change is None:
        root_change = refresh_info
    elif refresh_info.get("root_replaced"):
        root_change = {**root_change, **refresh_info}

    if track_changed or refresh_info.get("root_replaced"):
        _wait_for_first_needed_control_clickable(
            page,
            binding,
            state,
            root_change=root_change,
        )

    control_actions["date"] = _ensure_desktop_date(
        page,
        binding,
        start_date,
        state,
        root_change=root_change,
    )
    state = read_desktop_form_state(
        page,
        binding,
        track_name=track.name,
        start_date=start_date,
        nights=nights,
        people_size=people_size,
    )

    control_actions["nights"] = _ensure_desktop_nights(
        page,
        binding,
        nights,
        state,
        root_change=root_change,
    )
    state = read_desktop_form_state(
        page,
        binding,
        track_name=track.name,
        start_date=start_date,
        nights=nights,
        people_size=people_size,
    )

    control_actions["people"] = _ensure_desktop_people(
        page,
        binding,
        people_size,
        state,
        root_change=root_change,
    )

    state = wait_for_desktop_form_values(
        page,
        binding,
        track_name=track.name,
        start_date=start_date,
        nights=nights,
        people_size=people_size,
    )
    state["control_actions"] = control_actions

    failures: list[str] = []
    if control_actions.get("track") == "change_failed":
        failures.append(f"track (expected {track.name!r})")
    if not state.get("track_control", {}).get("matches_requested"):
        failures.append(f"track (expected {track.name!r})")
    if not state.get("nights_control", {}).get("matches_requested"):
        failures.append(f"nights (expected {nights})")
    if not state.get("people_control", {}).get("matches_requested"):
        failures.append(f"people (expected {people_size})")
    if not state.get("start_date_control", {}).get("matches_requested"):
        failures.append(f"start date (expected {start_date.isoformat()})")

    if failures:
        if not state.get("start_date_control", {}).get("matches_requested"):
            raise GreatWalkDateControlDiscoveryIncompleteError(
                "Desktop start date not verified after date-picker interaction: "
                + ", ".join(failures),
                date_iso=start_date.isoformat(),
                form_state=state,
            )
        raise SearchFormValidationError(
            "Desktop form values not verified: " + ", ".join(failures),
            form_state=state,
        )

    _raise_if_not_actionable(state, phase="after setting form values")
    if root_change is not None:
        state["desktop_root_refresh"] = root_change
    return state


def capture_desktop_selection_state(
    page: DesktopFormPage,
    track: Track,
    *,
    backend_metadata_confirmed: bool,
) -> dict[str, Any]:
    binding = resolve_desktop_great_walk_root(page)
    state = read_desktop_form_state(page, binding, track_name=track.name)
    track_ctrl = state.get("track_control") or {}
    visible_text = (track_ctrl.get("visible_text") or "").strip()
    visible_matches = bool(track_ctrl.get("matches_requested"))
    return {
        "desktop_root": state.get("desktop_root"),
        "backend_metadata_confirmed": backend_metadata_confirmed,
        "visible_track_label": visible_text or None,
        "visible_track_matches": visible_matches,
        "visible_selection_committed": visible_matches,
        "ui_state_inconsistent": backend_metadata_confirmed and not visible_matches,
    }
