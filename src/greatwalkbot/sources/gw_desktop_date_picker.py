"""Desktop React DatePicker binding for #great-walk-start-date."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date
from typing import Any, Protocol

from greatwalkbot.infra.errors import (
    GreatWalkDatePickerError,
    GreatWalkDateUnavailableError,
)
from greatwalkbot.sources.gw_active_form import normalize_date_string

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

_SAMPLE_VISIBLE_DAY_LABELS_JS = """
() => {
    return Array.from(document.querySelectorAll('.react-datepicker__day[role="button"]'))
        .filter(el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || rect.width === 0) return false;
            if (el.closest('[id*="-mobile"]')) return false;
            return true;
        })
        .map(el => (el.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim().slice(0, 100))
        .filter(Boolean)
        .slice(0, 15);
}
"""


class DatePickerPage(Protocol):
    def locator(self, selector: str) -> Any: ...

    def evaluate(self, expression: str, arg: Any = None) -> Any: ...

    def wait_for_timeout(self, timeout: int) -> None: ...

    def get_by_role(self, role: str, *, name: str | None = None, exact: bool = False) -> Any: ...


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
            from datetime import datetime

            parsed = datetime.strptime(cleaned, fmt)
            return date(parsed.year, parsed.month, 1)
        except ValueError:
            continue
    return None


def _day_button_locator(page: DatePickerPage, aria_label: str) -> Any:
    if hasattr(page, "get_by_role"):
        return page.get_by_role("button", name=aria_label, exact=True)
    escaped = aria_label.replace("\\", "\\\\").replace('"', '\\"')
    return page.locator(f'[role="button"][aria-label="{escaped}"]')


def read_date_picker_state(page: DatePickerPage) -> dict[str, Any]:
    raw = page.evaluate(_READ_DATE_PICKER_STATE_JS)
    return raw if isinstance(raw, dict) else {"open": False, "container_count": 0}


def sample_visible_day_labels(page: DatePickerPage) -> list[str]:
    raw = page.evaluate(_SAMPLE_VISIBLE_DAY_LABELS_JS)
    return list(raw) if isinstance(raw, list) else []


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
        calendar_diagnostics={
            "picker_state": last_state,
            "timeout_ms": timeout_ms,
        },
    )


def navigate_date_picker_to_month(
    page: DatePickerPage,
    target: date,
    *,
    date_iso: str,
) -> list[dict[str, Any]]:
    target_month = date(target.year, target.month, 1)
    steps: list[dict[str, Any]] = []
    for _ in range(MAX_MONTH_NAVIGATION_STEPS):
        state = read_date_picker_state(page)
        if not state.get("open"):
            raise GreatWalkDatePickerError(
                "Date picker closed during month navigation",
                date_iso=date_iso,
                calendar_diagnostics={"picker_state": state, "navigation_steps": steps},
            )
        month_text = state.get("month_text")
        current_month = parse_month_year_header(month_text)
        if current_month is None:
            raise GreatWalkDatePickerError(
                f"Could not parse date-picker month header: {month_text!r}",
                date_iso=date_iso,
                calendar_diagnostics={"picker_state": state, "navigation_steps": steps},
            )
        if current_month == target_month:
            steps.append({"action": "arrived", "month_text": month_text})
            return steps
        if current_month < target_month:
            if not state.get("has_next"):
                raise GreatWalkDatePickerError(
                    "Date-picker next-month navigation control is missing",
                    date_iso=date_iso,
                    calendar_diagnostics={"picker_state": state, "navigation_steps": steps},
                )
            page.locator(DATE_PICKER_NEXT).first.click()
            direction = "next"
        else:
            if not state.get("has_prev"):
                raise GreatWalkDatePickerError(
                    "Date-picker previous-month navigation control is missing",
                    date_iso=date_iso,
                    calendar_diagnostics={"picker_state": state, "navigation_steps": steps},
                )
            page.locator(DATE_PICKER_PREV).first.click()
            direction = "prev"
        page.wait_for_timeout(150)
        new_state = read_date_picker_state(page)
        new_month_text = new_state.get("month_text")
        if new_month_text == month_text:
            raise GreatWalkDatePickerError(
                "Date-picker month header unchanged after navigation click",
                date_iso=date_iso,
                calendar_diagnostics={
                    "picker_state": new_state,
                    "navigation_steps": steps,
                    "direction": direction,
                },
            )
        steps.append({"action": direction, "from": month_text, "to": new_month_text})
    raise GreatWalkDatePickerError(
        f"Exceeded {MAX_MONTH_NAVIGATION_STEPS} date-picker month navigation steps",
        date_iso=date_iso,
        calendar_diagnostics={"navigation_steps": steps, "target_month": target_month.isoformat()},
    )


def click_date_picker_day(
    page: DatePickerPage,
    target: date,
    *,
    date_iso: str,
    navigation_steps: list[dict[str, Any]],
) -> str:
    unavailable_label = build_unavailable_aria_label(target)
    unavailable = _day_button_locator(page, unavailable_label)
    if unavailable.count() > 0:
        raise GreatWalkDateUnavailableError(
            f"Requested start date is not available: {unavailable_label}",
            date_iso=date_iso,
            aria_label=unavailable_label,
            calendar_diagnostics={
                "navigation_steps": navigation_steps,
                "visible_day_labels": sample_visible_day_labels(page),
            },
        )

    choose_label = build_choose_aria_label(target)
    day_button = _day_button_locator(page, choose_label)
    if day_button.count() == 0:
        raise GreatWalkDatePickerError(
            f"No date-picker day button found for aria-label: {choose_label}",
            date_iso=date_iso,
            calendar_diagnostics={
                "choose_aria_label": choose_label,
                "navigation_steps": navigation_steps,
                "visible_day_labels": sample_visible_day_labels(page),
                "picker_state": read_date_picker_state(page),
            },
        )
    day_button.first.click()
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
        calendar_diagnostics={"picker_state": read_date_picker_state(page)},
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
    navigation_steps = navigate_date_picker_to_month(page, target, date_iso=date_iso)
    choose_label = click_date_picker_day(
        page,
        target,
        date_iso=date_iso,
        navigation_steps=navigation_steps,
    )
    wait_for_date_picker_closed(page)

    updated_ctrl = read_start_date_control()
    updated_iso = read_normalized_trigger_date(updated_ctrl)
    calendar_diagnostics = {
        "requested_iso": date_iso,
        "choose_aria_label": choose_label,
        "navigation_steps": navigation_steps,
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
