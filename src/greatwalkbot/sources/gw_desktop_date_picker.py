"""Desktop React DatePicker binding for #great-walk-start-date."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any, Literal, Protocol

from greatwalkbot.infra.errors import (
    GreatWalkDatePickerError,
    GreatWalkDateUnavailableError,
)
from greatwalkbot.sources.gw_active_form import normalize_date_string
from greatwalkbot.sources.gw_desktop_date_picker_popup import (
    DesktopDatePickerPopup,
    click_popup_navigation_control,
    discover_popup_navigation_raw,
    inspect_date_picker_navigation,
    navigation_diagnostics,
    resolve_calendar_navigation_controls,
    resolve_visible_desktop_date_picker,
    sample_popup_day_labels,
)

DATE_MOBILE_SELECTOR = "#great-walk-start-date-mobile"
DATE_PICKER_MONTH_CONTAINER = ".react-datepicker__month-container"
DATE_PICKER_CURRENT_MONTH = ".react-datepicker__current-month"
DATE_PICKER_NEXT = ".react-datepicker__navigation--next"
DATE_PICKER_PREV = ".react-datepicker__navigation--previous"
DATE_PICKER_DAY = '.react-datepicker__day[role="button"]'

MAX_MONTH_NAVIGATION_STEPS = 18
DATE_PICKER_OPEN_TIMEOUT_MS = 5_000
DATE_PICKER_CLOSE_TIMEOUT_MS = 5_000
MAX_VISIBLE_DAY_LABELS = 15

_DAY_LABEL_RE = re.compile(
    r"^(?:Choose|Not available)\s+\w+,\s+(\w+)\s+\d+(?:st|nd|rd|th),\s+(\d{4})$"
)

_READ_DATE_PICKER_STATE_JS = """
() => {
    const mobile = document.getElementById('great-walk-start-date-mobile');
    const containers = Array.from(document.querySelectorAll('.react-datepicker__month-container'))
        .filter(el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || rect.width === 0) return false;
            if (mobile && mobile.contains(el)) return false;
            if (el.closest('[id*="-mobile"]')) return false;
            return true;
        });
    const dp = containers[0] ? containers[0].closest('.react-datepicker') : null;
    const monthEl = dp ? dp.querySelector('.react-datepicker__current-month') : null;
    const next = dp ? dp.querySelector('.react-datepicker__navigation--next') : null;
    const prev = dp ? dp.querySelector('.react-datepicker__navigation--previous') : null;
    function visible(el) {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return style.display !== 'none' && rect.width > 0;
    }
    return {
        open: containers.length > 0,
        container_count: containers.length,
        month_text: monthEl ? monthEl.textContent.replace(/\\s+/g, ' ').trim() : null,
        has_next: visible(next),
        has_prev: visible(prev),
    };
}
"""

_COLLECT_CALENDAR_DIAGNOSTICS_JS = """
() => {
    const mobile = document.getElementById('great-walk-start-date-mobile');
    function visible(el) {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || rect.width === 0) return false;
        if (mobile && mobile.contains(el)) return false;
        if (el.closest('[id*="-mobile"]')) return false;
        return true;
    }
    function countVisible(selector) {
        return Array.from(document.querySelectorAll(selector))
            .filter(visible).length;
    }
    const dayLabels = Array.from(document.querySelectorAll('.react-datepicker__day[role="button"]'))
        .filter(visible)
        .map(el => (el.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim().slice(0, 100))
        .filter(Boolean)
        .slice(0, 15);
    const monthEl = Array.from(document.querySelectorAll('.react-datepicker__current-month'))
        .find(visible);
    return {
        selector_counts: {
            current_month: countVisible('.react-datepicker__current-month'),
            month_container: countVisible('.react-datepicker__month-container'),
            day_buttons: countVisible('.react-datepicker__day[role="button"]'),
            nav_next: countVisible('.react-datepicker__navigation--next'),
            nav_prev: countVisible('.react-datepicker__navigation--previous'),
        },
        month_text: monthEl ? monthEl.textContent.replace(/\\s+/g, ' ').trim() : null,
        visible_day_labels: dayLabels,
    };
}
"""


class DatePickerPage(Protocol):
    def locator(self, selector: str) -> Any: ...

    def evaluate(self, expression: str, arg: Any = None) -> Any: ...

    def wait_for_timeout(self, timeout: int) -> None: ...

    def get_by_role(self, role: str, *, name: str | None = None, exact: bool = False) -> Any: ...


TargetDayStatus = Literal["choose", "unavailable", "absent"]


def ordinal_day(day: int) -> str:
    if 11 <= day % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def build_choose_aria_label(target: date) -> str:
    return (
        f"Choose {target.strftime('%A')}, {target.strftime('%B')} "
        f"{ordinal_day(target.day)}, {target.year}"
    )


def build_unavailable_aria_label(target: date) -> str:
    return (
        f"Not available {target.strftime('%A')}, {target.strftime('%B')} "
        f"{ordinal_day(target.day)}, {target.year}"
    )


def parse_month_year_header(text: str | None) -> date | None:
    if not text:
        return None
    cleaned = " ".join(text.split())
    for fmt in ("%B %Y", "%b %Y"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return date(parsed.year, parsed.month, 1)
        except ValueError:
            continue
    return None


def parse_month_year_from_day_label(label: str) -> date | None:
    match = _DAY_LABEL_RE.match(label.strip())
    if not match:
        return None
    month_name, year_str = match.groups()
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            parsed = datetime.strptime(f"{month_name} 1 {year_str}", fmt)
            return date(parsed.year, parsed.month, 1)
        except ValueError:
            continue
    return None


def infer_month_from_day_labels(labels: list[str]) -> date | None:
    for label in labels:
        parsed = parse_month_year_from_day_label(label)
        if parsed is not None:
            return parsed
    return None


def day_label_fingerprint(labels: list[str]) -> dict[str, Any]:
    sample = labels[:MAX_VISIBLE_DAY_LABELS]
    return {
        "count": len(labels),
        "first": sample[0] if sample else None,
        "last": sample[-1] if sample else None,
        "sample": sample[:5],
    }


def _day_button_locator(
    page: DatePickerPage,
    aria_label: str,
    popup: DesktopDatePickerPopup | None = None,
) -> Any:
    if popup is not None:
        escaped = aria_label.replace("\\", "\\\\").replace('"', '\\"')
        scoped = popup.locator.locator(f'[aria-label="{escaped}"]')
        if scoped.count() > 0:
            return scoped.first
    if hasattr(page, "get_by_role"):
        return page.get_by_role("button", name=aria_label, exact=True)
    escaped = aria_label.replace("\\", "\\\\").replace('"', '\\"')
    return page.locator(f'[role="button"][aria-label="{escaped}"]')


def read_date_picker_state(page: DatePickerPage) -> dict[str, Any]:
    try:
        popup = resolve_visible_desktop_date_picker(page)
        month_text, labels = sample_popup_day_labels(page)
        discovery = discover_popup_navigation_raw(page)
        controls = resolve_calendar_navigation_controls(discovery)
        return {
            "open": True,
            "container_count": 1,
            "month_text": month_text,
            "has_next": controls.next is not None,
            "has_prev": controls.previous is not None,
            "popup": popup.descriptor.get("popup"),
            "day_label_count": len(labels),
        }
    except GreatWalkDatePickerError:
        return {"open": False, "container_count": 0}


def _wait_for_fingerprint_change(
    page: DatePickerPage,
    fingerprint_before: dict[str, Any],
    *,
    timeout_ms: int = 3_000,
) -> tuple[dict[str, Any], list[str]]:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        labels = sample_visible_day_labels(page)
        fingerprint_after = day_label_fingerprint(labels)
        if fingerprint_after != fingerprint_before:
            return fingerprint_after, labels
        page.wait_for_timeout(50)
    labels = sample_visible_day_labels(page)
    return day_label_fingerprint(labels), labels


def _raise_missing_navigation(
    page: DatePickerPage,
    *,
    direction: Literal["next", "prev"],
    target: date,
    date_iso: str,
    navigation_steps: list[dict[str, Any]],
    fingerprint_before: dict[str, Any] | None = None,
    fingerprint_after: dict[str, Any] | None = None,
) -> None:
    raise GreatWalkDatePickerError(
        f"Date-picker {direction}-month navigation control is missing",
        date_iso=date_iso,
        calendar_diagnostics=navigation_diagnostics(
            page,
            choose_label=build_choose_aria_label(target),
            unavailable_label=build_unavailable_aria_label(target),
            navigation_steps=navigation_steps,
            fingerprint_before=fingerprint_before,
            fingerprint_after=fingerprint_after,
        ),
    )


def _click_popup_month_navigation(
    page: DatePickerPage,
    direction: Literal["next", "prev"],
) -> None:
    popup = resolve_visible_desktop_date_picker(page)
    discovery = discover_popup_navigation_raw(page)
    controls = resolve_calendar_navigation_controls(discovery)
    resolved = controls.next if direction == "next" else controls.previous
    if resolved is None:
        raise GreatWalkDatePickerError(
            f"Date-picker {direction}-month navigation control is missing",
            calendar_diagnostics=navigation_diagnostics(page),
        )
    click_popup_navigation_control(page, popup, resolved, direction=direction)


def sample_visible_day_labels(page: DatePickerPage) -> list[str]:
    _month_text, labels = sample_popup_day_labels(page)
    return labels[:MAX_VISIBLE_DAY_LABELS]


def collect_calendar_diagnostics(
    page: DatePickerPage,
    target: date | None = None,
    *,
    navigation_steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    labels = sample_visible_day_labels(page)
    month_text, _ = sample_popup_day_labels(page)
    diag: dict[str, Any] = navigation_diagnostics(
        page,
        choose_label=build_choose_aria_label(target) if target else None,
        unavailable_label=build_unavailable_aria_label(target) if target else None,
        navigation_steps=navigation_steps,
    )
    diag.update(
        {
            "month_text": month_text,
            "parsed_month_from_header": (
                parse_month_year_header(month_text).isoformat()
                if parse_month_year_header(month_text)
                else None
            ),
            "parsed_month_from_day_labels": (
                infer_month_from_day_labels(labels).isoformat()
                if infer_month_from_day_labels(labels)
                else None
            ),
            "visible_day_labels": labels,
            "day_label_fingerprint": day_label_fingerprint(labels),
            "picker_state": read_date_picker_state(page),
        }
    )
    return diag


def locate_target_day_in_picker(
    page: DatePickerPage,
    target: date,
    popup: DesktopDatePickerPopup | None = None,
) -> tuple[TargetDayStatus, str | None]:
    if popup is None:
        try:
            popup = resolve_visible_desktop_date_picker(page)
        except GreatWalkDatePickerError:
            popup = None
    unavailable_label = build_unavailable_aria_label(target)
    if _day_button_locator(page, unavailable_label, popup).count() > 0:
        return "unavailable", unavailable_label
    choose_label = build_choose_aria_label(target)
    if _day_button_locator(page, choose_label, popup).count() > 0:
        return "choose", choose_label
    return "absent", None


def wait_for_date_picker_open(
    page: DatePickerPage,
    *,
    timeout_ms: int = DATE_PICKER_OPEN_TIMEOUT_MS,
) -> dict[str, Any]:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    last_state: dict[str, Any] = {"open": False, "container_count": 0}
    while time.monotonic() < deadline:
        last_state = read_date_picker_state(page)
        if last_state.get("open"):
            return last_state
        page.wait_for_timeout(100)
    raise GreatWalkDatePickerError(
        "Desktop React date picker did not open",
        calendar_diagnostics=collect_calendar_diagnostics(page),
    )


def _raise_unavailable(
    target: date,
    *,
    date_iso: str,
    aria_label: str,
    page: DatePickerPage,
    navigation_steps: list[dict[str, Any]],
) -> None:
    raise GreatWalkDateUnavailableError(
        f"Requested start date is not available: {aria_label}",
        date_iso=date_iso,
        aria_label=aria_label,
        calendar_diagnostics=collect_calendar_diagnostics(
            page,
            target,
            navigation_steps=navigation_steps,
        ),
    )


def _navigation_direction(
    target: date,
    *,
    header_month: date | None,
    inferred_month: date | None,
) -> Literal["next", "prev"]:
    target_month = date(target.year, target.month, 1)
    current_month = inferred_month or header_month
    if current_month is not None and current_month > target_month:
        return "prev"
    return "next"


def navigate_and_select_target_day(
    page: DatePickerPage,
    target: date,
    *,
    date_iso: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Locate target day first; navigate by day-label fingerprint when needed."""
    choose_label = build_choose_aria_label(target)
    navigation_steps: list[dict[str, Any]] = []

    for attempt in range(MAX_MONTH_NAVIGATION_STEPS + 1):
        popup: DesktopDatePickerPopup | None = None
        try:
            popup = resolve_visible_desktop_date_picker(page)
        except GreatWalkDatePickerError:
            pass
        status, label = locate_target_day_in_picker(page, target, popup)
        if status == "unavailable" and label:
            _raise_unavailable(
                target,
                date_iso=date_iso,
                aria_label=label,
                page=page,
                navigation_steps=navigation_steps,
            )
        if status == "choose" and label:
            _day_button_locator(page, label, popup).first.click()
            if attempt == 0:
                navigation_steps.append({"action": "target_already_visible"})
            else:
                navigation_steps.append({"action": "target_found_after_navigation"})
            return choose_label, navigation_steps

        if attempt >= MAX_MONTH_NAVIGATION_STEPS:
            break

        state = read_date_picker_state(page)
        if not state.get("open"):
            raise GreatWalkDatePickerError(
                "Date picker closed during month navigation",
                date_iso=date_iso,
                calendar_diagnostics=collect_calendar_diagnostics(
                    page,
                    target,
                    navigation_steps=navigation_steps,
                ),
            )

        labels_before = sample_visible_day_labels(page)
        fingerprint_before = day_label_fingerprint(labels_before)
        header_month = parse_month_year_header(state.get("month_text"))
        inferred_month = infer_month_from_day_labels(labels_before) or header_month

        if not labels_before and header_month is None:
            discovery = discover_popup_navigation_raw(page)
            controls = resolve_calendar_navigation_controls(discovery)
            if controls.next is None and controls.previous is None:
                raise GreatWalkDatePickerError(
                    "Date picker has no usable month header or day-button labels",
                    date_iso=date_iso,
                    calendar_diagnostics=collect_calendar_diagnostics(
                        page,
                        target,
                        navigation_steps=navigation_steps,
                    ),
                )

        direction = _navigation_direction(
            target,
            header_month=header_month,
            inferred_month=inferred_month,
        )
        if direction == "next" and not state.get("has_next"):
            _raise_missing_navigation(
                page,
                direction="next",
                target=target,
                date_iso=date_iso,
                navigation_steps=navigation_steps,
                fingerprint_before=fingerprint_before,
            )
        if direction == "prev" and not state.get("has_prev"):
            _raise_missing_navigation(
                page,
                direction="prev",
                target=target,
                date_iso=date_iso,
                navigation_steps=navigation_steps,
                fingerprint_before=fingerprint_before,
            )

        _click_popup_month_navigation(page, direction)
        fingerprint_after, labels_after = _wait_for_fingerprint_change(
            page,
            fingerprint_before,
        )
        if fingerprint_before == fingerprint_after:
            raise GreatWalkDatePickerError(
                "Date-picker day-label fingerprint unchanged after navigation click",
                date_iso=date_iso,
                calendar_diagnostics=navigation_diagnostics(
                    page,
                    choose_label=build_choose_aria_label(target),
                    unavailable_label=build_unavailable_aria_label(target),
                    navigation_steps=navigation_steps,
                    fingerprint_before=fingerprint_before,
                    fingerprint_after=fingerprint_after,
                ),
            )
        navigation_steps.append(
            {
                "action": direction,
                "fingerprint_before": fingerprint_before,
                "fingerprint_after": fingerprint_after,
                "month_text": state.get("month_text"),
                "parsed_month_from_header": (
                    header_month.isoformat() if header_month else None
                ),
                "parsed_month_from_day_labels": (
                    inferred_month.isoformat() if inferred_month else None
                ),
            }
        )

    raise GreatWalkDatePickerError(
        f"Exceeded {MAX_MONTH_NAVIGATION_STEPS} date-picker navigation steps "
        f"without finding target day",
        date_iso=date_iso,
        calendar_diagnostics=collect_calendar_diagnostics(
            page,
            target,
            navigation_steps=navigation_steps,
        ),
    )


