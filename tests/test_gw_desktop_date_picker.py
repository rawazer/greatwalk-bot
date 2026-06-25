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
    day_label_fingerprint,
    infer_month_from_day_labels,
    navigate_and_select_target_day,
    navigate_date_picker_to_month,
    ordinal_day,
    parse_month_year_from_day_label,
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
    assert parse_month_year_header(None) is None


def test_parse_month_year_from_day_label():
    label = build_choose_aria_label(date(2026, 12, 7))
    assert parse_month_year_from_day_label(label) == date(2026, 12, 1)
    assert infer_month_from_day_labels([label]) == date(2026, 12, 1)


class _PickerStatePage:
    def __init__(
        self,
        *,
        open_picker: bool = False,
        month_text: str | None = "June 2026",
        has_next: bool = True,
        has_prev: bool = True,
        visible_labels: list[str] | None = None,
    ) -> None:
        self.open_picker = open_picker
        self.month_text = month_text
        self.has_next = has_next
        self.has_prev = has_prev
        self.visible_labels = list(visible_labels or [])
        self.clicks: list[str] = []
        self._day_click_side_effect: object | None = None
        self._nav_clicks = 0

    def evaluate(self, expression: str, arg=None) -> object:
        if "selector_counts" in expression:
            return {
                "selector_counts": {
                    "current_month": 1 if self.month_text else 0,
                    "month_container": 1 if self.open_picker else 0,
                    "day_buttons": len(self.visible_labels),
                    "nav_next": 1 if self.has_next and self.open_picker else 0,
                    "nav_prev": 1 if self.has_prev and self.open_picker else 0,
                },
                "month_text": self.month_text if self.open_picker else None,
                "visible_day_labels": list(self.visible_labels)[:15],
            }
        if "react-datepicker__month-container" in expression:
            return {
                "open": self.open_picker,
                "container_count": 1 if self.open_picker else 0,
                "month_text": self.month_text if self.open_picker else None,
                "has_next": self.has_next if self.open_picker else False,
                "has_prev": self.has_prev if self.open_picker else False,
            }
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
        count = 1 if name in self.visible_labels else 0
        loc.count.return_value = count
        loc.first = loc

        def _click() -> None:
            if name:
                self.clicks.append(name)
            if self._day_click_side_effect is not None and callable(self._day_click_side_effect):
                self._day_click_side_effect()

        loc.click.side_effect = _click
        return loc

    def set_day_click_side_effect(self, effect: object) -> None:
        self._day_click_side_effect = effect

    def wait_for_timeout(self, timeout: int) -> None:
        return None

    def _labels_for_month(self, month_text: str | None) -> list[str]:
        if not month_text:
            return [build_choose_aria_label(date(2026, 6, 1))]
        from datetime import datetime

        current = datetime.strptime(month_text, "%B %Y")
        return [build_choose_aria_label(date(current.year, current.month, day)) for day in (1, 7, 15)]

    def _click_next(self) -> None:
        from datetime import datetime

        self._nav_clicks += 1
        if self.month_text:
            current = datetime.strptime(self.month_text, "%B %Y")
            if current.month == 12:
                nxt = current.replace(year=current.year + 1, month=1)
            else:
                nxt = current.replace(month=current.month + 1)
            self.month_text = nxt.strftime("%B %Y")
        else:
            inferred = infer_month_from_day_labels(self.visible_labels) or date(2026, 6, 1)
            current = datetime(inferred.year, inferred.month, 1)
            if current.month == 12:
                nxt = current.replace(year=current.year + 1, month=1)
            else:
                nxt = current.replace(month=current.month + 1)
            self.month_text = nxt.strftime("%B %Y")
        self.visible_labels = self._labels_for_month(self.month_text)
        if self.month_text == "December 2026":
            self.visible_labels.append(build_choose_aria_label(date(2026, 12, 7)))

    def _click_prev(self) -> None:
        from datetime import datetime

        if not self.month_text:
            return
        current = datetime.strptime(self.month_text, "%B %Y")
        if current.month == 1:
            prev = current.replace(year=current.year - 1, month=12)
        else:
            prev = current.replace(month=current.month - 1)
        self.month_text = prev.strftime("%B %Y")
        self.visible_labels = self._labels_for_month(self.month_text)


def test_no_header_target_date_already_visible():
    choose = build_choose_aria_label(date(2026, 12, 7))
    page = _PickerStatePage(
        open_picker=True,
        month_text=None,
        visible_labels=[choose],
    )
    label, steps = navigate_and_select_target_day(page, date(2026, 12, 7), date_iso="2026-12-07")
    assert label == choose
    assert steps == [{"action": "target_already_visible"}]
    assert choose in page.clicks


