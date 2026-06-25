"""Tests for desktop React DatePicker binding."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from greatwalkbot.infra.errors import GreatWalkDatePickerError, GreatWalkDateUnavailableError
from greatwalkbot.sources.gw_desktop_date_picker import (
    DATE_MOBILE_SELECTOR,
    DATE_PICKER_NEXT,
    DATE_PICKER_PREV,
    build_choose_aria_label,
    build_unavailable_aria_label,
    click_date_picker_day,
    navigate_date_picker_to_month,
    ordinal_day,
    parse_month_year_header,
    select_desktop_date_via_react_picker,
    wait_for_date_picker_open,
)
from greatwalkbot.sources.gw_desktop_form import (
    DESKTOP_ROOT_SELECTOR,
    DesktopRootBinding,
    set_desktop_start_date,
)


def test_ordinal_day_suffixes():
    assert ordinal_day(1) == "1st"
    assert ordinal_day(2) == "2nd"
    assert ordinal_day(3) == "3rd"
    assert ordinal_day(7) == "7th"
    assert ordinal_day(26) == "26th"


def test_build_choose_aria_label_december_2026():
    label = build_choose_aria_label(date(2026, 12, 7))
    assert label == "Choose Monday, December 7th, 2026"


def test_build_unavailable_aria_label():
    label = build_unavailable_aria_label(date(2026, 6, 26))
    assert label == "Not available Friday, June 26th, 2026"


def test_parse_month_year_header():
    assert parse_month_year_header("June 2026") == date(2026, 6, 1)
    assert parse_month_year_header("December 2026") == date(2026, 12, 1)


class _PickerStatePage:
    def __init__(
        self,
        *,
        open_picker: bool = False,
        month_text: str = "June 2026",
        has_next: bool = True,
        has_prev: bool = True,
        day_labels: dict[str, int] | None = None,
    ) -> None:
        self.open_picker = open_picker
        self.month_text = month_text
        self.has_next = has_next
        self.has_prev = has_prev
        self.day_labels = day_labels or {}
        self.clicks: list[str] = []
        self._day_click_side_effect: object | None = None

    def evaluate(self, expression: str, arg=None) -> object:
        if "react-datepicker__month-container" in expression:
            return {
                "open": self.open_picker,
                "container_count": 1 if self.open_picker else 0,
                "month_text": self.month_text if self.open_picker else None,
                "has_next": self.has_next if self.open_picker else False,
                "has_prev": self.has_prev if self.open_picker else False,
            }
        if "react-datepicker__day" in expression:
            return list(self.day_labels.keys())[:15]
        return {}

    def locator(self, selector: str) -> MagicMock:
        loc = MagicMock()
        loc.first = loc
        if selector == DATE_PICKER_NEXT and self.has_next:
            loc.count.return_value = 1
            loc.click.side_effect = self._click_next
        elif selector == DATE_PICKER_PREV and self.has_prev:
            loc.count.return_value = 1
            loc.click.side_effect = self._click_prev
        else:
            loc.count.return_value = 0
        return loc

    def get_by_role(self, role: str, *, name: str | None = None, exact: bool = False) -> MagicMock:
        loc = MagicMock()
        count = self.day_labels.get(name or "", 0)
        loc.count.return_value = count
        loc.first = loc

        def _click() -> None:
            if name:
                self.clicks.append(name)
            if self._day_click_side_effect is not None:
                effect = self._day_click_side_effect
                if callable(effect):
                    effect()

        loc.click.side_effect = _click
        return loc

    def set_day_click_side_effect(self, effect: object) -> None:
        self._day_click_side_effect = effect

    def wait_for_timeout(self, timeout: int) -> None:
        return None

    def _click_next(self) -> None:
        from datetime import datetime

        current = datetime.strptime(self.month_text, "%B %Y")
        if current.month == 12:
            nxt = current.replace(year=current.year + 1, month=1)
        else:
            nxt = current.replace(month=current.month + 1)
        self.month_text = nxt.strftime("%B %Y")

    def _click_prev(self) -> None:
        from datetime import datetime

        current = datetime.strptime(self.month_text, "%B %Y")
        if current.month == 1:
            prev = current.replace(year=current.year - 1, month=12)
        else:
            prev = current.replace(month=current.month - 1)
        self.month_text = prev.strftime("%B %Y")


def test_navigate_six_months_to_december():
    page = _PickerStatePage(open_picker=True, month_text="June 2026")
    steps = navigate_date_picker_to_month(page, date(2026, 12, 7), date_iso="2026-12-07")
    assert page.month_text == "December 2026"
    assert steps[-1]["action"] == "arrived"
    assert len([s for s in steps if s.get("action") == "next"]) == 6


def test_unavailable_date_raises_typed_error():
    page = _PickerStatePage(
        open_picker=True,
        month_text="June 2026",
        day_labels={build_unavailable_aria_label(date(2026, 6, 26)): 1},
    )
    with pytest.raises(GreatWalkDateUnavailableError, match="Not available"):
        click_date_picker_day(
            page,
            date(2026, 6, 26),
            date_iso="2026-06-26",
            navigation_steps=[],
        )


def test_missing_next_navigation_raises():
    page = _PickerStatePage(open_picker=True, month_text="June 2026", has_next=False)
    with pytest.raises(GreatWalkDatePickerError, match="next-month"):
        navigate_date_picker_to_month(page, date(2026, 12, 7), date_iso="2026-12-07")


def test_picker_never_opens_raises():
    page = _PickerStatePage(open_picker=False)
    with pytest.raises(GreatWalkDatePickerError, match="did not open"):
        wait_for_date_picker_open(page, timeout_ms=50)


def test_select_future_date_via_aria_label():
    choose = build_choose_aria_label(date(2026, 12, 7))
    trigger = {
        "visible_text": "26/06/2026",
        "data_date": "2026-06-26",
        "aria_label": "Choose Friday, June 26th, 2026",
    }
    page = _PickerStatePage(open_picker=False, month_text="June 2026", day_labels={choose: 1})
    opened = {"value": False}

    def open_picker() -> None:
        opened["value"] = True
        page.open_picker = True

    def read_trigger() -> dict:
        return dict(trigger)

    def apply_selection() -> None:
        trigger["data_date"] = "2026-12-07"
        trigger["visible_text"] = "07/12/2026"
        trigger["aria_label"] = choose
        page.open_picker = False

    page.set_day_click_side_effect(apply_selection)

    result = select_desktop_date_via_react_picker(
        page,
        target=date(2026, 12, 7),
        open_picker=open_picker,
        read_start_date_control=read_trigger,
    )
    assert opened["value"] is True
    assert result["action"] == "changed_and_verified"
    assert result["normalized_iso"] == "2026-12-07"
    assert result["calendar_diagnostics"]["choose_aria_label"] == choose


def test_current_date_already_matches_skips_picker():
    trigger = {"visible_text": "07/12/2026", "data_date": "2026-12-07", "aria_label": None}
    page = _PickerStatePage()
    opened = {"value": False}

    result = select_desktop_date_via_react_picker(
        page,
        target=date(2026, 12, 7),
        open_picker=lambda: opened.update(value=True),
        read_start_date_control=lambda: trigger,
    )
    assert result["action"] == "already_matched"
    assert opened["value"] is False


def test_post_selection_verification_failure():
    choose = build_choose_aria_label(date(2026, 12, 7))
    trigger = {"visible_text": "26/06/2026", "data_date": "2026-06-26", "aria_label": None}
    page = _PickerStatePage(open_picker=False, month_text="December 2026", day_labels={choose: 1})

    def open_picker() -> None:
        page.open_picker = True
        page.month_text = "December 2026"

    def read_trigger() -> dict:
        return dict(trigger)

    page.set_day_click_side_effect(lambda: setattr(page, "open_picker", False))

    with pytest.raises(GreatWalkDatePickerError, match="expected '2026-12-07'"):
        select_desktop_date_via_react_picker(
            page,
            target=date(2026, 12, 7),
            open_picker=open_picker,
            read_start_date_control=read_trigger,
        )


def _desktop_state(data_date: str, visible_text: str) -> dict:
    return {
        "desktop_root_count": 1,
        "desktop_root": {"selector": DESKTOP_ROOT_SELECTOR, "id": None, "class": "themeTopsearch"},
        "track_control": {"visible_text": "Milford Track", "enabled": True},
        "nights_control": {"visible_text": "3", "enabled": True},
        "people_control": {"visible_text": "1", "enabled": True},
        "start_date_control": {
            "visible_text": visible_text,
            "data_date": data_date,
            "enabled": True,
        },
        "search_button": {"visible_text": "Search", "enabled": True},
        "validation_messages": [],
        "loading_present": False,
    }


class _DesktopDatePage(_PickerStatePage):
    def __init__(self, state: dict) -> None:
        super().__init__()
        self.state = state
        self._locators: dict[str, MagicMock] = {}

    def evaluate(self, expression: str, arg=None) -> object:
        if "desktop_root_count" in expression or "readBtn" in expression:
            return self.state
        return super().evaluate(expression, arg)

    def locator(self, selector: str) -> MagicMock:
        if selector not in self._locators:
            loc = MagicMock()
            loc.count.return_value = 1
            loc.first = loc
            loc.is_enabled.return_value = True
            if selector == DATE_MOBILE_SELECTOR:
                loc.count.return_value = 1
                loc.first.is_visible.return_value = False
            self._locators[selector] = loc
        return self._locators[selector]


def test_set_desktop_start_date_never_clicks_mobile_control():
    page = _DesktopDatePage(_desktop_state("2026-12-07", "07/12/2026"))
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    with patch("greatwalkbot.sources.gw_desktop_form.click_desktop_control") as click:
        with patch(
            "greatwalkbot.sources.gw_desktop_form.select_desktop_date_via_react_picker",
            return_value={"action": "already_matched", "calendar_diagnostics": {}},
        ):
            set_desktop_start_date(page, date(2026, 12, 7), binding)
    for call in click.call_args_list:
        assert DATE_MOBILE_SELECTOR not in str(call)


def test_set_desktop_start_date_already_matched_does_not_open_picker():
    page = _DesktopDatePage(_desktop_state("2026-12-07", "07/12/2026"))
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    with patch("greatwalkbot.sources.gw_desktop_form.click_desktop_control") as click:
        result = set_desktop_start_date(page, date(2026, 12, 7), binding)
    click.assert_not_called()
    assert result["action"] == "already_matched"