def navigate_date_picker_to_month(
    page: DatePickerPage,
    target: date,
    *,
    date_iso: str,
) -> list[dict[str, Any]]:
    """Backward-compatible wrapper; navigation stops before clicking the day."""
    status, _ = locate_target_day_in_picker(page, target)
    if status == "choose":
        return [{"action": "target_already_visible"}]

    target_month = date(target.year, target.month, 1)
    steps: list[dict[str, Any]] = []
    for attempt in range(MAX_MONTH_NAVIGATION_STEPS):
        state = read_date_picker_state(page)
        if not state.get("open"):
            raise GreatWalkDatePickerError(
                "Date picker closed during month navigation",
                date_iso=date_iso,
                calendar_diagnostics=collect_calendar_diagnostics(page, target, navigation_steps=steps),
            )
        labels = sample_visible_day_labels(page)
        header_month = parse_month_year_header(state.get("month_text"))
        inferred_month = infer_month_from_day_labels(labels) or header_month
        if inferred_month == target_month:
            steps.append({"action": "arrived", "month_text": state.get("month_text")})
            return steps

        fingerprint_before = day_label_fingerprint(labels)
        direction = _navigation_direction(
            target,
            header_month=header_month,
            inferred_month=inferred_month,
        )
        if direction == "next" and not state.get("has_next"):
            _raise_missing_navigation(
                page,
                direction="next",
                target=target,
                date_iso=date_iso,
                navigation_steps=steps,
                fingerprint_before=fingerprint_before,
            )
        if direction == "prev" and not state.get("has_prev"):
            _raise_missing_navigation(
                page,
                direction="prev",
                target=target,
                date_iso=date_iso,
                navigation_steps=steps,
                fingerprint_before=fingerprint_before,
            )
        _click_popup_month_navigation(page, direction)
        fingerprint_after, _labels_after = _wait_for_fingerprint_change(
            page,
            fingerprint_before,
        )
        if fingerprint_before == fingerprint_after:
            raise GreatWalkDatePickerError(
                "Date-picker day-label fingerprint unchanged after navigation click",
                date_iso=date_iso,
                calendar_diagnostics=navigation_diagnostics(
                    page,
                    choose_label=build_choose_aria_label(target),
                    unavailable_label=build_unavailable_aria_label(target),
                    navigation_steps=steps,
                    fingerprint_before=fingerprint_before,
                    fingerprint_after=fingerprint_after,
                ),
            )
        steps.append(
            {
                "action": direction,
                "fingerprint_before": fingerprint_before,
                "fingerprint_after": fingerprint_after,
                "month_text": state.get("month_text"),
            }
        )
    raise GreatWalkDatePickerError(
        f"Exceeded {MAX_MONTH_NAVIGATION_STEPS} date-picker month navigation steps",
        date_iso=date_iso,
        calendar_diagnostics=collect_calendar_diagnostics(page, target, navigation_steps=steps),
    )