def test_no_header_navigation_succeeds_using_day_label_fingerprint():
    page = _PickerStatePage(
        open_picker=True,
        month_text=None,
        visible_labels=[build_choose_aria_label(date(2026, 6, 1))],
    )
    label, steps = navigate_and_select_target_day(page, date(2026, 12, 7), date_iso="2026-12-07")
    assert label == build_choose_aria_label(date(2026, 12, 7))
    assert len([s for s in steps if s.get("action") == "next"]) == 6
    assert steps[-1]["action"] == "target_found_after_navigation"


def test_no_header_requested_date_unavailable():
    unavailable = build_unavailable_aria_label(date(2026, 12, 7))
    page = _PickerStatePage(open_picker=True, month_text=None, visible_labels=[unavailable])
    with pytest.raises(GreatWalkDateUnavailableError, match="Not available"):
        navigate_and_select_target_day(page, date(2026, 12, 7), date_iso="2026-12-07")


def test_header_exists_still_supported():
    page = _PickerStatePage(open_picker=True, month_text="December 2026", visible_labels=[])
    page.visible_labels = [build_choose_aria_label(date(2026, 12, 7))]
    steps = navigate_date_picker_to_month(page, date(2026, 12, 7), date_iso="2026-12-07")
    assert steps == [{"action": "target_already_visible"}]


def test_navigation_unchanged_fingerprint_fails_honestly():
    label = build_choose_aria_label(date(2026, 6, 1))
    page = _PickerStatePage(
        open_picker=True,
        month_text=None,
        visible_labels=[label],
        has_next=True,
    )
    page._click_next = lambda: None  # type: ignore[method-assign]
    with pytest.raises(GreatWalkDatePickerError, match="fingerprint unchanged"):
        navigate_and_select_target_day(page, date(2026, 12, 7), date_iso="2026-12-07")


def test_no_header_or_day_labels_fails_with_diagnostics():
    page = _PickerStatePage(
        open_picker=True,
        month_text=None,
        visible_labels=[],
        has_next=False,
        has_prev=False,
    )
    with pytest.raises(GreatWalkDatePickerError, match="no usable month header") as exc_info:
        navigate_and_select_target_day(page, date(2026, 12, 7), date_iso="2026-12-07")
    diag = exc_info.value.calendar_diagnostics
    assert diag is not None
    assert "choose_aria_label" in diag
    assert "visible_day_labels" in diag


def test_navigate_six_months_to_december_with_header():
    page = _PickerStatePage(
        open_picker=True,
        month_text="June 2026",
        visible_labels=[build_choose_aria_label(date(2026, 6, 1))],
    )
    steps = navigate_date_picker_to_month(page, date(2026, 12, 7), date_iso="2026-12-07")
    assert page.month_text == "December 2026"
    assert steps[-1]["action"] == "arrived"
    assert len([s for s in steps if s.get("action") == "next"]) == 6


def test_unavailable_date_raises_typed_error():
    page = _PickerStatePage(
        open_picker=True,
        month_text="June 2026",
        visible_labels=[build_unavailable_aria_label(date(2026, 6, 26))],
    )
    with pytest.raises(GreatWalkDateUnavailableError, match="Not available"):
        click_date_picker_day(
            page,
            date(2026, 6, 26),
            date_iso="2026-06-26",
            navigation_steps=[],
        )


def test_missing_next_navigation_raises():
    page = _PickerStatePage(
        open_picker=True,
        month_text="June 2026",
        visible_labels=[build_choose_aria_label(date(2026, 6, 1))],
        has_next=False,
    )
    with pytest.raises(GreatWalkDatePickerError, match="next-month"):
        navigate_and_select_target_day(page, date(2026, 12, 7), date_iso="2026-12-07")


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
    page = _PickerStatePage(
        open_picker=False,
        month_text=None,
        visible_labels=[build_choose_aria_label(date(2026, 6, 1))],
    )
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
    page = _PickerStatePage(
        open_picker=False,
        month_text="December 2026",
        visible_labels=[choose],
    )

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


def test_day_label_fingerprint_stable():
    labels = [
        build_choose_aria_label(date(2026, 6, 1)),
        build_choose_aria_label(date(2026, 6, 7)),
    ]
    fp = day_label_fingerprint(labels)
    assert fp["count"] == 2
    assert fp["first"] == labels[0]
    assert fp["last"] == labels[1]


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
