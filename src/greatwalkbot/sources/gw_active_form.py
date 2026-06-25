"""Active Great Walk form root discovery and scoped control interaction."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from greatwalkbot.infra.errors import (
    GreatWalkControlNotFoundError,
    GreatWalkFormNotReadyError,
)
from greatwalkbot.sources.spa_timing import DEFAULT_FORM_READY_TIMEOUT_MS

ACTIVE_ROOT_ATTR = "data-gwbot-active-root"
ACTIVE_ROOT_SELECTOR = f'[{ACTIVE_ROOT_ATTR}="1"]'

PLACEHOLDER_TRACK_LABELS = frozenset({"select great walk", "select a great walk"})

LOADING_TEXT_MARKERS = (
    "fetching content",
    "loading...",
    "loading",
    "please wait",
)

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_DMY_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})")

_RESOLVE_ACTIVE_ROOT_JS = """
() => {
    const LOADING = ['fetching content', 'loading...', 'please wait'];
    const ACTIVE_ATTR = 'data-gwbot-active-root';

    function isVisible(el) {
        if (!el || !el.getBoundingClientRect) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        if (parseFloat(style.opacity || '1') === 0) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function isInteractable(el) {
        return isVisible(el)
            && !el.disabled
            && el.getAttribute('aria-hidden') !== 'true'
            && el.getAttribute('aria-disabled') !== 'true';
    }

    function isLoadingText(text) {
        const t = (text || '').trim().toLowerCase();
        return LOADING.some(m => t.includes(m));
    }

    function rootText(root) {
        return (root.textContent || '').trim().slice(0, 300);
    }

    function hasLoadingPlaceholder(root) {
        const text = rootText(root).toLowerCase();
        if (isLoadingText(text)) return true;
        const nodes = root.querySelectorAll('[class*="loading"], [class*="spinner"], [role="status"]');
        for (const node of nodes) {
            if (!isVisible(node)) continue;
            if (isLoadingText(node.textContent)) return true;
        }
        return false;
    }

    function findDateControl(root) {
        const selectors = [
            'input#great-walk-start-date-input',
            'input[name="startDate"]',
            'input[name*="arrival" i]',
            'input[type="date"][id*="great-walk"]',
            'input[type="hidden"][id*="date" i]',
            'input[id*="great-walk"][id*="date" i]',
        ];
        for (const sel of selectors) {
            const el = root.querySelector(sel);
            if (el && (el.value || el.type === 'date')) {
                return { el, selector: sel, kind: 'input' };
            }
        }
        const btn = root.querySelector('#great-walk-start-date, [id*="start-date" i]');
        if (btn && isVisible(btn)) {
            const hidden = root.querySelector(
                'input#great-walk-start-date-input, input[name="startDate"], '
                + 'input[type="hidden"][id*="date" i]'
            );
            return {
                el: hidden || btn,
                selector: hidden ? '#great-walk-start-date-input' : '#great-walk-start-date',
                kind: hidden ? 'hidden-input' : 'date-button',
                trigger: btn,
            };
        }
        return null;
    }

    function findNightsControl(root) {
        const selectors = [
            'select#great-walk-nights',
            'select[id*="great-walk"][id*="night" i]',
            'select[name*="night" i]',
        ];
        for (const sel of selectors) {
            const el = root.querySelector(sel);
            if (el && isInteractable(el) && el.options && el.options.length > 0) {
                return { el, selector: sel };
            }
        }
        return null;
    }

    function findSearchButton(root) {
        const ids = ['great-walk-search-button', 'great-walk-search', 'btn-great-walk-search'];
        for (const id of ids) {
            const el = root.querySelector('#' + id);
            if (el && isVisible(el)) return { el, selector: '#' + id };
        }
        const btn = Array.from(root.querySelectorAll('button')).find(
            b => /^search$/i.test((b.textContent || '').trim()) && isVisible(b)
        );
        return btn ? { el: btn, selector: 'button:text(Search)' } : null;
    }

    function findTrackControl(root) {
        const ids = ['great-walk-dropdown-button', 'great-walk-mobile-dropdown-button'];
        for (const id of ids) {
            const el = root.querySelector('#' + id);
            if (el && isVisible(el)) return { el, selector: '#' + id };
        }
        return null;
    }

    function scoreRoot(root) {
        let score = 0;
        const reasons = [];
        if (!isVisible(root)) {
            return { score: -1000, reasons: ['hidden'] };
        }
        if (hasLoadingPlaceholder(root)) {
            score -= 30;
            reasons.push('loading-placeholder');
        }
        const nights = findNightsControl(root);
        const dateCtrl = findDateControl(root);
        const search = findSearchButton(root);
        const track = findTrackControl(root);
        if (nights) { score += 25; reasons.push('has-nights'); }
        else { score -= 20; reasons.push('missing-nights'); }
        if (dateCtrl) { score += 20; reasons.push('has-date'); }
        else { score -= 15; reasons.push('missing-date'); }
        if (search) { score += 15; reasons.push('has-search'); }
        if (track) { score += 10; reasons.push('has-track'); }
        const rect = root.getBoundingClientRect();
        score += Math.min(10, Math.floor(rect.width / 200));
        return { score, reasons, nights, dateCtrl, search, track };
    }

    function candidateRoots() {
        const roots = new Set();
        const nightsEls = document.querySelectorAll(
            'select#great-walk-nights, select[id*="great-walk"][id*="night" i]'
        );
        nightsEls.forEach(el => {
            let node = el;
            for (let i = 0; i < 8 && node; i++) {
                if (node.id && /great-walk|greatwalk/i.test(node.id)) {
                    roots.add(node);
                    break;
                }
                if (node.tagName === 'FORM' || (node.classList && node.classList.contains('tab-pane'))) {
                    roots.add(node);
                    break;
                }
                node = node.parentElement;
            }
        });
        document.querySelectorAll(
            '[id*="great-walk"][id*="form" i], [id*="great-walk"][id*="search" i], #great-walk-container'
        ).forEach(el => roots.add(el));
        if (roots.size === 0) {
            const fallback = document.querySelector('[id^="great-walk-"]');
            if (fallback) {
                let node = fallback;
                for (let i = 0; i < 6 && node.parentElement; i++) node = node.parentElement;
                roots.add(node);
            }
        }
        return Array.from(roots);
    }

    document.querySelectorAll('[' + ACTIVE_ATTR + ']').forEach(el => el.removeAttribute(ACTIVE_ATTR));

    const candidates = candidateRoots();
    const evaluated = candidates.map((root, index) => {
        const { score, reasons, nights, dateCtrl, search, track } = scoreRoot(root);
        return {
            index,
            id: root.id || null,
            tag: root.tagName,
            score,
            reasons,
            visible: isVisible(root),
            has_nights: !!nights,
            has_date: !!dateCtrl,
            has_search: !!search,
            has_track: !!track,
            loading: hasLoadingPlaceholder(root),
            root,
        };
    });

    evaluated.sort((a, b) => b.score - a.score);
    const rejected = evaluated.slice(1).map(c => ({
        index: c.index,
        id: c.id,
        tag: c.tag,
        score: c.score,
        reasons: c.reasons,
        rejected_because: 'lower score than active root',
    }));

    const active = evaluated[0] || null;
    if (!active || active.score < 0) {
        return {
            candidate_count: candidates.length,
            active_root: null,
            rejected_candidates: evaluated.map(c => ({
                index: c.index,
                id: c.id,
                tag: c.tag,
                score: c.score,
                reasons: c.reasons,
                rejected_because: c.score < 0 ? 'negative score' : 'no candidates',
            })),
        };
    }

    active.root.setAttribute(ACTIVE_ATTR, '1');
    const nights = findNightsControl(active.root);
    const dateCtrl = findDateControl(active.root);
    const search = findSearchButton(active.root);
    const track = findTrackControl(active.root);

    return {
        candidate_count: candidates.length,
        active_root: {
            index: active.index,
            id: active.id,
            tag: active.tag,
            selector: active.id ? '#' + active.id : '[' + ACTIVE_ATTR + '="1"]',
            score: active.score,
            reasons: active.reasons,
            controls_found: {
                track: !!track,
                start_date: !!dateCtrl,
                nights: !!nights,
                search: !!search,
            },
            loading_present: hasLoadingPlaceholder(active.root),
        },
        rejected_candidates: rejected,
    };
}
"""

_READ_SCOPED_STATE_JS = """
(requested) => {
    const root = document.querySelector('[data-gwbot-active-root="1"]');
    if (!root) return { error: 'no active root' };

    function isVisible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function relSelector(el, fallback) {
        if (!el) return fallback;
        if (el.id) return '#' + el.id;
        return fallback;
    }

    function readSelect(el, selector) {
        const opt = el.options[el.selectedIndex];
        return {
            selector,
            control_type: 'select',
            tag: 'SELECT',
            visible: isVisible(el),
            enabled: !el.disabled,
            raw_value: el.value ?? null,
            normalized_value: el.value ?? null,
            selected_option_value: opt ? opt.value : null,
            selected_option_text: opt ? opt.text.trim() : null,
            visible_text: null,
        };
    }

    function readDate(root) {
        const input = root.querySelector(
            'input#great-walk-start-date-input, input[name="startDate"], '
            + 'input[type="date"][id*="great-walk"], input[type="hidden"][id*="date" i]'
        );
        if (input && input.value) {
            return {
                selector: relSelector(input, 'input[type="date"]'),
                control_type: 'input',
                tag: input.tagName,
                visible: isVisible(input),
                enabled: !input.disabled,
                raw_value: input.value,
                normalized_value: input.value,
                selected_option_value: null,
                selected_option_text: null,
                visible_text: null,
            };
        }
        const btn = root.querySelector('#great-walk-start-date, [id*="start-date" i]');
        const dataDate = btn ? btn.getAttribute('data-date') : null;
        const hidden = root.querySelector('input#great-walk-start-date-input, input[name="startDate"]');
        const raw = (hidden && hidden.value) || dataDate || null;
        return btn ? {
            selector: relSelector(btn, '#great-walk-start-date'),
            control_type: hidden ? 'hidden-input' : 'date-button',
            tag: btn.tagName,
            visible: isVisible(btn),
            enabled: !btn.disabled,
            raw_value: raw,
            normalized_value: raw,
            selected_option_value: null,
            selected_option_text: (btn.textContent || '').trim().slice(0, 40) || null,
            visible_text: (btn.textContent || '').trim().slice(0, 40) || null,
        } : null;
    }

    const trackEl = root.querySelector('#great-walk-dropdown-button, #great-walk-mobile-dropdown-button');
    const visibleTrack = trackEl && isVisible(trackEl) ? trackEl
        : Array.from(root.querySelectorAll('#great-walk-dropdown-button, #great-walk-mobile-dropdown-button'))
            .find(isVisible) || null;

    const nightsEl = root.querySelector('select#great-walk-nights, select[id*="night" i]');
    const searchIds = ['great-walk-search-button', 'great-walk-search', 'btn-great-walk-search'];
    let searchBtn = null;
    let searchSelector = null;
    for (const id of searchIds) {
        const el = root.querySelector('#' + id);
        if (el && isVisible(el)) { searchBtn = el; searchSelector = '#' + id; break; }
    }
    if (!searchBtn) {
        searchBtn = Array.from(root.querySelectorAll('button')).find(
            b => /^search$/i.test((b.textContent || '').trim()) && isVisible(b)
        ) || null;
        if (searchBtn) searchSelector = 'button:text(Search)';
    }

    const LOADING = ['fetching content', 'loading...', 'please wait'];
    function isLoadingText(text) {
        const t = (text || '').trim().toLowerCase();
        return LOADING.some(m => t.includes(m));
    }

    const validation = [];
    root.querySelectorAll('[role="alert"], .invalid-feedback, .field-validation-error').forEach(el => {
        const text = (el.textContent || '').trim();
        if (!text || !isVisible(el)) return;
        if (isLoadingText(text)) return;
        validation.push(text.slice(0, 200));
    });

    let loading = false;
    root.querySelectorAll('[class*="loading"], [class*="spinner"], [role="status"]').forEach(el => {
        if (isVisible(el) && isLoadingText(el.textContent)) loading = true;
    });
    const rootText = (root.textContent || '').trim();
    if (isLoadingText(rootText)) loading = true;

    return {
        active_root: {
            id: root.id || null,
            selector: root.id ? '#' + root.id : '[data-gwbot-active-root="1"]',
        },
        track_control: visibleTrack ? {
            selector: relSelector(visibleTrack, '#great-walk-dropdown-button'),
            control_type: 'dropdown-button',
            tag: visibleTrack.tagName,
            visible: true,
            enabled: !visibleTrack.disabled,
            raw_value: null,
            normalized_value: null,
            selected_option_value: null,
            selected_option_text: null,
            visible_text: (visibleTrack.textContent || '').trim().slice(0, 120) || null,
        } : {},
        start_date_control: readDate(root) || {},
        nights_control: nightsEl && nightsEl.options && nightsEl.options.length
            ? readSelect(nightsEl, relSelector(nightsEl, 'select#great-walk-nights'))
            : {},
        search_button_selector: searchSelector,
        search_button_text: searchBtn ? (searchBtn.textContent || '').trim().slice(0, 40) : null,
        search_button_enabled: searchBtn
            ? !(searchBtn.disabled || searchBtn.getAttribute('aria-disabled') === 'true')
            : false,
        search_button_visible: !!searchBtn,
        validation_messages: validation.slice(0, 5),
        loading_present: loading,
        requested,
    };
}
"""

_INVENTORY_JS = """
() => {
    const root = document.querySelector('[data-gwbot-active-root="1"]');
    if (!root) return [];
    const items = [];
    const nodes = root.querySelectorAll(
        'input, select, button, [role="listbox"], [role="combobox"], label, [role="alert"]'
    );
    for (const el of nodes) {
        if (items.length >= 40) break;
        const style = window.getComputedStyle(el);
        const visible = style.display !== 'none' && style.visibility !== 'hidden'
            && el.getBoundingClientRect().width > 0;
        const entry = {
            tag: el.tagName,
            id: el.id || null,
            name: el.getAttribute('name'),
            type: el.getAttribute('type'),
            role: el.getAttribute('role'),
            visible,
            enabled: !el.disabled,
            value: el.value !== undefined && el.value !== '' ? el.value : null,
            checked: el.checked === true ? true : null,
            selected: el.tagName === 'OPTION' ? el.selected : null,
            label: (el.labels && el.labels[0] ? el.labels[0].textContent : el.textContent || '')
                .trim().slice(0, 80) || null,
        };
        items.push(entry);
    }
    return items;
}
"""


@dataclass
class ActiveFormResolution:
    candidate_count: int
    active_root: dict[str, Any] | None
    rejected_candidates: list[dict[str, Any]] = field(default_factory=list)

    @property
    def root_selector(self) -> str:
        if self.active_root is None:
            return ACTIVE_ROOT_SELECTOR
        return str(self.active_root.get("selector") or ACTIVE_ROOT_SELECTOR)

    @property
    def controls_found(self) -> dict[str, bool]:
        if self.active_root is None:
            return {}
        return dict(self.active_root.get("controls_found") or {})


class PlaywrightFormPage(Protocol):
    def locator(self, selector: str) -> Any: ...

    def evaluate(self, expression: str, arg: Any = None) -> Any: ...

    def wait_for_timeout(self, timeout: int) -> None: ...


def normalize_date_string(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if _ISO_DATE_RE.match(value):
        return value[:10]
    dmy_match = _DMY_DATE_RE.match(value)
    if dmy_match:
        day, month, year = dmy_match.groups()
        return date(int(year), int(month), int(day)).isoformat()
    if len(value) >= 10 and value[4] == "-" and value[7] == "-":
        return value[:10]
    return None


def resolve_active_great_walk_form(page: PlaywrightFormPage) -> ActiveFormResolution:
    raw = page.evaluate(_RESOLVE_ACTIVE_ROOT_JS)
    if not isinstance(raw, dict):
        return ActiveFormResolution(candidate_count=0, active_root=None)
    return ActiveFormResolution(
        candidate_count=int(raw.get("candidate_count") or 0),
        active_root=raw.get("active_root"),
        rejected_candidates=list(raw.get("rejected_candidates") or []),
    )


def inventory_active_form(page: PlaywrightFormPage) -> list[dict[str, Any]]:
    raw = page.evaluate(_INVENTORY_JS)
    return list(raw) if isinstance(raw, list) else []


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
    if start_date is not None and start_ctrl:
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


def read_active_form_state(
    page: PlaywrightFormPage,
    resolution: ActiveFormResolution,
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
    raw = page.evaluate(_READ_SCOPED_STATE_JS, requested)
    if not isinstance(raw, dict):
        raw = {}
    state = _attach_match_flags(raw, track_name=track_name, start_date=start_date, nights=nights)
    state["form_resolution"] = {
        "candidate_count": resolution.candidate_count,
        "active_root": resolution.active_root,
        "rejected_candidates": resolution.rejected_candidates[:5],
    }
    return state


def _require_controls(state: dict[str, Any], resolution: ActiveFormResolution) -> None:
    found = resolution.controls_found
    if not found.get("start_date") or not state.get("start_date_control"):
        raise GreatWalkControlNotFoundError(
            "Start date control not found in active Great Walk form root",
            control="start_date",
            form_state=state,
        )
    if not found.get("nights") or not state.get("nights_control"):
        raise GreatWalkControlNotFoundError(
            "Nights control not found in active Great Walk form root",
            control="nights",
            form_state=state,
        )
    if not found.get("search"):
        raise GreatWalkControlNotFoundError(
            "Search button not found in active Great Walk form root",
            control="search",
            form_state=state,
        )


def wait_for_active_form_ready(
    page: PlaywrightFormPage,
    *,
    timeout_ms: int = DEFAULT_FORM_READY_TIMEOUT_MS,
) -> tuple[ActiveFormResolution, dict[str, Any]]:
    """Wait until the active form root is resolved and not in a loading state."""
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    last_resolution = ActiveFormResolution(candidate_count=0, active_root=None)
    last_state: dict[str, Any] = {}

    while time.monotonic() < deadline:
        last_resolution = resolve_active_great_walk_form(page)
        if last_resolution.active_root is None:
            page.wait_for_timeout(150)
            continue
        last_state = read_active_form_state(page, last_resolution)
        loading = bool(
            last_state.get("loading_present")
            or last_resolution.active_root.get("loading_present")
        )
        controls = last_resolution.controls_found
        if (
            not loading
            and controls.get("nights")
            and controls.get("start_date")
            and controls.get("search")
        ):
            return last_resolution, last_state
        page.wait_for_timeout(150)

    last_state = read_active_form_state(page, last_resolution)
    raise GreatWalkFormNotReadyError(
        "Active Great Walk form did not become ready within "
        f"{timeout_ms}ms (loading or required controls missing)",
        form_state=last_state,
    )


def capture_selection_state(
    page: PlaywrightFormPage,
    track: Any,
    resolution: ActiveFormResolution,
    *,
    backend_metadata_confirmed: bool,
) -> dict[str, Any]:
    state = read_active_form_state(page, resolution, track_name=track.name)
    track_ctrl = state.get("track_control") or {}
    visible_text = (track_ctrl.get("visible_text") or "").strip()
    visible_matches = bool(track_ctrl.get("matches_requested"))
    placeholder = visible_text.lower() in PLACEHOLDER_TRACK_LABELS if visible_text else True
    return {
        "active_root": state.get("active_root"),
        "backend_metadata_confirmed": backend_metadata_confirmed,
        "visible_track_label": visible_text or None,
        "visible_track_matches": visible_matches,
        "visible_selection_committed": visible_matches and not placeholder,
        "ui_state_inconsistent": backend_metadata_confirmed and not visible_matches,
    }


def set_active_start_date(page: PlaywrightFormPage, target: date) -> None:
    iso = target.isoformat()
    root = page.locator(ACTIVE_ROOT_SELECTOR)

    hidden = root.locator(
        "input#great-walk-start-date-input, input[name='startDate'], "
        "input[type='hidden'][id*='date' i]"
    )
    if hidden.count() > 0:
        field = hidden.first
        field.fill(iso)
        field.dispatch_event("input")
        field.dispatch_event("change")
        field.dispatch_event("blur")
        page.wait_for_timeout(150)
        return

    date_input = root.locator("input[type='date'][id*='great-walk']")
    if date_input.count() > 0:
        date_input.first.fill(iso)
        date_input.first.dispatch_event("change")
        page.wait_for_timeout(150)
        return

    date_btn = root.locator("#great-walk-start-date, [id*='start-date' i]").first
    if date_btn.count() == 0:
        raise GreatWalkControlNotFoundError(
            "Start date control not found in active form",
            control="start_date",
        )
    date_btn.click()
    page.wait_for_timeout(200)
    cell = page.locator(f'[data-gwbot-active-root="1"] [data-date="{iso}"], [data-date="{iso}"]')
    if cell.count() > 0:
        cell.first.click()
        page.wait_for_timeout(150)
        return

    raise GreatWalkControlNotFoundError(
        f"Could not set start date to {iso} via active form date picker",
        control="start_date",
    )


def set_active_nights(page: PlaywrightFormPage, nights: int) -> None:
    root = page.locator(ACTIVE_ROOT_SELECTOR)
    select = root.locator("select#great-walk-nights, select[id*='night' i]")
    if select.count() == 0:
        raise GreatWalkControlNotFoundError(
            "Nights select not found in active form",
            control="nights",
        )
    nights_str = str(nights)
    select.first.select_option(value=nights_str)
    select.first.dispatch_event("input")
    select.first.dispatch_event("change")
    select.first.dispatch_event("blur")
    page.wait_for_timeout(150)


def wait_for_active_form_values(
    page: PlaywrightFormPage,
    resolution: ActiveFormResolution,
    *,
    track_name: str,
    start_date: date,
    nights: int,
    timeout_ms: int = 5_000,
) -> dict[str, Any]:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    last_state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_state = read_active_form_state(
            page,
            resolution,
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


def click_active_search_button(page: PlaywrightFormPage) -> bool:
    return bool(
        page.evaluate(
            """() => {
                const root = document.querySelector('[data-gwbot-active-root="1"]');
                if (!root) return false;
                const ids = ['great-walk-search-button', 'great-walk-search', 'btn-great-walk-search'];
                for (const id of ids) {
                    const btn = root.querySelector('#' + id);
                    if (btn && btn.offsetParent && !btn.disabled) {
                        btn.click();
                        return true;
                    }
                }
                const btn = Array.from(root.querySelectorAll('button')).find(
                    b => /^search$/i.test((b.textContent || '').trim()) && b.offsetParent && !b.disabled
                );
                if (btn) { btn.click(); return true; }
                return false;
            }"""
        )
    )
