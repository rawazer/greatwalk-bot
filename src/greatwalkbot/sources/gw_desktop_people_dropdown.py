"""Desktop Great Walk People dropdown binding and diagnostics."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from greatwalkbot.infra.errors import GreatWalkPeopleDropdownError
from greatwalkbot.sources.gw_desktop_form import (
    PEOPLE_BUTTON_SELECTOR,
    PEOPLE_LIST_SELECTOR,
    DesktopRootBinding,
    _extract_count,
    click_desktop_control,
    probe_click_readiness,
    read_desktop_form_state,
    wait_for_control_clickable,
)

PEOPLE_VERIFY_TIMEOUT_MS = 5_000
PEOPLE_OPEN_TIMEOUT_MS = 5_000
PEOPLE_MENU_WAIT_TIMEOUT_MS = 5_000
PEOPLE_POLL_INTERVAL_MS = 50
MAX_CONTAINER_CANDIDATES = 10
MAX_OPTION_CANDIDATES = 20

AssociationMethod = Literal[
    "aria",
    "id-pattern",
    "option-id-pattern",
    "geometry",
    "visible-popup",
    "unresolved",
]

ResolutionMethod = Literal[
    "zero_based_option_id",
    "generic_discovery",
]

_DISCOVER_PEOPLE_DROPDOWN_JS = """
({ buttonSelector, listSelector }) => {
    const MAX_CONTAINERS = 10;
    const MAX_OPTIONS = 20;
    const MAX_ANCESTOR = 5;
    const PEOPLE_PREFIX = 'great-walk-people';

    function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function inMobile(el) {
        if (!el) return false;
        const id = el.id || '';
        const cls = (el.className || '').toString();
        if (id.includes('-mobile') || cls.includes('-mobile')) return true;
        return !!el.closest('[id*="-mobile"], [class*="-mobile"]');
    }

    function hasPeoplePrefix(el) {
        const id = el.id || '';
        const cls = (el.className || '').toString();
        return id.includes(PEOPLE_PREFIX) || cls.includes(PEOPLE_PREFIX);
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

    function describe(el) {
        const rect = el.getBoundingClientRect();
        const attrs = {};
        for (const name of el.getAttributeNames()) {
            if (!name.startsWith('data-') && name !== 'value') continue;
            attrs[name] = (el.getAttribute(name) || '').slice(0, 80);
        }
        return {
            tag: el.tagName,
            id: el.id || null,
            class: (el.className || '').toString().slice(0, 120) || null,
            role: el.getAttribute('role'),
            aria_label: (el.getAttribute('aria-label') || '').slice(0, 100) || null,
            title: (el.getAttribute('title') || '').slice(0, 80) || null,
            text: (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 40) || null,
            value: el.getAttribute('value'),
            data_attributes: attrs,
            visible: visible(el),
            enabled: !el.disabled && el.getAttribute('aria-disabled') !== 'true',
            likely_mobile: inMobile(el),
            rect: {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
            },
            ancestors: ancestors(el),
        };
    }

    function isDesktopButton(el) {
        if (!el || el.id !== 'great-walk-people-dropdown-button') return false;
        if (!visible(el) || inMobile(el)) return false;
        const root = el.closest('div[role="search"]');
        if (!root) return false;
        return (root.className || '').toString().includes('themeTopsearch') && visible(root);
    }

    const buttons = Array.from(document.querySelectorAll(buttonSelector)).filter(isDesktopButton);
    const button = buttons.length === 1 ? buttons[0] : (buttons[0] || null);
    if (!button) {
        return {
            found: false,
            reason: 'desktop-people-button-missing',
            button: null,
            containers: [],
            options: [],
            dropdown_open: false,
        };
    }

    const buttonRect = button.getBoundingClientRect();
    const buttonInfo = {
        ...describe(button),
        aria_controls: button.getAttribute('aria-controls'),
        aria_owns: button.getAttribute('aria-owns'),
        aria_expanded: button.getAttribute('aria-expanded'),
        aria_haspopup: button.getAttribute('aria-haspopup'),
        aria_labelledby: button.getAttribute('aria-labelledby'),
    };

    const containers = [];
    const containerSeen = new Set();

    function pushContainer(el, method, extra) {
        if (!el || containers.length >= MAX_CONTAINERS) return;
        if (!visible(el) || inMobile(el)) return;
        const key = (el.id || '') + ':' + el.tagName + ':' + method;
        if (containerSeen.has(key)) return;
        containerSeen.add(key);
        const rect = el.getBoundingClientRect();
        containers.push({
            ...describe(el),
            association_hint: method,
            distance_below_button: Math.round(rect.top - buttonRect.bottom),
            horizontal_overlap: !(rect.right < buttonRect.left || rect.left > buttonRect.right),
            ...extra,
        });
    }

    for (const attr of ['aria-controls', 'aria-owns']) {
        const id = button.getAttribute(attr);
        if (!id) continue;
        const linked = document.getElementById(id);
        if (linked && visible(linked) && !inMobile(linked)) {
            pushContainer(linked, 'aria', { aria_relationship: attr });
        }
    }

    const labelledBy = button.getAttribute('aria-labelledby');
    if (labelledBy) {
        labelledBy.split(/\\s+/).forEach(id => {
            const linked = document.getElementById(id);
            if (linked && visible(linked) && !inMobile(linked)) {
                pushContainer(linked, 'aria', { aria_relationship: 'aria-labelledby' });
            }
        });
    }

    document.querySelectorAll('[id*="great-walk-people"], [class*="great-walk-people"]').forEach(el => {
        if (el === button) return;
        if (!visible(el) || inMobile(el)) return;
        const role = el.getAttribute('role');
        const tag = el.tagName;
        const isContainer = role === 'listbox' || role === 'menu' || role === 'dialog'
            || tag === 'UL' || tag === 'OL'
            || el.id === 'great-walk-people-dropdown-box'
            || (el.id && el.id.endsWith('-dropdown-box'));
        if (isContainer) {
            pushContainer(el, 'id-pattern', {});
        }
    });

    const list = document.getElementById('great-walk-people-dropdown-box')
        || document.querySelector(listSelector);
    if (list && visible(list) && !inMobile(list)) {
        pushContainer(list, 'id-pattern', { list_selector: listSelector });
    }

    document.querySelectorAll('[role="listbox"], [role="menu"], [role="dialog"]').forEach(el => {
        if (!visible(el) || inMobile(el)) return;
        if (hasPeoplePrefix(el) || el.querySelector('[id*="great-walk-people"]')) {
            pushContainer(el, 'visible-popup', {});
        }
    });

    document.querySelectorAll('ul, ol, div').forEach(el => {
        if (containers.length >= MAX_CONTAINERS) return;
        if (!visible(el) || inMobile(el)) return;
        if (!el.querySelector('[id*="great-walk-people"], [role="option"]')) return;
        const rect = el.getBoundingClientRect();
        const below = rect.top >= buttonRect.top - 8;
        const overlap = !(rect.right < buttonRect.left || rect.left > buttonRect.right);
        if (below && overlap) {
            pushContainer(el, 'geometry', {
                distance_below_button: Math.round(rect.top - buttonRect.bottom),
            });
        }
    });

    const options = [];
    const optionSeen = new Set();

    function pushOption(el, hint, containerId) {
        if (options.length >= MAX_OPTIONS) return;
        if (!visible(el) || inMobile(el)) return;
        if (el === button) return;
        if (el.id === 'great-walk-people-dropdown-button') return;
        const text = (el.textContent || '').replace(/\\s+/g, ' ').trim();
        const aria = (el.getAttribute('aria-label') || '').trim();
        if (!text && !aria && !el.id) return;
        const key = (el.id || '') + ':' + text.slice(0, 20);
        if (optionSeen.has(key)) return;
        optionSeen.add(key);
        const rect = el.getBoundingClientRect();
        const below = rect.top >= buttonRect.top - 8;
        const overlap = !(rect.right < buttonRect.left || rect.left > buttonRect.right);
        options.push({
            ...describe(el),
            container_id: containerId || null,
            association_hint: hint,
            below_button: below,
            horizontal_overlap: overlap,
        });
    }

    const containerEls = [];
    containers.forEach(c => {
        if (c.id) {
            const el = document.getElementById(c.id);
            if (el) containerEls.push({ el, hint: c.association_hint });
        }
    });
    if (list && visible(list)) containerEls.push({ el: list, hint: 'id-pattern' });

    for (const { el, hint } of containerEls) {
        el.querySelectorAll('[role="option"], [id*="great-walk-people"], li, button, a, div, span').forEach(child => {
            if (!hasPeoplePrefix(child) && child.getAttribute('role') !== 'option') return;
            pushOption(child, hint, el.id || null);
        });
    }

    document.querySelectorAll('[id*="great-walk-people"]').forEach(el => {
        if (el.id && (el.id.endsWith('-dropdown-box') || el.id.endsWith('-dropdown-button'))) return;
        if (!hasPeoplePrefix(el)) return;
        const rect = el.getBoundingClientRect();
        const below = rect.top >= buttonRect.top - 8;
        const overlap = !(rect.right < buttonRect.left || rect.left > buttonRect.right);
        if (visible(el) && !inMobile(el) && (below || overlap)) {
            pushOption(el, 'option-id-pattern', null);
        }
    });

    const dropdownOpen = button.getAttribute('aria-expanded') === 'true' || options.length > 0;

    return {
        found: true,
        button: buttonInfo,
        containers: containers.slice(0, MAX_CONTAINERS),
        options: options.slice(0, MAX_OPTIONS),
        dropdown_open: dropdownOpen,
    };
}
"""

_PROBE_ZERO_BASED_BINDING_JS = """
({ peopleSize, menuSelector }) => {
    const MAX_ANCESTOR = 5;
    const optionId = `great-walk-people-${peopleSize - 1}`;

    function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function inMobile(el) {
        if (!el) return false;
        const id = el.id || '';
        const cls = (el.className || '').toString();
        if (id.includes('-mobile') || cls.includes('-mobile')) return true;
        return !!el.closest('[id*="-mobile"], [class*="-mobile"]');
    }

    function normalizeText(el) {
        return (el.textContent || '').replace(/\\s+/g, ' ').trim();
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

    function describe(el) {
        const rect = el.getBoundingClientRect();
        return {
            tag: el.tagName,
            id: el.id || null,
            class: (el.className || '').toString().slice(0, 120) || null,
            role: el.getAttribute('role'),
            aria_label: (el.getAttribute('aria-label') || '').slice(0, 100) || null,
            text: normalizeText(el).slice(0, 40) || null,
            visible: visible(el),
            enabled: !el.disabled && el.getAttribute('aria-disabled') !== 'true',
            likely_mobile: inMobile(el),
            rect: {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
            },
            ancestors: ancestors(el),
        };
    }

    const menus = Array.from(document.querySelectorAll(menuSelector))
        .filter(el => visible(el) && !inMobile(el));

    const button = document.getElementById('great-walk-people-dropdown-button');
    const buttonText = button ? normalizeText(button).slice(0, 40) : null;

    let targetOptions = [];
    if (menus.length === 1) {
        const menu = menus[0];
        targetOptions = Array.from(menu.querySelectorAll(`[id="${optionId}"]`))
            .filter(el => el.id === optionId && visible(el) && !inMobile(el) && el.closest(menuSelector) === menu);
        if (targetOptions.length === 0) {
            const direct = menu.querySelector(`#${optionId}`);
            if (direct && direct.id === optionId && visible(direct) && !inMobile(direct)) {
                targetOptions = [direct];
            }
        }
    }

    const target = targetOptions.length === 1 ? describe(targetOptions[0]) : (
        targetOptions.length > 0 ? describe(targetOptions[0]) : null
    );

    return {
        requested_people: peopleSize,
        computed_option_id: optionId,
        menu_count: menus.length,
        menus: menus.slice(0, 3).map(describe),
        target_option_count: targetOptions.length,
        target_option: target,
        observed_target_text: target ? target.text : null,
        menu_open: button ? button.getAttribute('aria-expanded') === 'true' : null,
        trigger_value_before: buttonText,
        button_aria_expanded: button ? button.getAttribute('aria-expanded') : null,
        option_present: targetOptions.length > 0,
    };
}
"""

_WHOLE_NUMBER_RE = re.compile(r"(?<!\d)(\d+)(?!\d)")


class PeopleDropdownPage(Protocol):
    def locator(self, selector: str) -> Any: ...

    def evaluate(self, expression: str, arg: Any = None) -> Any: ...

    def wait_for_timeout(self, timeout: int) -> None: ...

    def screenshot(self, **kwargs: Any) -> bytes: ...


@dataclass(frozen=True)
class PeopleSelectionResult:
    action: Literal["already_matched", "changed_and_verified"]
    requested_people: int
    normalized_value: str | None
    people_dropdown_diagnostics: dict[str, Any] | None = None


def zero_based_option_element_id(people_size: int) -> str:
    """Map requested party size to the live zero-based People option element id."""
    return f"great-walk-people-{people_size - 1}"


def zero_based_option_selector(people_size: int) -> str:
    return f"#{zero_based_option_element_id(people_size)}"


def probe_zero_based_binding(page: PeopleDropdownPage, people_size: int) -> dict[str, Any]:
    raw = page.evaluate(
        _PROBE_ZERO_BASED_BINDING_JS,
        {"peopleSize": people_size, "menuSelector": PEOPLE_LIST_SELECTOR},
    )
    return raw if isinstance(raw, dict) else {"menu_count": 0, "target_option_count": 0}


def build_deterministic_binding_diagnostics(
    probe: dict[str, Any],
    *,
    trigger_value_after: str | None = None,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    diag: dict[str, Any] = {
        "requested_people": probe.get("requested_people"),
        "computed_option_id": probe.get("computed_option_id"),
        "menu_count": probe.get("menu_count"),
        "menus": list(probe.get("menus") or [])[:3],
        "target_option_count": probe.get("target_option_count"),
        "target_option": probe.get("target_option"),
        "observed_target_text": probe.get("observed_target_text"),
        "menu_open": probe.get("menu_open"),
        "trigger_value_before": probe.get("trigger_value_before"),
    }
    if trigger_value_after is not None:
        diag["trigger_value_after"] = trigger_value_after
    if failure_reason:
        diag["failure_reason"] = failure_reason
    return diag


def _semantic_option_score(candidate: dict[str, Any], people_size: int) -> int | None:
    if candidate.get("likely_mobile"):
        return None
    text = (candidate.get("text") or "").strip()
    if text == str(people_size):
        return 1
    if text.lower() == f"{people_size} people":
        return 1
    data_attrs = candidate.get("data_attributes") or {}
    for key in ("data-value", "value"):
        raw = candidate.get(key) or data_attrs.get(key)
        if raw is not None and str(raw).strip() == str(people_size):
            return 2
    aria = candidate.get("aria_label") or ""
    if re.search(rf"(?<!\d){people_size}(?!\d)", aria):
        return 3
    option_id = candidate.get("id") or ""
    if option_id == f"great-walk-people-{people_size - 1}":
        return 4
    if option_id == f"great-walk-people-{people_size}":
        return 5
    return None


def _viable_options(discovery: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        o
        for o in list(discovery.get("options") or [])[:MAX_OPTION_CANDIDATES]
        if o.get("visible") and o.get("enabled", True) and not o.get("likely_mobile")
    ]


def resolve_people_option_container(
    discovery: dict[str, Any],
) -> tuple[dict[str, Any] | None, AssociationMethod, list[str]]:
    containers = list(discovery.get("containers") or [])
    rejection_reasons: list[str] = []
    if not containers:
        rejection_reasons.append("no visible people option containers")
        return None, "unresolved", rejection_reasons

    for hint, method in (
        ("aria", "aria"),
        ("id-pattern", "id-pattern"),
        ("visible-popup", "visible-popup"),
        ("geometry", "geometry"),
    ):
        matches = [c for c in containers if c.get("association_hint") == hint]
        if len(matches) == 1:
            return matches[0], method, rejection_reasons  # type: ignore[return-value]
        if len(matches) > 1:
            rejection_reasons.append(f"ambiguous {hint} containers: {len(matches)}")

    rejection_reasons.append("could not resolve a unique people option container")
    return None, "unresolved", rejection_reasons


def resolve_people_option(
    discovery: dict[str, Any],
    people_size: int,
    *,
    container: dict[str, Any] | None = None,
    association_method: AssociationMethod = "unresolved",
) -> tuple[dict[str, Any] | None, AssociationMethod, list[str]]:
    rejection_reasons: list[str] = []
    options = _viable_options(discovery)

    if container and container.get("id"):
        scoped = [o for o in options if o.get("container_id") == container["id"]]
        if scoped:
            options = scoped

    scored: list[tuple[int, dict[str, Any]]] = []
    for option in options:
        score = _semantic_option_score(option, people_size)
        if score is not None:
            scored.append((score, option))

    if not scored:
        rejection_reasons.append(f"no semantic option match for people={people_size}")
        for option in options:
            rejection_reasons.append(
                f"rejected option id={option.get('id')!r} text={option.get('text')!r}"
            )
        return None, association_method, rejection_reasons

    scored.sort(key=lambda item: (item[0], item[1].get("id") or ""))
    best_score = scored[0][0]
    best = [opt for score, opt in scored if score == best_score]
    if len(best) > 1:
        rejection_reasons.append(
            f"ambiguous people option candidates for {people_size}: {len(best)}"
        )
        for option in best:
            rejection_reasons.append(
                f"ambiguous candidate id={option.get('id')!r} text={option.get('text')!r}"
            )
        return None, association_method, rejection_reasons

    selected = best[0]
    resolved_method = association_method
    if resolved_method == "unresolved":
        hint = selected.get("association_hint") or "option-id-pattern"
        if hint in ("aria", "id-pattern", "geometry", "visible-popup", "option-id-pattern"):
            resolved_method = hint  # type: ignore[assignment]
        else:
            resolved_method = "option-id-pattern"
    return selected, resolved_method, rejection_reasons


def build_people_dropdown_diagnostics(
    discovery: dict[str, Any],
    *,
    requested_people: int,
    current_people: int | None,
    association_method: AssociationMethod,
    selected_candidate: dict[str, Any] | None,
    rejection_reasons: list[str],
    post_click_value: str | None = None,
    before_state: dict[str, Any] | None = None,
    opened_state: dict[str, Any] | None = None,
    after_close_state: dict[str, Any] | None = None,
    click_readiness: dict[str, Any] | None = None,
    open_screenshot_path: str | None = None,
    resolution_method: ResolutionMethod | None = None,
    deterministic_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diag: dict[str, Any] = {
        "button": discovery.get("button"),
        "requested_people": requested_people,
        "current_people": current_people,
        "dropdown_open": discovery.get("dropdown_open"),
        "option_container_candidates": list(discovery.get("containers") or [])[
            :MAX_CONTAINER_CANDIDATES
        ],
        "option_candidates": list(discovery.get("options") or [])[:MAX_OPTION_CANDIDATES],
        "association_method": association_method,
        "selected_candidate": selected_candidate,
        "rejection_reasons": rejection_reasons[:20],
        "post_click_value": post_click_value,
    }
    if resolution_method is not None:
        diag["resolution_method"] = resolution_method
    if deterministic_binding is not None:
        diag["deterministic_binding"] = deterministic_binding
    if before_state is not None:
        diag["before_open"] = before_state
    if opened_state is not None:
        diag["opened"] = opened_state
    if after_close_state is not None:
        diag["after_close"] = after_close_state
    if click_readiness is not None:
        diag["click_readiness"] = click_readiness
    if open_screenshot_path:
        diag["open_screenshot_path"] = open_screenshot_path
    return diag


def discover_people_dropdown_raw(page: PeopleDropdownPage) -> dict[str, Any]:
    raw = page.evaluate(
        _DISCOVER_PEOPLE_DROPDOWN_JS,
        {
            "buttonSelector": PEOPLE_BUTTON_SELECTOR,
            "listSelector": PEOPLE_LIST_SELECTOR,
        },
    )
    return raw if isinstance(raw, dict) else {"found": False, "containers": [], "options": []}


def _summarize_discovery(discovery: dict[str, Any]) -> dict[str, Any]:
    button = discovery.get("button") or {}
    return {
        "dropdown_open": discovery.get("dropdown_open"),
        "button_aria_expanded": button.get("aria_expanded"),
        "button_text": button.get("text"),
        "container_count": len(discovery.get("containers") or []),
        "option_count": len(discovery.get("options") or []),
        "button_rect": button.get("rect"),
    }


def _wait_for_zero_based_menu(
    page: PeopleDropdownPage,
    *,
    timeout_ms: int = PEOPLE_MENU_WAIT_TIMEOUT_MS,
) -> dict[str, Any]:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    last = probe_zero_based_binding(page, people_size=1)
    while time.monotonic() < deadline:
        last = probe_zero_based_binding(page, people_size=1)
        if last.get("menu_count") == 1:
            return last
        page.wait_for_timeout(PEOPLE_POLL_INTERVAL_MS)
    return last


def _evaluate_zero_based_binding(
    probe: dict[str, Any],
    people_size: int,
) -> tuple[Literal["matched", "absent", "failed"], list[str]]:
    reasons: list[str] = []
    menu_count = int(probe.get("menu_count") or 0)
    if menu_count > 1:
        reasons.append(f"ambiguous visible people menus: {menu_count}")
        return "failed", reasons
    if menu_count == 0:
        reasons.append("visible people menu not found")
        return "absent", reasons

    target_count = int(probe.get("target_option_count") or 0)
    if target_count == 0:
        reasons.append(
            f"deterministic option {probe.get('computed_option_id')!r} not found in visible menu"
        )
        return "absent", reasons

    if target_count > 1:
        reasons.append(f"ambiguous deterministic people options: {target_count}")
        return "failed", reasons

    observed = (probe.get("observed_target_text") or "").strip()
    if observed != str(people_size):
        reasons.append(
            f"deterministic option text mismatch: expected {people_size!r}, observed {observed!r}"
        )
        return "failed", reasons

    target = probe.get("target_option") or {}
    if not target.get("visible", True):
        reasons.append("deterministic option not visible")
        return "failed", reasons
    if target.get("likely_mobile"):
        reasons.append("deterministic option is mobile")
        return "failed", reasons
    if not target.get("enabled", True):
        reasons.append("deterministic option disabled")
        return "failed", reasons

    return "matched", reasons


def _zero_based_option_locator(page: PeopleDropdownPage, people_size: int) -> Any:
    mobile = page.locator("[id*='-mobile']")
    menu = page.locator(PEOPLE_LIST_SELECTOR).filter(has_not=mobile)
    if menu.count() != 1:
        raise GreatWalkPeopleDropdownError(
            f"Expected exactly one visible desktop People menu, found {menu.count()}",
        )
    option_id = zero_based_option_element_id(people_size)
    option = menu.locator(f"#{option_id}").filter(has_not=mobile)
    if option.count() != 1:
        raise GreatWalkPeopleDropdownError(
            f"Expected exactly one visible desktop People option {option_id!r}, found {option.count()}",
        )
    return option.first


def _wait_for_people_dropdown_open(
    page: PeopleDropdownPage,
    *,
    timeout_ms: int = PEOPLE_OPEN_TIMEOUT_MS,
) -> dict[str, Any]:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    last = discover_people_dropdown_raw(page)
    while time.monotonic() < deadline:
        last = discover_people_dropdown_raw(page)
        button = last.get("button") or {}
        if last.get("dropdown_open") or button.get("aria_expanded") == "true":
            return last
        if _viable_options(last):
            return last
        page.wait_for_timeout(PEOPLE_POLL_INTERVAL_MS)
    return last


def _close_people_dropdown_if_open(
    page: PeopleDropdownPage,
    binding: DesktopRootBinding,
    discovery: dict[str, Any],
    *,
    root_change: dict[str, Any] | None = None,
) -> None:
    button = discovery.get("button") or {}
    if button.get("aria_expanded") == "true" or discovery.get("dropdown_open"):
        click_desktop_control(
            page,
            binding,
            PEOPLE_BUTTON_SELECTOR,
            "people",
            root_change=root_change,
        )
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            closed = discover_people_dropdown_raw(page)
            if not closed.get("dropdown_open") and not _viable_options(closed):
                btn = closed.get("button") or {}
                if btn.get("aria_expanded") != "true":
                    return
            page.wait_for_timeout(PEOPLE_POLL_INTERVAL_MS)


def inspect_people_dropdown(
    page: PeopleDropdownPage,
    binding: DesktopRootBinding,
    *,
    root_change: dict[str, Any] | None = None,
    screenshot_path: Path | None = None,
) -> dict[str, Any]:
    """Open the desktop People dropdown read-only and capture bounded evidence."""
    state = read_desktop_form_state(page, binding)
    people_ctrl = state.get("people_control") or {}
    current = _extract_count(people_ctrl.get("visible_text"))

    before_discovery = discover_people_dropdown_raw(page)
    before_state = _summarize_discovery(before_discovery)
    click_readiness = probe_click_readiness(page, binding, PEOPLE_BUTTON_SELECTOR)

    wait_for_control_clickable(
        page,
        binding,
        PEOPLE_BUTTON_SELECTOR,
        "people",
        root_change=root_change,
    )
    click_desktop_control(
        page,
        binding,
        PEOPLE_BUTTON_SELECTOR,
        "people",
        root_change=root_change,
    )

    opened_discovery = _wait_for_people_dropdown_open(page)
    opened_state = _summarize_discovery(opened_discovery)

    open_screenshot: str | None = None
    if screenshot_path is not None:
        try:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot_path), full_page=False, timeout=5_000)
            open_screenshot = str(screenshot_path)
        except Exception:
            open_screenshot = None

    container, association_method, container_reasons = resolve_people_option_container(
        opened_discovery
    )
    _, resolved_method, option_reasons = resolve_people_option(
        opened_discovery,
        people_size=2,
        container=container,
        association_method=association_method,
    )

    _close_people_dropdown_if_open(page, binding, opened_discovery, root_change=root_change)
    after_discovery = discover_people_dropdown_raw(page)
    after_close_state = _summarize_discovery(after_discovery)

    return {
        "people_dropdown": build_people_dropdown_diagnostics(
            opened_discovery,
            requested_people=current or 0,
            current_people=current,
            association_method=resolved_method,
            selected_candidate=None,
            rejection_reasons=container_reasons + option_reasons,
            before_state=before_state,
            opened_state=opened_state,
            after_close_state=after_close_state,
            click_readiness=click_readiness,
            open_screenshot_path=open_screenshot,
        )
    }


def _option_locator(page: PeopleDropdownPage, candidate: dict[str, Any]) -> Any:
    mobile = page.locator("[id*='-mobile']")
    if candidate.get("id"):
        loc = page.locator(f"#{candidate['id']}").filter(has_not=mobile)
        if loc.count() == 1:
            return loc.first
        if loc.count() > 1:
            visible_loc = page.locator(f"#{candidate['id']}:visible").filter(has_not=mobile)
            if visible_loc.count() >= 1:
                return visible_loc.first
    aria = candidate.get("aria_label")
    if aria:
        escaped = aria.replace("\\", "\\\\").replace('"', '\\"')
        loc = page.locator(f'[aria-label="{escaped}"]').filter(has_not=mobile)
        if loc.count() == 1:
            return loc.first
    text = (candidate.get("text") or "").strip()
    if text:
        if hasattr(page, "get_by_text"):
            loc = page.get_by_text(text, exact=True).filter(has_not=mobile)
        else:
            loc = page.locator(f'text="{text}"').filter(has_not=mobile)
        if loc.count() == 1:
            return loc.first
    cls = candidate.get("class") or ""
    if cls:
        first_class = cls.split()[0]
        if first_class and "mobile" not in first_class:
            loc = page.locator(f".{first_class}").filter(has_not=mobile)
            if loc.count() == 1:
                return loc.first
    raise GreatWalkPeopleDropdownError(
        f"Could not build locator for people option {candidate.get('id')!r}",
        people_dropdown_diagnostics={"selected_candidate": candidate},
    )


def _wait_for_people_value(
    page: PeopleDropdownPage,
    binding: DesktopRootBinding,
    people_size: int,
    *,
    timeout_ms: int = PEOPLE_VERIFY_TIMEOUT_MS,
) -> tuple[bool, str | None]:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    last_value: str | None = None
    while time.monotonic() < deadline:
        state = read_desktop_form_state(page, binding, people_size=people_size)
        people_ctrl = state.get("people_control") or {}
        last_value = people_ctrl.get("normalized_value")
        count = _extract_count(people_ctrl.get("visible_text"))
        value_ok = people_ctrl.get("matches_requested") or count == people_size
        expanded = people_ctrl.get("aria_expanded")
        menu_closed = expanded == "false" or expanded is False
        if value_ok and menu_closed:
            return True, last_value or str(people_size)
        page.wait_for_timeout(PEOPLE_POLL_INTERVAL_MS)
    return False, last_value


def _discovery_from_zero_based_probe(probe: dict[str, Any]) -> dict[str, Any]:
    target = probe.get("target_option")
    return {
        "button": {
            "text": probe.get("trigger_value_before"),
            "aria_expanded": probe.get("button_aria_expanded"),
        },
        "dropdown_open": probe.get("menu_open"),
        "containers": list(probe.get("menus") or []),
        "options": [target] if target else [],
    }


def _select_via_generic_discovery(
    page: PeopleDropdownPage,
    binding: DesktopRootBinding,
    people_size: int,
    current: int | None,
    *,
    root_change: dict[str, Any] | None = None,
) -> PeopleSelectionResult:
    discovery = _wait_for_people_dropdown_open(page)
    selected, association_method, rejection_reasons = _resolve_people_selection(
        discovery,
        people_size,
    )

    if selected is None:
        diagnostics = build_people_dropdown_diagnostics(
            discovery,
            requested_people=people_size,
            current_people=current,
            association_method=association_method,
            selected_candidate=None,
            rejection_reasons=rejection_reasons,
            opened_state=_summarize_discovery(discovery),
            resolution_method="generic_discovery",
        )
        raise GreatWalkPeopleDropdownError(
            f"Could not resolve desktop People option for {people_size}",
            people_dropdown_diagnostics=diagnostics,
        )

    rediscovery = discover_people_dropdown_raw(page)
    selected, association_method, rejection_reasons = _resolve_people_selection(
        rediscovery,
        people_size,
    )
    if selected is None:
        diagnostics = build_people_dropdown_diagnostics(
            rediscovery,
            requested_people=people_size,
            current_people=current,
            association_method=association_method,
            selected_candidate=None,
            rejection_reasons=rejection_reasons
            + ["option could not be re-resolved immediately before click"],
            opened_state=_summarize_discovery(rediscovery),
            resolution_method="generic_discovery",
        )
        raise GreatWalkPeopleDropdownError(
            f"Could not re-resolve desktop People option for {people_size} before click",
            people_dropdown_diagnostics=diagnostics,
        )

    option_locator = _option_locator(page, selected)
    try:
        if hasattr(option_locator, "is_enabled") and not option_locator.is_enabled():
            raise GreatWalkPeopleDropdownError(
                f"Desktop People option for {people_size} is disabled",
                people_dropdown_diagnostics=build_people_dropdown_diagnostics(
                    rediscovery,
                    requested_people=people_size,
                    current_people=current,
                    association_method=association_method,
                    selected_candidate=selected,
                    rejection_reasons=rejection_reasons + ["selected option disabled"],
                    resolution_method="generic_discovery",
                ),
            )
    except GreatWalkPeopleDropdownError:
        raise
    except Exception:
        pass

    option_locator.click(timeout=5_000)
    verified, post_value = _wait_for_people_value(page, binding, people_size)
    diagnostics = build_people_dropdown_diagnostics(
        rediscovery,
        requested_people=people_size,
        current_people=current,
        association_method=association_method,
        selected_candidate=selected,
        rejection_reasons=rejection_reasons,
        post_click_value=post_value,
        opened_state=_summarize_discovery(rediscovery),
        resolution_method="generic_discovery",
    )

    if not verified:
        raise GreatWalkPeopleDropdownError(
            f"Desktop People control did not verify as {people_size} after selection",
            people_dropdown_diagnostics=diagnostics,
        )

    return PeopleSelectionResult(
        action="changed_and_verified",
        requested_people=people_size,
        normalized_value=post_value,
        people_dropdown_diagnostics=diagnostics,
    )


def _resolve_people_selection(
    discovery: dict[str, Any],
    people_size: int,
) -> tuple[dict[str, Any] | None, AssociationMethod, list[str]]:
    container, association_method, container_reasons = resolve_people_option_container(
        discovery
    )
    selected, resolved_method, option_reasons = resolve_people_option(
        discovery,
        people_size,
        container=container,
        association_method=association_method,
    )
    return selected, resolved_method, container_reasons + option_reasons


def select_desktop_people(
    page: PeopleDropdownPage,
    people_size: int,
    binding: DesktopRootBinding | None = None,
    *,
    root_change: dict[str, Any] | None = None,
) -> PeopleSelectionResult:
    """Select and verify desktop party size in the custom People dropdown."""
    from greatwalkbot.sources.gw_desktop_form import resolve_desktop_great_walk_root

    binding = binding or resolve_desktop_great_walk_root(page)

    state = read_desktop_form_state(page, binding, people_size=people_size)
    people_ctrl = state.get("people_control") or {}
    current = _extract_count(people_ctrl.get("visible_text"))
    if people_ctrl.get("matches_requested"):
        return PeopleSelectionResult(
            action="already_matched",
            requested_people=people_size,
            normalized_value=people_ctrl.get("normalized_value"),
        )

    wait_for_control_clickable(
        page,
        binding,
        PEOPLE_BUTTON_SELECTOR,
        "people",
        root_change=root_change,
    )
    click_desktop_control(
        page,
        binding,
        PEOPLE_BUTTON_SELECTOR,
        "people",
        root_change=root_change,
    )

    _wait_for_zero_based_menu(page)
    probe = probe_zero_based_binding(page, people_size)
    status, rejection_reasons = _evaluate_zero_based_binding(probe, people_size)

    if status == "failed":
        diagnostics = build_people_dropdown_diagnostics(
            _discovery_from_zero_based_probe(probe),
            requested_people=people_size,
            current_people=current,
            association_method="id-pattern",
            selected_candidate=probe.get("target_option"),
            rejection_reasons=rejection_reasons,
            opened_state={
                "dropdown_open": probe.get("menu_open"),
                "button_aria_expanded": probe.get("button_aria_expanded"),
                "button_text": probe.get("trigger_value_before"),
            },
            resolution_method="zero_based_option_id",
            deterministic_binding=build_deterministic_binding_diagnostics(
                probe,
                failure_reason=rejection_reasons[0] if rejection_reasons else None,
            ),
        )
        raise GreatWalkPeopleDropdownError(
            f"Deterministic desktop People binding failed for {people_size}",
            people_dropdown_diagnostics=diagnostics,
        )

    if status == "matched":
        probe = probe_zero_based_binding(page, people_size)
        status, rejection_reasons = _evaluate_zero_based_binding(probe, people_size)
        if status != "matched":
            diagnostics = build_people_dropdown_diagnostics(
                _discovery_from_zero_based_probe(probe),
                requested_people=people_size,
                current_people=current,
                association_method="id-pattern",
                selected_candidate=probe.get("target_option"),
                rejection_reasons=rejection_reasons
                + ["deterministic option could not be re-resolved immediately before click"],
                resolution_method="zero_based_option_id",
                deterministic_binding=build_deterministic_binding_diagnostics(
                    probe,
                    failure_reason=rejection_reasons[0] if rejection_reasons else None,
                ),
            )
            raise GreatWalkPeopleDropdownError(
                f"Could not re-resolve deterministic desktop People option for {people_size}",
                people_dropdown_diagnostics=diagnostics,
            )

        option_locator = _zero_based_option_locator(page, people_size)
        try:
            if hasattr(option_locator, "is_enabled") and not option_locator.is_enabled():
                raise GreatWalkPeopleDropdownError(
                    f"Desktop People option for {people_size} is disabled",
                    people_dropdown_diagnostics=build_people_dropdown_diagnostics(
                        _discovery_from_zero_based_probe(probe),
                        requested_people=people_size,
                        current_people=current,
                        association_method="id-pattern",
                        selected_candidate=probe.get("target_option"),
                        rejection_reasons=["deterministic option disabled"],
                        resolution_method="zero_based_option_id",
                        deterministic_binding=build_deterministic_binding_diagnostics(probe),
                    ),
                )
        except GreatWalkPeopleDropdownError:
            raise
        except Exception:
            pass

        option_locator.click(timeout=5_000)
        verified, post_value = _wait_for_people_value(page, binding, people_size)
        after_probe = probe_zero_based_binding(page, people_size)
        diagnostics = build_people_dropdown_diagnostics(
            _discovery_from_zero_based_probe(after_probe),
            requested_people=people_size,
            current_people=current,
            association_method="id-pattern",
            selected_candidate=probe.get("target_option"),
            rejection_reasons=[],
            post_click_value=post_value,
            opened_state={
                "dropdown_open": probe.get("menu_open"),
                "button_aria_expanded": probe.get("button_aria_expanded"),
                "button_text": probe.get("trigger_value_before"),
            },
            resolution_method="zero_based_option_id",
            deterministic_binding=build_deterministic_binding_diagnostics(
                probe,
                trigger_value_after=post_value,
            ),
        )
        if not verified:
            diagnostics["deterministic_binding"] = build_deterministic_binding_diagnostics(
                after_probe,
                trigger_value_after=post_value,
                failure_reason="trigger did not verify after deterministic selection",
            )
            raise GreatWalkPeopleDropdownError(
                f"Desktop People control did not verify as {people_size} after selection",
                people_dropdown_diagnostics=diagnostics,
            )
        return PeopleSelectionResult(
            action="changed_and_verified",
            requested_people=people_size,
            normalized_value=post_value,
            people_dropdown_diagnostics=diagnostics,
        )

    return _select_via_generic_discovery(
        page,
        binding,
        people_size,
        current,
        root_change=root_change,
    )