def click_date_picker_day(
    page: DatePickerPage,
    target: date,
    *,
    date_iso: str,
    navigation_steps: list[dict[str, Any]],
) -> str:
    status, label = locate_target_day_in_picker(page, target)
    if status == "unavailable" and label:
        _raise_unavailable(
            target,
            date_iso=date_iso,
            aria_label=label,
            page=page,
            navigation_steps=navigation_steps,
        )
    choose_label = build_choose_aria_label(target)
    if status != "choose" or not label:
        raise GreatWalkDatePickerError(
            f"No date-picker day button found for aria-label: {choose_label}",
            date_iso=date_iso,
            calendar_diagnostics=collect_calendar_diagnostics(
                page,
                target,
                navigation_steps=navigation_steps,
            ),
        )
    _day_button_locator(page, label).first.click()
    return choose_label


def wait_for_date_picker_closed(
    page: DatePickerPage,
    *,
    timeout_ms: int = DATE_PICKER_CLOSE_TIMEOUT_MS,
) -> None:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        if not read_date_picker_state(page).get("open"):
            return
        page.wait_for_timeout(100)
    raise GreatWalkDatePickerError(
        "Desktop React date picker did not close after day selection",
        calendar_diagnostics=collect_calendar_diagnostics(page),
    )


def read_normalized_trigger_date(start_date_control: dict[str, Any]) -> str | None:
    normalized = normalize_date_string(start_date_control.get("data_date"))
    if not normalized:
        normalized = normalize_date_string(start_date_control.get("visible_text"))
    if not normalized:
        normalized = normalize_date_string(start_date_control.get("aria_label"))
    return normalized


