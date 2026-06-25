"""Desktop date-picker popup resolution and navigation control binding."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from greatwalkbot.infra.errors import GreatWalkDatePickerError

DATE_TRIGGER_SELECTOR = "#great-walk-start-date"
DATE_MOBILE_SELECTOR = "#great-walk-start-date-mobile"

MAX_NAV_CANDIDATES = 20
MAX_ANCESTOR_DEPTH = 5
HEADER_UPPER_FRACTION = 0.35
EDGE_FRACTION = 0.25
MIN_HORIZONTAL_SEPARATION_RATIO = 0.3

_NAV_SEMANTIC_NEXT = re.compile(
    r"next|forward|chevron-right|arrow-right|month.*next",
    re.IGNORECASE,
)
_NAV_SEMANTIC_PREV = re.compile(
    r"prev(?:ious)?|back|chevron-left|arrow-left|month.*prev",
    re.IGNORECASE,
)
_DAY_LABEL_HINT = re.compile(r"^(?:Choose|Not available)\s+", re.IGNORECASE)

_RESOLVE_DESKTOP_POPUP_JS = """
({ triggerSelector }) => {
    const MAX = 20;
    const mobile = document.getElementById('great-walk-start-date-mobile');
    const trigger = document.querySelector(triggerSelector);
    if (!trigger || trigger.id.includes('-mobile')) {
        return { found: false, reason: 'desktop-trigger-missing' };
    }
    function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }
    function inMobile(el) {
        return !!(mobile && mobile.contains(el)) || !!el.closest('[id*="-mobile"]');
    }
    function hasCalendarContent(el) {
        return !!(
            el.querySelector('.react-datepicker__day, .react-datepicker__month-container, [role="grid"], [role="gridcell"]')
            || el.querySelector('button[aria-label^="Choose"], button[aria-label^="Not available"]')
            || el.querySelector('[class*="day"]')
        );
    }
    const roots = [
        '.react-datepicker-popper',
        '.react-datepicker',
        '[class*="datepicker-popper"]',
        '[class*="DatePicker"]',
        '[role="dialog"]',
    ];
    const popups = [];
    const seen = new Set();
    for (const sel of roots) {
        document.querySelectorAll(sel).forEach(el => {
            if (!visible(el) || inMobile(el) || !hasCalendarContent(el)) return;
            const rect = el.getBoundingClientRect();
            const key = Math.round(rect.x) + ':' + Math.round(rect.y) + ':' + Math.round(rect.width);
            if (seen.has(key)) return;
            seen.add(key);
            const triggerRect = trigger.getBoundingClientRect();
            popups.push({
                strategy: sel,
                tag: el.tagName,
                id: el.id || null,
                class: (el.className || '').toString().slice(0, 120),
                role: el.getAttribute('role'),
                rect: {
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                },
                distance_below_trigger: Math.max(0, Math.round(rect.top - triggerRect.bottom)),
            });
        });
    }
    popups.sort((a, b) => a.distance_below_trigger - b.distance_below_trigger);
    return {
        found: popups.length === 1,
        popup_count: popups.length,
        popup: popups[0] || null,
        popups: popups.slice(0, MAX),
        trigger_rect: (() => {
            const r = trigger.getBoundingClientRect();
            return { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) };
        })(),
    };
}
"""

_DISCOVER_NAVIGATION_JS = """
() => {
    const MAX = 20;
    const MAX_ANCESTOR = 5;
    const mobile = document.getElementById('great-walk-start-date-mobile');
    const trigger = document.querySelector('#great-walk-start-date');
    function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }
    function inMobile(el) {
        return !!(mobile && mobile.contains(el)) || !!el.closest('[id*="-mobile"]');
    }
    function findPopup() {
        const roots = ['.react-datepicker-popper', '.react-datepicker', '[class*="datepicker-popper"]', '[role="dialog"]'];
        const popups = [];
        for (const sel of roots) {
            document.querySelectorAll(sel).forEach(el => {
                if (!visible(el) || inMobile(el)) return;
                const rect = el.getBoundingClientRect();
                const triggerRect = trigger ? trigger.getBoundingClientRect() : { bottom: 0 };
                popups.push({ el, rect, distance: Math.max(0, rect.top - triggerRect.bottom) });
            });
        }
        popups.sort((a, b) => a.distance - b.distance);
        return popups[0] ? popups[0].el : null;
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
    function clickableTarget(el) {
        if (!el) return null;
        if (el.tagName === 'BUTTON' || el.tagName === 'A') return el;
        if (el.getAttribute('role') === 'button') return el;
        const tabindex = el.getAttribute('tabindex');
        if (tabindex !== null && tabindex !== '-1') return el;
        if (el.tagName === 'SVG') return el.closest('button, a, [role="button"], [tabindex]') || el;
        return null;
    }
    const popup = findPopup();
    if (!popup) {
        return { found: false, popup: null, candidates: [] };
    }
    const popupRect = popup.getBoundingClientRect();
    const headerBottom = popupRect.top + popupRect.height * 0.35;
    const selectors = ['button', '[role="button"]', 'a', 'svg', '[tabindex]'];
    const candidates = [];
    const seen = new Set();
    for (const sel of selectors) {
        popup.querySelectorAll(sel).forEach(el => {
            if (candidates.length >= MAX) return;
            const target = clickableTarget(el);
            if (!target || !visible(target) || inMobile(target)) return;
            const aria = (target.getAttribute('aria-label') || '').trim();
            if (/^(Choose|Not available)\\s/i.test(aria)) return;
            const rect = target.getBoundingClientRect();
            if (rect.bottom > headerBottom) return;
            const key = target.tagName + ':' + (target.id || '') + ':' + Math.round(rect.x);
            if (seen.has(key)) return;
            seen.add(key);
            const relX = rect.left - popupRect.left;
            const relY = rect.top - popupRect.top;
            const popupWidth = popupRect.width || 1;
            candidates.push({
                index: candidates.length,
                tag: target.tagName,
                id: target.id || null,
                class: (target.className || '').toString().slice(0, 120) || null,
                role: target.getAttribute('role'),
                aria_label: aria.slice(0, 100) || null,
                title: (target.getAttribute('title') || '').slice(0, 80) || null,
                text: (target.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 40) || null,
                visible: true,
                enabled: !target.disabled && target.getAttribute('aria-disabled') !== 'true',
                rect: {
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                },
                popup_relative_x: Math.round(relX),
                popup_relative_y: Math.round(relY),
                in_upper_portion: true,
                near_left_edge: relX <= popupWidth * 0.25,
                near_right_edge: relX >= popupWidth * 0.75,
                ancestors: ancestors(target),
                react_next: (target.className || '').toString().includes('react-datepicker__navigation--next'),
                react_prev: (target.className || '').toString().includes('react-datepicker__navigation--previous'),
            });
        });
    }
    return {
        found: true,
        popup: {
            tag: popup.tagName,
            id: popup.id || null,
            class: (popup.className || '').toString().slice(0, 120),
            role: popup.getAttribute('role'),
            rect: {
                x: Math.round(popupRect.x),
                y: Math.round(popupRect.y),
                width: Math.round(popupRect.width),
                height: Math.round(popupRect.height),
            },
        },
        candidates,
        standard_nav: {
            next: !!popup.querySelector('.react-datepicker__navigation--next'),
            prev: !!popup.querySelector('.react-datepicker__navigation--previous'),
        },
    };
}
"""

_SAMPLE_POPUP_DAY_LABELS_JS = """
() => {
    const mobile = document.getElementById('great-walk-start-date-mobile');
    const trigger = document.querySelector('#great-walk-start-date');
    function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        return el.getBoundingClientRect().width > 0;
    }
    function inMobile(el) {
        return !!(mobile && mobile.contains(el)) || !!el.closest('[id*="-mobile"]');
    }
    function findPopup() {
        const roots = ['.react-datepicker-popper', '.react-datepicker', '[class*="datepicker-popper"]'];
        const popups = [];
        for (const sel of roots) {
            document.querySelectorAll(sel).forEach(el => {
                if (!visible(el) || inMobile(el)) return;
                const rect = el.getBoundingClientRect();
                const triggerRect = trigger ? trigger.getBoundingClientRect() : { bottom: 0 };
                popups.push({ el, distance: Math.max(0, rect.top - triggerRect.bottom) });
            });
        }
        popups.sort((a, b) => a.distance - b.distance);
        return popups[0] ? popups[0].el : null;
    }
    const popup = findPopup();
    if (!popup) return { month_text: null, labels: [] };
    const monthEl = popup.querySelector('.react-datepicker__current-month, [class*="current-month"]');
    const labels = Array.from(popup.querySelectorAll('.react-datepicker__day[role="button"], button[aria-label^="Choose"], button[aria-label^="Not available"]'))
        .filter(el => visible(el) && !inMobile(el))
        .map(el => (el.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim().slice(0, 100))
        .filter(Boolean)
        .slice(0, 15);
    return {
        month_text: monthEl ? monthEl.textContent.replace(/\\s+/g, ' ').trim() : null,
        labels,
    };
}
"""


class PopupPage(Protocol):
    def locator(self, selector: str) -> Any: ...

    def evaluate(self, expression: str, arg: Any = None) -> Any: ...


@dataclass(frozen=True)
class DesktopDatePickerPopup:
    locator: Any
    descriptor: dict[str, Any]


@dataclass(frozen=True)
class ResolvedNavControl:
    candidate: dict[str, Any]
    resolution_method: str


@dataclass(frozen=True)
class CalendarNavigationControls:
    popup: dict[str, Any]
    candidates: list[dict[str, Any]]
    previous: ResolvedNavControl | None
    next: ResolvedNavControl | None
    resolution_method: Literal["semantic", "geometric_fallback", "standard_react", "unresolved"]
    rejection_reasons: list[str]
    popup_selector: str


def _build_popup_locator(page: PopupPage, descriptor: dict[str, Any]) -> Any:
    mobile = page.locator("[id*='-mobile']")
    popup_info = descriptor.get("popup") or {}
    strategy = popup_info.get("strategy") or ".react-datepicker-popper"
    base = page.locator(f"{strategy}:visible").filter(has_not=mobile)
    popup_id = popup_info.get("id")
    if popup_id:
        scoped = page.locator(f"#{popup_id}:visible").filter(has_not=mobile)
        if scoped.count() == 1:
            return scoped.first
    if base.count() == 1:
        return base.first
    return base.first


def resolve_visible_desktop_date_picker(
    page: PopupPage,
    *,
    trigger_selector: str = DATE_TRIGGER_SELECTOR,
) -> DesktopDatePickerPopup:
    raw = page.evaluate(_RESOLVE_DESKTOP_POPUP_JS, {"triggerSelector": trigger_selector})
    if not isinstance(raw, dict):
        raw = {"found": False, "popup_count": 0}
    if not raw.get("found"):
        raise GreatWalkDatePickerError(
            "Could not resolve exactly one visible desktop date-picker popup",
            calendar_diagnostics={
                "date_picker_popup": {
                    "popup_count": raw.get("popup_count", 0),
                    "popups": list(raw.get("popups") or [])[:5],
                    "reason": raw.get("reason"),
                    "trigger_rect": raw.get("trigger_rect"),
                }
            },
        )
    locator = _build_popup_locator(page, raw)
    return DesktopDatePickerPopup(
        locator=locator,
        descriptor=raw,
    )


def discover_popup_navigation_raw(page: PopupPage) -> dict[str, Any]:
    raw = page.evaluate(_DISCOVER_NAVIGATION_JS)
    return raw if isinstance(raw, dict) else {"found": False, "candidates": []}


def _semantic_match(candidate: dict[str, Any], direction: Literal["next", "prev"]) -> bool:
    if direction == "next" and candidate.get("react_next"):
        return True
    if direction == "prev" and candidate.get("react_prev"):
        return True
    accessible = " ".join(
        filter(
            None,
            [
                candidate.get("aria_label") or "",
                candidate.get("title") or "",
                candidate.get("text") or "",
            ],
        )
    )
    pattern = _NAV_SEMANTIC_NEXT if direction == "next" else _NAV_SEMANTIC_PREV
    if accessible.strip():
        return bool(pattern.search(accessible))
    class_name = candidate.get("class") or ""
    if "react-datepicker__navigation" in class_name:
        return bool(pattern.search(class_name))
    return False


def _is_day_cell_candidate(candidate: dict[str, Any]) -> bool:
    aria = candidate.get("aria_label") or ""
    return bool(_DAY_LABEL_HINT.match(aria))


def resolve_calendar_navigation_controls(
    discovery: dict[str, Any],
    *,
    popup_selector: str = ".react-datepicker-popper:visible",
) -> CalendarNavigationControls:
    popup = discovery.get("popup") or {}
    candidates = [
        c
        for c in list(discovery.get("candidates") or [])[:MAX_NAV_CANDIDATES]
        if c.get("visible") and c.get("enabled", True) and not _is_day_cell_candidate(c)
    ]
    rejection_reasons: list[str] = []

    def pick_semantic(direction: Literal["next", "prev"]) -> ResolvedNavControl | None:
        matches = [c for c in candidates if _semantic_match(c, direction)]
        if len(matches) == 1:
            return ResolvedNavControl(candidate=matches[0], resolution_method="semantic")
        if len(matches) > 1:
            rejection_reasons.append(f"ambiguous semantic {direction}: {len(matches)} candidates")
        return None

    previous = pick_semantic("prev")
    next_control = pick_semantic("next")
    method: Literal["semantic", "geometric_fallback", "standard_react", "unresolved"] = "unresolved"

    if previous and next_control:
        method = "semantic"
    else:
        header_candidates = [
            c
            for c in candidates
            if c.get("in_upper_portion")
            and (c.get("near_left_edge") or c.get("near_right_edge"))
        ]
        if len(header_candidates) < 2:
            rejection_reasons.append(
                f"insufficient header edge candidates: {len(header_candidates)}"
            )
        else:
            left = min(header_candidates, key=lambda c: c.get("popup_relative_x", 0))
            right = max(header_candidates, key=lambda c: c.get("popup_relative_x", 0))
            popup_width = (popup.get("rect") or {}).get("width") or 1
            separation = abs(
                (right.get("popup_relative_x") or 0) - (left.get("popup_relative_x") or 0)
            )
            if separation < popup_width * MIN_HORIZONTAL_SEPARATION_RATIO:
                rejection_reasons.append(
                    f"header candidates not sufficiently separated: {separation}px"
                )
            elif left.get("index") == right.get("index"):
                rejection_reasons.append("left and right header candidates collapsed to same element")
            else:
                if not previous:
                    previous = ResolvedNavControl(candidate=left, resolution_method="geometric_fallback")
                if not next_control:
                    next_control = ResolvedNavControl(
                        candidate=right,
                        resolution_method="geometric_fallback",
                    )
                method = "geometric_fallback"

    standard = discovery.get("standard_nav") or {}
    if not previous and standard.get("prev"):
        previous = ResolvedNavControl(
            candidate={
                "react_prev": True,
                "class": "react-datepicker__navigation--previous",
                "tag": "BUTTON",
            },
            resolution_method="standard_react",
        )
    if not next_control and standard.get("next"):
        next_control = ResolvedNavControl(
            candidate={
                "react_next": True,
                "class": "react-datepicker__navigation--next",
                "tag": "BUTTON",
            },
            resolution_method="standard_react",
        )
    if previous and next_control and method == "unresolved":
        method = "standard_react"

    if not previous or not next_control:
        rejection_reasons.append("could not resolve both previous and next controls")

    return CalendarNavigationControls(
        popup=popup,
        candidates=candidates,
        previous=previous,
        next=next_control,
        resolution_method=method,
        rejection_reasons=rejection_reasons,
        popup_selector=popup_selector,
    )


def inspect_date_picker_navigation(page: PopupPage) -> dict[str, Any]:
    popup_binding = resolve_visible_desktop_date_picker(page)
    discovery = discover_popup_navigation_raw(page)
    controls = resolve_calendar_navigation_controls(
        discovery,
        popup_selector=popup_binding.descriptor.get("popup", {}).get("strategy", ""),
    )
    return {
        "date_picker_popup": popup_binding.descriptor.get("popup"),
        "date_picker_navigation": {
            "popup_selector": controls.popup_selector,
            "candidate_count": len(controls.candidates),
            "candidates": controls.candidates[:MAX_NAV_CANDIDATES],
            "resolved_previous": (
                controls.previous.candidate if controls.previous else None
            ),
            "resolved_next": controls.next.candidate if controls.next else None,
            "resolution_method": controls.resolution_method,
            "rejection_reasons": controls.rejection_reasons[:10],
            "standard_nav": discovery.get("standard_nav"),
        },
    }


def sample_popup_day_labels(page: PopupPage) -> tuple[str | None, list[str]]:
    raw = page.evaluate(_SAMPLE_POPUP_DAY_LABELS_JS)
    if not isinstance(raw, dict):
        return None, []
    return raw.get("month_text"), list(raw.get("labels") or [])[:15]


def _candidate_locator(popup_locator: Any, candidate: dict[str, Any]) -> Any:
    if candidate.get("id"):
        return popup_locator.locator(f"#{candidate['id']}")
    aria = candidate.get("aria_label")
    if aria:
        escaped = aria.replace("\\", "\\\\").replace('"', '\\"')
        loc = popup_locator.locator(f'[aria-label="{escaped}"]')
        if loc.count() > 0:
            return loc.first
    if candidate.get("react_next"):
        loc = popup_locator.locator(".react-datepicker__navigation--next")
        if loc.count() > 0:
            return loc.first
    if candidate.get("react_prev"):
        loc = popup_locator.locator(".react-datepicker__navigation--previous")
        if loc.count() > 0:
            return loc.first
    cls = candidate.get("class") or ""
    if cls:
        first_class = cls.split()[0]
        if first_class:
            loc = popup_locator.locator(f".{first_class}")
            if loc.count() > 0:
                return loc.first
    tag = (candidate.get("tag") or "button").lower()
    idx = int(candidate.get("index") or 0)
    return popup_locator.locator(tag).nth(idx)


def click_popup_navigation_control(
    page: PopupPage,
    popup: DesktopDatePickerPopup,
    control: ResolvedNavControl,
    *,
    direction: Literal["next", "prev"],
) -> None:
    discovery = discover_popup_navigation_raw(page)
    controls = resolve_calendar_navigation_controls(discovery)
    resolved = controls.next if direction == "next" else controls.previous
    if resolved is None:
        raise GreatWalkDatePickerError(
            f"Date-picker {direction}-month navigation control is missing",
            calendar_diagnostics={
                "date_picker_navigation": {
                    "candidate_count": len(controls.candidates),
                    "candidates": controls.candidates,
                    "resolution_method": controls.resolution_method,
                    "rejection_reasons": controls.rejection_reasons,
                }
            },
        )
    locator = _candidate_locator(popup.locator, resolved.candidate)
    try:
        if hasattr(locator, "is_enabled") and not locator.is_enabled():
            raise GreatWalkDatePickerError(
                f"Date-picker {direction} navigation control is disabled",
                calendar_diagnostics={"resolved_control": resolved.candidate},
            )
    except Exception:
        pass
    locator.click(timeout=5_000)


def navigation_diagnostics(
    page: PopupPage,
    *,
    target: Any | None = None,
    choose_label: str | None = None,
    unavailable_label: str | None = None,
    navigation_steps: list[dict[str, Any]] | None = None,
    fingerprint_before: dict[str, Any] | None = None,
    fingerprint_after: dict[str, Any] | None = None,
) -> dict[str, Any]:
    discovery = discover_popup_navigation_raw(page)
    controls = resolve_calendar_navigation_controls(discovery)
    month_text, labels = sample_popup_day_labels(page)
    diag: dict[str, Any] = {
        "date_picker_popup": discovery.get("popup"),
        "date_picker_navigation": {
            "popup_selector": controls.popup_selector,
            "candidate_count": len(controls.candidates),
            "candidates": controls.candidates[:MAX_NAV_CANDIDATES],
            "resolved_previous": controls.previous.candidate if controls.previous else None,
            "resolved_next": controls.next.candidate if controls.next else None,
            "resolution_method": controls.resolution_method,
            "rejection_reasons": controls.rejection_reasons,
            "standard_nav": discovery.get("standard_nav"),
        },
        "month_text": month_text,
        "visible_day_labels": labels,
    }
    if choose_label:
        diag["choose_aria_label"] = choose_label
    if unavailable_label:
        diag["unavailable_aria_label"] = unavailable_label
    if navigation_steps is not None:
        diag["navigation_steps"] = navigation_steps
    if fingerprint_before is not None:
        diag["fingerprint_before"] = fingerprint_before
    if fingerprint_after is not None:
        diag["fingerprint_after"] = fingerprint_after
    return diag
