"""Desktop Great Walk People dropdown binding and diagnostics."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from greatwalkbot.infra.errors import GreatWalkPeopleDropdownError
from greatwalkbot.sources.gw_desktop_form import (
    PEOPLE_BUTTON_SELECTOR,
    PEOPLE_LIST_SELECTOR,
    DesktopRootBinding,
    _extract_count,
    click_desktop_control,
    read_desktop_form_state,
    wait_for_control_clickable,
)

PEOPLE_VERIFY_TIMEOUT_MS = 5_000
PEOPLE_POLL_INTERVAL_MS = 50
MAX_CONTAINER_CANDIDATES = 10
MAX_OPTION_CANDIDATES = 20
MAX_ANCESTOR_DEPTH = 5

AssociationMethod = Literal[
    "aria",
    "visible-popup",
    "geometry",
    "id-pattern",
    "unresolved",
]

_DISCOVER_PEOPLE_DROPDOWN_JS = """
({ rootSelector, buttonSelector, listSelector }) => {
    const MAX_CONTAINERS = 10;
    const MAX_OPTIONS = 20;
    const MAX_ANCESTOR = 5;

    function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function inMobile(el) {
        if (!el) return false;
        if (el.id && el.id.includes('-mobile')) return true;
        return !!el.closest('[id*="-mobile"]');
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

    const roots = Array.from(document.querySelectorAll('div[role="search"]'))
        .filter(el => (el.className || '').toString().includes('themeTopsearch') && visible(el));
    const root = roots.length === 1 ? roots[0] : null;
    if (!root) {
        return { found: false, reason: 'desktop-root-missing', button: null, containers: [], options: [] };
    }

    const button = root.querySelector(buttonSelector);
    if (!button || !visible(button) || inMobile(button)) {
        return { found: false, reason: 'people-button-missing', button: null, containers: [], options: [] };
    }

    const buttonRect = button.getBoundingClientRect();
    const buttonInfo = {
        ...describe(button),
        aria_controls: button.getAttribute('aria-controls'),
        aria_owns: button.getAttribute('aria-owns'),
        aria_expanded: button.getAttribute('aria-expanded'),
        aria_haspopup: button.getAttribute('aria-haspopup'),
    };

    const containers = [];
    const seen = new Set();

    function pushContainer(el, method, extra) {
        if (!el || containers.length >= MAX_CONTAINERS) return;
        if (!visible(el) || inMobile(el)) return;
        const key = (el.id || '') + ':' + el.tagName;
        if (seen.has(key)) return;
        seen.add(key);
        const rect = el.getBoundingClientRect();
        containers.push({
            ...describe(el),
            association_hint: method,
            distance_below_button: Math.round(rect.top - buttonRect.bottom),
            root_relative_x: Math.round(rect.left - root.getBoundingClientRect().left),
            ...extra,
        });
    }

    for (const attr of ['aria-controls', 'aria-owns']) {
        const id = button.getAttribute(attr);
        if (id) {
            const linked = document.getElementById(id);
            if (linked && root.contains(linked)) {
                pushContainer(linked, 'aria', { aria_relationship: attr });
            }
        }
    }

    const list = root.querySelector(listSelector);
    if (list) {
        pushContainer(list, 'id-pattern', { list_selector: listSelector });
    }

    root.querySelectorAll('[role="listbox"], [role="menu"], [role="dialog"]').forEach(el => {
        if (visible(el) && !inMobile(el)) {
            pushContainer(el, 'visible-popup', {});
        }
    });

    root.querySelectorAll('ul, ol, div').forEach(el => {
        if (containers.length >= MAX_CONTAINERS) return;
        if (!visible(el) || inMobile(el)) return;
        const rect = el.getBoundingClientRect();
        const below = rect.top >= buttonRect.top - 5;
        const near = Math.abs(rect.left - buttonRect.left) < 250;
        const hasOptions = el.querySelector('[role="option"], [id^="great-walk-people"]');
        if (below && near && hasOptions) {
            pushContainer(el, 'geometry', {
                distance_below_button: Math.round(rect.top - buttonRect.bottom),
            });
        }
    });

    const options = [];
    const optionSeen = new Set();
    const containerEls = containers.map(c => c.id ? document.getElementById(c.id) : null).filter(Boolean);
    if (list && visible(list)) containerEls.push(list);

    for (const container of containerEls) {
        if (!container) continue;
        container.querySelectorAll(
            '[role="option"], [id^="great-walk-people"], li, button, a, div'
        ).forEach(el => {
            if (options.length >= MAX_OPTIONS) return;
            if (!visible(el) || inMobile(el)) return;
            const text = (el.textContent || '').replace(/\\s+/g, ' ').trim();
            if (!text && !el.getAttribute('aria-label') && !el.id) return;
            const key = (el.id || '') + ':' + text.slice(0, 20);
            if (optionSeen.has(key)) return;
            optionSeen.add(key);
            const rect = el.getBoundingClientRect();
            options.push({
                ...describe(el),
                container_id: container.id || null,
                root_relative_x: Math.round(rect.left - root.getBoundingClientRect().left),
                root_relative_y: Math.round(rect.top - root.getBoundingClientRect().top),
            });
        });
    }

    return {
        found: true,
        button: buttonInfo,
        containers: containers.slice(0, MAX_CONTAINERS),
        options: options.slice(0, MAX_OPTIONS),
        root_selector: rootSelector,
    };
}
"""

_WHOLE_NUMBER_RE = re.compile(r"(?<!\d)(\d+)(?!\d)")


class PeopleDropdownPage(Protocol):
    def locator(self, selector: str) -> Any: ...

    def evaluate(self, expression: str, arg: Any = None) -> Any: ...

    def wait_for_timeout(self, timeout: int) -> None: ...


@dataclass(frozen=True)
class PeopleSelectionResult:
    action: Literal["already_matched", "changed_and_verified"]
    requested_people: int
    normalized_value: str | None
    people_dropdown_diagnostics: dict[str, Any] | None = None


def _people_value_from_candidate(candidate: dict[str, Any]) -> int | None:
    data_attrs = candidate.get("data_attributes") or {}
    for key in ("data-value", "value"):
        raw = candidate.get(key) or data_attrs.get(key)
        if raw is not None and str(raw).strip().isdigit():
            return int(str(raw).strip())
    for key, raw in data_attrs.items():
        if "value" in key.lower() and str(raw).strip().isdigit():
            return int(str(raw).strip())
    text = candidate.get("text") or ""
    if text.strip().isdigit():
        return int(text.strip())
    match = _WHOLE_NUMBER_RE.search(text)
    if match:
        return int(match.group(1))
    aria = candidate.get("aria_label") or ""
    match = _WHOLE_NUMBER_RE.search(aria)
    if match:
        return int(match.group(1))
    option_id = candidate.get("id") or ""
    id_match = re.search(r"people[-_]?(\d+)", option_id, re.IGNORECASE)
    if id_match:
        return int(id_match.group(1))
    return None


def _semantic_option_score(candidate: dict[str, Any], people_size: int) -> int | None:
    if candidate.get("likely_mobile"):
        return None
    data_attrs = candidate.get("data_attributes") or {}
    for key in ("data-value", "value"):
        raw = candidate.get(key) or data_attrs.get(key)
        if raw is not None and str(raw).strip() == str(people_size):
            return 1
    text = (candidate.get("text") or "").strip()
    if text == str(people_size):
        return 2
    if text.lower() == f"{people_size} people":
        return 2
    aria = candidate.get("aria_label") or ""
    if re.search(rf"(?<!\d){people_size}(?!\d)", aria):
        return 3
    option_id = candidate.get("id") or ""
    if option_id == f"great-walk-people-{people_size}":
        return 4
    value = _people_value_from_candidate(candidate)
    if value == people_size:
        return 5
    return None


def resolve_people_option_container(
    discovery: dict[str, Any],
) -> tuple[dict[str, Any] | None, AssociationMethod, list[str]]:
    containers = list(discovery.get("containers") or [])
    rejection_reasons: list[str] = []
    if not containers:
        rejection_reasons.append("no visible people option containers")
        return None, "unresolved", rejection_reasons

    aria_matches = [c for c in containers if c.get("association_hint") == "aria"]
    if len(aria_matches) == 1:
        return aria_matches[0], "aria", rejection_reasons
    if len(aria_matches) > 1:
        rejection_reasons.append(f"ambiguous aria-linked containers: {len(aria_matches)}")

    popup_matches = [c for c in containers if c.get("association_hint") == "visible-popup"]
    if len(popup_matches) == 1:
        return popup_matches[0], "visible-popup", rejection_reasons
    if len(popup_matches) > 1:
        rejection_reasons.append(f"ambiguous visible popup containers: {len(popup_matches)}")

    id_matches = [c for c in containers if c.get("association_hint") == "id-pattern"]
    if len(id_matches) == 1:
        return id_matches[0], "id-pattern", rejection_reasons

    geometry_matches = [c for c in containers if c.get("association_hint") == "geometry"]
    if len(geometry_matches) == 1:
        return geometry_matches[0], "geometry", rejection_reasons
    if len(geometry_matches) > 1:
        rejection_reasons.append(f"ambiguous geometry containers: {len(geometry_matches)}")

    rejection_reasons.append("could not resolve a unique people option container")
    return None, "unresolved", rejection_reasons


def resolve_people_option(
    discovery: dict[str, Any],
    people_size: int,
    *,
    container: dict[str, Any] | None = None,
    association_method: AssociationMethod = "unresolved",
) -> tuple[dict[str, Any] | None, list[str]]:
    rejection_reasons: list[str] = []
    options = [
        o
        for o in list(discovery.get("options") or [])[:MAX_OPTION_CANDIDATES]
        if o.get("visible") and o.get("enabled", True) and not o.get("likely_mobile")
    ]
    if container and container.get("id"):
        container_id = container["id"]
        options = [o for o in options if o.get("container_id") == container_id] or options

    scored: list[tuple[int, dict[str, Any]]] = []
    for option in options:
        score = _semantic_option_score(option, people_size)
        if score is not None:
            scored.append((score, option))

    if not scored:
        rejection_reasons.append(f"no semantic option match for people={people_size}")
        return None, rejection_reasons

    scored.sort(key=lambda item: item[0])
    best_score = scored[0][0]
    best = [opt for score, opt in scored if score == best_score]
    if len(best) > 1:
        rejection_reasons.append(
            f"ambiguous people option candidates for {people_size}: {len(best)}"
        )
        return None, rejection_reasons
    if association_method == "unresolved":
        rejection_reasons.append("people option container unresolved")
        return None, rejection_reasons
    return best[0], rejection_reasons


def build_people_dropdown_diagnostics(
    discovery: dict[str, Any],
    *,
    requested_people: int,
    current_people: int | None,
    association_method: AssociationMethod,
    selected_candidate: dict[str, Any] | None,
    rejection_reasons: list[str],
    post_click_value: str | None = None,
) -> dict[str, Any]:
    return {
        "button": discovery.get("button"),
        "requested_people": requested_people,
        "current_people": current_people,
        "option_container_candidates": list(discovery.get("containers") or [])[
            :MAX_CONTAINER_CANDIDATES
        ],
        "option_candidates": list(discovery.get("options") or [])[:MAX_OPTION_CANDIDATES],
        "association_method": association_method,
        "selected_candidate": selected_candidate,
        "rejection_reasons": rejection_reasons[:10],
        "post_click_value": post_click_value,
    }


def discover_people_dropdown_raw(page: PeopleDropdownPage) -> dict[str, Any]:
    raw = page.evaluate(
        _DISCOVER_PEOPLE_DROPDOWN_JS,
        {
            "rootSelector": 'div[role="search"].themeTopsearch',
            "buttonSelector": PEOPLE_BUTTON_SELECTOR,
            "listSelector": PEOPLE_LIST_SELECTOR,
        },
    )
    return raw if isinstance(raw, dict) else {"found": False, "containers": [], "options": []}


def inspect_people_dropdown(
    page: PeopleDropdownPage,
    binding: DesktopRootBinding,
    *,
    root_change: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Open the desktop People dropdown read-only and capture bounded evidence."""
    state = read_desktop_form_state(page, binding)
    people_ctrl = state.get("people_control") or {}
    current = _extract_count(people_ctrl.get("visible_text"))

    click_desktop_control(
        page,
        binding,
        PEOPLE_BUTTON_SELECTOR,
        "people",
        root_change=root_change,
    )
    discovery = discover_people_dropdown_raw(page)
    container, association_method, container_reasons = resolve_people_option_container(
        discovery
    )
    _, option_reasons = resolve_people_option(
        discovery,
        people_size=current or 0,
        container=container,
        association_method=association_method,
    )
    return {
        "people_dropdown": build_people_dropdown_diagnostics(
            discovery,
            requested_people=current or 0,
            current_people=current,
            association_method=association_method,
            selected_candidate=None,
            rejection_reasons=container_reasons + option_reasons,
        )
    }


def _option_locator(root_locator: Any, candidate: dict[str, Any]) -> Any:
    if candidate.get("id"):
        loc = root_locator.locator(f"#{candidate['id']}")
        if loc.count() > 0:
            return loc.first
    aria = candidate.get("aria_label")
    if aria:
        escaped = aria.replace("\\", "\\\\").replace('"', '\\"')
        loc = root_locator.locator(f'[aria-label="{escaped}"]')
        if loc.count() > 0:
            return loc.first
    text = candidate.get("text")
    if text:
        loc = root_locator.locator(f'text="{text}"')
        if hasattr(root_locator, "get_by_text"):
            loc = root_locator.get_by_text(text, exact=True)
        if loc.count() > 0:
            return loc.first
    cls = candidate.get("class") or ""
    if cls:
        first_class = cls.split()[0]
        if first_class:
            loc = root_locator.locator(f".{first_class}")
            if loc.count() == 1:
                return loc.first
    tag = (candidate.get("tag") or "div").lower()
    return root_locator.locator(tag).first


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
        if people_ctrl.get("matches_requested"):
            return True, people_ctrl.get("normalized_value")
        last_value = people_ctrl.get("normalized_value")
        expanded = people_ctrl.get("aria_expanded")
        if expanded == "false":
            count = _extract_count(people_ctrl.get("visible_text"))
            if count == people_size:
                return True, str(count)
        page.wait_for_timeout(PEOPLE_POLL_INTERVAL_MS)
    return False, last_value


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

    discovery = discover_people_dropdown_raw(page)
    container, association_method, container_reasons = resolve_people_option_container(
        discovery
    )
    selected, option_reasons = resolve_people_option(
        discovery,
        people_size,
        container=container,
        association_method=association_method,
    )
    rejection_reasons = container_reasons + option_reasons

    if selected is None:
        diagnostics = build_people_dropdown_diagnostics(
            discovery,
            requested_people=people_size,
            current_people=current,
            association_method=association_method,
            selected_candidate=None,
            rejection_reasons=rejection_reasons,
        )
        raise GreatWalkPeopleDropdownError(
            f"Could not resolve desktop People option for {people_size}",
            people_dropdown_diagnostics=diagnostics,
        )

    root_locator = page.locator(binding.selector)
    option_locator = _option_locator(root_locator, selected)
    try:
        if hasattr(option_locator, "is_enabled") and not option_locator.is_enabled():
            raise GreatWalkPeopleDropdownError(
                f"Desktop People option for {people_size} is disabled",
                people_dropdown_diagnostics=build_people_dropdown_diagnostics(
                    discovery,
                    requested_people=people_size,
                    current_people=current,
                    association_method=association_method,
                    selected_candidate=selected,
                    rejection_reasons=rejection_reasons + ["selected option disabled"],
                ),
            )
    except GreatWalkPeopleDropdownError:
        raise
    except Exception:
        pass

    option_locator.click(timeout=5_000)
    verified, post_value = _wait_for_people_value(page, binding, people_size)
    diagnostics = build_people_dropdown_diagnostics(
        discovery,
        requested_people=people_size,
        current_people=current,
        association_method=association_method,
        selected_candidate=selected,
        rejection_reasons=rejection_reasons,
        post_click_value=post_value,
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