def select_desktop_date_via_react_picker(
    page: DatePickerPage,
    *,
    target: date,
    open_picker: Callable[[], None],
    read_start_date_control: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Open picker, navigate months, select day by accessible name, verify trigger."""
    date_iso = target.isoformat()
    start_ctrl = read_start_date_control()
    normalized = read_normalized_trigger_date(start_ctrl)
    if normalized == date_iso:
        return {
            "action": "already_matched",
            "requested_iso": date_iso,
            "normalized_iso": normalized,
            "calendar_diagnostics": {"trigger": _bounded_trigger_diag(start_ctrl)},
        }

    open_picker()
    picker_state = wait_for_date_picker_open(page)
    choose_label, navigation_steps = navigate_and_select_target_day(
        page,
        target,
        date_iso=date_iso,
    )
    wait_for_date_picker_closed(page)

    updated_ctrl = read_start_date_control()
    updated_iso = read_normalized_trigger_date(updated_ctrl)
    calendar_diagnostics = {
        **collect_calendar_diagnostics(page, target, navigation_steps=navigation_steps),
        "requested_iso": date_iso,
        "choose_aria_label": choose_label,
        "picker_open_state": picker_state,
        "trigger_after": _bounded_trigger_diag(updated_ctrl),
        "normalized_iso_after": updated_iso,
    }
    if updated_iso != date_iso:
        raise GreatWalkDatePickerError(
            f"Start date trigger shows {updated_iso!r}, expected {date_iso!r}",
            date_iso=date_iso,
            calendar_diagnostics=calendar_diagnostics,
        )
    return {
        "action": "changed_and_verified",
        "requested_iso": date_iso,
        "normalized_iso": updated_iso,
        "calendar_diagnostics": calendar_diagnostics,
    }


def _bounded_trigger_diag(control: dict[str, Any]) -> dict[str, Any]:
    return {
        "visible_text": (control.get("visible_text") or "")[:80] or None,
        "data_date": control.get("data_date"),
        "aria_label": (control.get("aria_label") or "")[:120] or None,
    }
