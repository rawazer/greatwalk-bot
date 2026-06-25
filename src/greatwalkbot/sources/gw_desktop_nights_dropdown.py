"""Desktop Great Walk Nights dropdown binding with track-aware behavior."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from greatwalkbot.infra.errors import (
    GreatWalkNightsDropdownError,
    GreatWalkNightsTrackConstraintError,
)
from greatwalkbot.sources.gw_desktop_form import (
    NIGHTS_BUTTON_SELECTOR,
    NIGHTS_LIST_SELECTOR,
    DesktopRootBinding,
    _extract_count,
    click_desktop_control,
    read_desktop_form_state,
    wait_for_control_clickable,
)

NIGHTS_VERIFY_TIMEOUT_MS = 5_000
NIGHTS_OPEN_TIMEOUT_MS = 5_000
NIGHTS_MENU_WAIT_TIMEOUT_MS = 5_000
NIGHTS_POLL_INTERVAL_MS = 50
MAX_NIGHTS_OPTION_CANDIDATES = 20

ResolutionMethod = Literal["zero_based_option_id", "generic_discovery"]

_PROBE_NIGHTS_TRIGGER_JS = """
() => {
    const MAX = 5;
    const mobile = document.getElementById('great-walk-start-date-mobile');
    const button = document.getElementById('great-walk-night-dropdown-button');
    if (!button) {
        return { found: false, reason: 'nights-button-missing', trigger: null };
    }

    function visible(el) {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function inMobile(el) {
        return !!(mobile && mobile.contains(el)) || !!el.closest('[id*="-mobile"], [class*="-mobile"]');
    }

    const style = window.getComputedStyle(button);
    const rect = button.getBoundingClientRect();
    const cls = (button.className || '').toString();
    const ariaDisabled = button.getAttribute('aria-disabled');
    const enabled = !button.disabled && ariaDisabled !== 'true';
    const pointerEvents = style.pointerEvents || null;
    const nonEditableEvidence = [];
    if (button.disabled) nonEditableEvidence.push('button.disabled');
    if (ariaDisabled === 'true') nonEditableEvidence.push('aria-disabled=true');
    if (cls.includes('disabled')) nonEditableEvidence.push('class-contains-disabled');
    if (/grey|gray/i.test(cls)) nonEditableEvidence.push('class-contains-grey');
    if (pointerEvents === 'none') nonEditableEvidence.push('pointer-events-none');
    if (!enabled) nonEditableEvidence.push('computed-not-enabled');

    const trigger = {
        tag: button.tagName,
        id: button.id || null,
        class: cls.slice(0, 120) || null,
        text: (button.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 40) || null,
        aria_label: (button.getAttribute('aria-label') || '').slice(0, 120) || null,
        aria_expanded: button.getAttribute('aria-expanded'),
        aria_disabled: ariaDisabled,
        visible: visible(button) && !inMobile(button),
        enabled,
        pointer_events: pointerEvents,
        likely_mobile: inMobile(button),
        rect: {
            x: Math.round(rect.x),
            y: Math.round(rect.y),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
        },
    };

    return {
        found: true,
        trigger,
        editable: enabled && visible(button) && !inMobile(button) && nonEditableEvidence.length === 0,
        non_editable_evidence: nonEditableEvidence.slice(0, MAX),
        menu_open: button.getAttribute('aria-expanded') === 'true',
    };
}
"""

_PROBE_ZERO_BASED_NIGHTS_JS = """
({ nights, menuSelector }) => {
    const MAX = 20;
    const optionId = `great-walk-night-${nights - 1}`;
    const mobile = document.getElementById('great-walk-start-date-mobile');

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
        return !!(mobile && mobile.contains(el)) || !!el.closest('[id*="-mobile"], [class*="-mobile"]');
    }

    function normalizeText(el) {
        return (el.textContent || '').replace(/\\s+/g, ' ').trim();
    }

    function describe(el, index) {
        const rect = el.getBoundingClientRect();
        const cls = (el.className || '').toString();
        return {
            index,
            tag: el.tagName,
            id: el.id || null,
            class: cls.slice(0, 120) || null,
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
        };
    }

    const menus = Array.from(document.querySelectorAll(menuSelector))
        .filter(el => visible(el) && !inMobile(el));

    const button = document.getElementById('great-walk-night-dropdown-button');
    const buttonText = button ? normalizeText(button).slice(0, 40) : null;

    let targetOptions = [];
    let menuOptions = [];
    if (menus.length === 1) {
        const menu = menus[0];
        targetOptions = Array.from(menu.querySelectorAll(`[id="${optionId}"]`))
            .filter(el => el.id === optionId && visible(el) && !inMobile(el));
        if (targetOptions.length === 0) {
            const direct = menu.querySelector(`#${optionId}`);
            if (direct && direct.id === optionId && visible(direct) && !inMobile(direct)) {
                targetOptions = [direct];
            }
        }
        menu.querySelectorAll('[id*="great-walk-night"], [role="option"], li, a, button, div').forEach(el => {
            if (menuOptions.length >= MAX) return;
            if (!visible(el) || inMobile(el)) return;
            if (el.id === 'great-walk-night-dropdown-button') return;
            const text = normalizeText(el);
            const id = el.id || '';
            if (!text && !id) return;
            if (id.endsWith('-dropdown-box') || id.endsWith('-dropdown-button')) return;
            menuOptions.push(describe(el, menuOptions.length));
        });
    }

    const target = targetOptions.length === 1 ? describe(targetOptions[0], 0) : (
        targetOptions.length > 0 ? describe(targetOptions[0], 0) : null
    );

    return {
        requested_nights: nights,
        computed_option_id: optionId,
        menu_count: menus.length,
        menus: menus.slice(0, 3).map((el, index) => describe(el, index)),
        target_option_count: targetOptions.length,
        target_option: target,
        observed_target_text: target ? target.text : null,
        menu_open: button ? button.getAttribute('aria-expanded') === 'true' : null,
        trigger_value_before: buttonText,
        button_aria_expanded: button ? button.getAttribute('aria-expanded') : null,
        menu_options: menuOptions.slice(0, MAX),
    };
}
"""


class NightsDropdownPage(Protocol):
    def locator(self, selector: str) -> Any: ...

    def evaluate(self, expression: str, arg: Any = None) -> Any: ...

    def wait_for_timeout(self, timeout: int) -> None: ...


@dataclass(frozen=True)
class NightsSelectionResult:
    action: Literal["already_matched", "already_matched_track_controlled", "changed_and_verified"]
    requested_nights: int
    normalized_value: str | None
    nights_dropdown_diagnostics: dict[str, Any] | None = None


def zero_based_option_element_id(nights: int) -> str:
    return f"great-walk-night-{nights - 1}"


def probe_nights_trigger(page: NightsDropdownPage) -> dict[str, Any]:
    raw = page.evaluate(_PROBE_NIGHTS_TRIGGER_JS)
    return raw if isinstance(raw, dict) else {"found": False, "trigger": None, "editable": False}


def inspect_nights_control(
    page: NightsDropdownPage,
    binding: DesktopRootBinding,
    *,
    requested_nights: int,
) -> dict[str, Any]:
    state = read_desktop_form_state(page, binding, nights=requested_nights)
    nights_ctrl = dict(state.get("nights_control") or {})
    trigger_probe = probe_nights_trigger(page)
    current = _extract_count(nights_ctrl.get("visible_text"))
    return {
        "trigger": trigger_probe.get("trigger"),
        "editable": bool(trigger_probe.get("editable")),
        "non_editable_evidence": list(trigger_probe.get("non_editable_evidence") or []),
        "menu_open_before": trigger_probe.get("menu_open"),
        "current_nights": current,
        "requested_nights": requested_nights,
        "normalized_value": nights_ctrl.get("normalized_value"),
        "matches_requested": nights_ctrl.get("matches_requested"),
        "aria_expanded": nights_ctrl.get("aria_expanded"),
    }


def build_nights_dropdown_diagnostics(
    inspection: dict[str, Any],
    *,
    resolution_method: ResolutionMethod | None = None,
    deterministic_binding: dict[str, Any] | None = None,
    generic_candidates: list[dict[str, Any]] | None = None,
    rejection_reasons: list[str] | None = None,
    post_click_value: str | None = None,
    menu_open_after: bool | None = None,
) -> dict[str, Any]:
    diag: dict[str, Any] = {
        "trigger": inspection.get("trigger"),
        "editable": inspection.get("editable"),
        "non_editable_evidence": list(inspection.get("non_editable_evidence") or []),
        "current_nights": inspection.get("current_nights"),
        "requested_nights": inspection.get("requested_nights"),
        "normalized_value": inspection.get("normalized_value"),
        "matches_requested": inspection.get("matches_requested"),
        "menu_open_before": inspection.get("menu_open_before"),
    }
    if resolution_method is not None:
        diag["resolution_method"] = resolution_method
    if deterministic_binding is not None:
        diag["deterministic_binding"] = deterministic_binding
    if generic_candidates is not None:
        diag["generic_option_candidates"] = generic_candidates[:MAX_NIGHTS_OPTION_CANDIDATES]
    if rejection_reasons is not None:
        diag["rejection_reasons"] = rejection_reasons[:20]
    if post_click_value is not None:
        diag["post_click_value"] = post_click_value
    if menu_open_after is not None:
        diag["menu_open_after"] = menu_open_after
    return diag


def build_deterministic_binding_diagnostics(
    probe: dict[str, Any],
    *,
    trigger_value_after: str | None = None,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    diag: dict[str, Any] = {
        "requested_nights": probe.get("requested_nights"),
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


def probe_zero_based_nights_binding(page: NightsDropdownPage, nights: int) -> dict[str, Any]:
    raw = page.evaluate(
        _PROBE_ZERO_BASED_NIGHTS_JS,
        {"nights": nights, "menuSelector": NIGHTS_LIST_SELECTOR},
    )
    return raw if isinstance(raw, dict) else {"menu_count": 0, "target_option_count": 0, "menu_options": []}


def _evaluate_zero_based_binding(
    probe: dict[str, Any],
    nights: int,
) -> tuple[Literal["matched", "absent", "failed"], list[str]]:
    reasons: list[str] = []
    menu_count = int(probe.get("menu_count") or 0)
    if menu_count > 1:
        reasons.append(f"ambiguous visible nights menus: {menu_count}")
        return "failed", reasons
    if menu_count == 0:
        reasons.append("visible nights menu not found")
        return "absent", reasons

    target_count = int(probe.get("target_option_count") or 0)
    if target_count == 0:
        reasons.append(
            f"deterministic option {probe.get('computed_option_id')!r} not found in visible menu"
        )
        return "absent", reasons
    if target_count > 1:
        reasons.append(f"ambiguous deterministic nights options: {target_count}")
        return "failed", reasons

    observed = (probe.get("observed_target_text") or "").strip()
    if observed != str(nights):
        reasons.append(
            f"deterministic option text mismatch: expected {nights!r}, observed {observed!r}"
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


def _semantic_nights_option_score(candidate: dict[str, Any], nights: int) -> bool:
    if candidate.get("likely_mobile"):
        return False
    text = (candidate.get("text") or "").strip()
    if text == str(nights):
        return True
    if re.fullmatch(rf"{nights}\s+nights?", text, flags=re.IGNORECASE):
        return True
    option_id = candidate.get("id") or ""
    return option_id == zero_based_option_element_id(nights)


def _resolve_generic_nights_option(
    probe: dict[str, Any],
    nights: int,
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    options = [
        o
        for o in list(probe.get("menu_options") or [])[:MAX_NIGHTS_OPTION_CANDIDATES]
        if o.get("visible") and o.get("enabled", True) and not o.get("likely_mobile")
    ]
    matches = [o for o in options if _semantic_nights_option_score(o, nights)]
    if not matches:
        for option in options:
            reasons.append(
                f"rejected generic option id={option.get('id')!r} text={option.get('text')!r}"
            )
        reasons.append(f"no generic nights option match for {nights}")
        return None, reasons
    if len(matches) > 1:
        reasons.append(f"ambiguous generic nights options for {nights}: {len(matches)}")
        return None, reasons
    return matches[0], reasons


def _wait_for_zero_based_nights_menu(
    page: NightsDropdownPage,
    *,
    timeout_ms: int = NIGHTS_MENU_WAIT_TIMEOUT_MS,
) -> dict[str, Any]:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    last = probe_zero_based_nights_binding(page, nights=1)
    while time.monotonic() < deadline:
        last = probe_zero_based_nights_binding(page, nights=1)
        if last.get("menu_count") == 1:
            return last
        page.wait_for_timeout(NIGHTS_POLL_INTERVAL_MS)
    return last


def _zero_based_option_locator(page: NightsDropdownPage, nights: int) -> Any:
    mobile = page.locator("[id*='-mobile']")
    menu = page.locator(NIGHTS_LIST_SELECTOR).filter(has_not=mobile)
    if menu.count() != 1:
        raise GreatWalkNightsDropdownError(
            f"Expected exactly one visible desktop Nights menu, found {menu.count()}",
        )
    option_id = zero_based_option_element_id(nights)
    option = menu.locator(f"#{option_id}").filter(has_not=mobile)
    if option.count() != 1:
        raise GreatWalkNightsDropdownError(
            f"Expected exactly one visible desktop Nights option {option_id!r}, found {option.count()}",
        )
    return option.first


def _generic_option_locator(page: NightsDropdownPage, candidate: dict[str, Any]) -> Any:
    mobile = page.locator("[id*='-mobile']")
    menu = page.locator(NIGHTS_LIST_SELECTOR).filter(has_not=mobile)
    if menu.count() != 1:
        raise GreatWalkNightsDropdownError("Expected exactly one visible desktop Nights menu")
    if candidate.get("id"):
        loc = menu.locator(f"#{candidate['id']}").filter(has_not=mobile)
        if loc.count() == 1:
            return loc.first
    text = (candidate.get("text") or "").strip()
    if text:
        loc = menu.locator(f'text="{text}"').filter(has_not=mobile)
        if loc.count() == 1:
            return loc.first
    raise GreatWalkNightsDropdownError(
        f"Could not build locator for nights option {candidate.get('id')!r}",
        nights_dropdown_diagnostics={"selected_candidate": candidate},
    )


def _wait_for_nights_value(
    page: NightsDropdownPage,
    binding: DesktopRootBinding,
    nights: int,
    *,
    timeout_ms: int = NIGHTS_VERIFY_TIMEOUT_MS,
) -> tuple[bool, str | None]:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    last_value: str | None = None
    while time.monotonic() < deadline:
        state = read_desktop_form_state(page, binding, nights=nights)
        nights_ctrl = state.get("nights_control") or {}
        last_value = nights_ctrl.get("normalized_value")
        count = _extract_count(nights_ctrl.get("visible_text"))
        value_ok = nights_ctrl.get("matches_requested") or count == nights
        expanded = nights_ctrl.get("aria_expanded")
        menu_closed = expanded == "false" or expanded is False
        if value_ok and menu_closed:
            return True, last_value or str(nights)
        page.wait_for_timeout(NIGHTS_POLL_INTERVAL_MS)
    return False, last_value


def _click_editable_nights_option(
    page: NightsDropdownPage,
    binding: DesktopRootBinding,
    nights: int,
    inspection: dict[str, Any],
    *,
    root_change: dict[str, Any] | None = None,
) -> NightsSelectionResult:
    probe = probe_zero_based_nights_binding(page, nights)
    status, rejection_reasons = _evaluate_zero_based_binding(probe, nights)
    resolution_method: ResolutionMethod = "zero_based_option_id"
    selected_candidate: dict[str, Any] | None = None
    use_generic = False

    if status == "failed":
        raise GreatWalkNightsDropdownError(
            f"Deterministic desktop Nights binding failed for {nights}",
            nights_dropdown_diagnostics=build_nights_dropdown_diagnostics(
                inspection,
                resolution_method=resolution_method,
                deterministic_binding=build_deterministic_binding_diagnostics(
                    probe,
                    failure_reason=rejection_reasons[0] if rejection_reasons else None,
                ),
                rejection_reasons=rejection_reasons,
            ),
        )

    if status == "absent":
        selected_candidate, generic_reasons = _resolve_generic_nights_option(probe, nights)
        rejection_reasons = generic_reasons
        resolution_method = "generic_discovery"
        use_generic = True
        if selected_candidate is None:
            raise GreatWalkNightsDropdownError(
                f"Could not resolve desktop Nights option for {nights}",
                nights_dropdown_diagnostics=build_nights_dropdown_diagnostics(
                    inspection,
                    resolution_method=resolution_method,
                    deterministic_binding=build_deterministic_binding_diagnostics(probe),
                    generic_candidates=list(probe.get("menu_options") or []),
                    rejection_reasons=rejection_reasons,
                ),
            )
    else:
        selected_candidate = probe.get("target_option")

    probe = probe_zero_based_nights_binding(page, nights)
    if not use_generic:
        status, rejection_reasons = _evaluate_zero_based_binding(probe, nights)
        if status != "matched":
            raise GreatWalkNightsDropdownError(
                f"Could not re-resolve deterministic desktop Nights option for {nights}",
                nights_dropdown_diagnostics=build_nights_dropdown_diagnostics(
                    inspection,
                    resolution_method=resolution_method,
                    deterministic_binding=build_deterministic_binding_diagnostics(
                        probe,
                        failure_reason=rejection_reasons[0] if rejection_reasons else None,
                    ),
                    rejection_reasons=rejection_reasons,
                ),
            )
        option_locator = _zero_based_option_locator(page, nights)
    else:
        selected_candidate, rejection_reasons = _resolve_generic_nights_option(probe, nights)
        if selected_candidate is None:
            raise GreatWalkNightsDropdownError(
                f"Could not re-resolve generic desktop Nights option for {nights}",
                nights_dropdown_diagnostics=build_nights_dropdown_diagnostics(
                    inspection,
                    resolution_method=resolution_method,
                    generic_candidates=list(probe.get("menu_options") or []),
                    rejection_reasons=rejection_reasons
                    + ["option could not be re-resolved immediately before click"],
                ),
            )
        option_locator = _generic_option_locator(page, selected_candidate)

    try:
        if hasattr(option_locator, "is_enabled") and not option_locator.is_enabled():
            raise GreatWalkNightsDropdownError(
                f"Desktop Nights option for {nights} is disabled",
                nights_dropdown_diagnostics=build_nights_dropdown_diagnostics(
                    inspection,
                    resolution_method=resolution_method,
                    rejection_reasons=["selected option disabled"],
                ),
            )
    except GreatWalkNightsDropdownError:
        raise
    except Exception:
        pass

    option_locator.click(timeout=NIGHTS_VERIFY_TIMEOUT_MS)
    verified, post_value = _wait_for_nights_value(page, binding, nights)
    after_probe = probe_zero_based_nights_binding(page, nights)
    diagnostics = build_nights_dropdown_diagnostics(
        inspection,
        resolution_method=resolution_method,
        deterministic_binding=build_deterministic_binding_diagnostics(
            probe,
            trigger_value_after=post_value,
        ),
        generic_candidates=list(probe.get("menu_options") or [])
        if use_generic
        else None,
        rejection_reasons=rejection_reasons,
        post_click_value=post_value,
        menu_open_after=bool(after_probe.get("menu_open")),
    )
    if not verified:
        diagnostics["deterministic_binding"] = build_deterministic_binding_diagnostics(
            after_probe,
            trigger_value_after=post_value,
            failure_reason="trigger did not verify after nights selection",
        )
        raise GreatWalkNightsDropdownError(
            f"Desktop Nights control did not verify as {nights} after selection",
            nights_dropdown_diagnostics=diagnostics,
        )
    return NightsSelectionResult(
        action="changed_and_verified",
        requested_nights=nights,
        normalized_value=post_value,
        nights_dropdown_diagnostics=diagnostics,
    )


def select_desktop_nights(
    page: NightsDropdownPage,
    nights: int,
    binding: DesktopRootBinding | None = None,
    *,
    root_change: dict[str, Any] | None = None,
) -> NightsSelectionResult:
    """Select or verify desktop nights with track-controlled vs editable behavior."""
    from greatwalkbot.sources.gw_desktop_form import resolve_desktop_great_walk_root

    binding = binding or resolve_desktop_great_walk_root(page)
    inspection = inspect_nights_control(page, binding, requested_nights=nights)
    current = inspection.get("current_nights")

    if not inspection.get("editable"):
        if inspection.get("matches_requested"):
            return NightsSelectionResult(
                action="already_matched_track_controlled",
                requested_nights=nights,
                normalized_value=inspection.get("normalized_value"),
                nights_dropdown_diagnostics=build_nights_dropdown_diagnostics(inspection),
            )
        raise GreatWalkNightsTrackConstraintError(
            f"Nights control is track-controlled at {current!r}, cannot set {nights}",
            requested_nights=nights,
            current_nights=current,
            nights_dropdown_diagnostics=build_nights_dropdown_diagnostics(inspection),
        )

    if inspection.get("matches_requested"):
        return NightsSelectionResult(
            action="already_matched",
            requested_nights=nights,
            normalized_value=inspection.get("normalized_value"),
        )

    wait_for_control_clickable(
        page,
        binding,
        NIGHTS_BUTTON_SELECTOR,
        "nights",
        root_change=root_change,
    )
    click_desktop_control(
        page,
        binding,
        NIGHTS_BUTTON_SELECTOR,
        "nights",
        root_change=root_change,
    )
    _wait_for_zero_based_nights_menu(page)
    inspection = inspect_nights_control(page, binding, requested_nights=nights)
    inspection["menu_open_before"] = True
    return _click_editable_nights_option(
        page,
        binding,
        nights,
        inspection,
        root_change=root_change,
    )
