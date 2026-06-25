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
    click_target_day_in_picker,
    day_label_fingerprint,
    infer_month_from_day_labels,
    navigate_and_select_target_day,
    navigate_date_picker_to_month,
    ordinal_day,
    parse_month_year_from_day_label,
    parse_month_year_header,
    resolve_target_day_candidates,
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
        use_standard_react_nav: bool = True,
    ) -> None:
        self.open_picker = open_picker
        self.month_text = month_text
        self.has_next = has_next
        self.has_prev = has_prev
        self.use_standard_react_nav = use_standard_react_nav
        self.visible_labels = list(visible_labels or [])
        self.day_candidates: dict[str, list[dict]] = {}
        self.clicks: list[str] = []
        self._day_click_side_effect: object | None = None
        self._nav_clicks = 0
        self._nav_resolve_generation = 0

    def set_day_candidates(self, label: str, candidates: list[dict]) -> None:
        self.day_candidates[label] = candidates
        if any(candidate.get("visible") and not candidate.get("outside_month") for candidate in candidates):
            if label not in self.visible_labels:
                self.visible_labels.append(label)

    def _candidates_for_label(self, label: str) -> list[dict]:
        if label in self.day_candidates:
            return list(self.day_candidates[label])
        if label in self.visible_labels:
            return [
                {
                    "index": 0,
                    "tag": "DIV",
                    "role": "button",
                    "class": "react-datepicker__day",
                    "aria_label": label,
                    "visible": True,
                    "enabled": True,
                    "outside_month": False,
                    "clickable": True,
                    "in_popup": True,
                    "rect": {"x": 120, "y": 220, "width": 24, "height": 24},
                }
            ]
        return []

    def _target_day_probe(self, choose_label: str, unavailable_label: str) -> dict:
        if not self.open_picker:
            return {
                "found": False,
                "popup_found": False,
                "choose_label": choose_label,
                "unavailable_label": unavailable_label,
                "choose_candidates": [],
                "unavailable_candidates": [],
            }
        return {
            "found": True,
            "popup_found": True,
            "choose_label": choose_label,
            "unavailable_label": unavailable_label,
            "choose_candidates": self._candidates_for_label(choose_label),
            "unavailable_candidates": self._candidates_for_label(unavailable_label),
        }

    def _popup_inner_locator(self, inner: str) -> MagicMock:
        inner_loc = MagicMock()
        inner_loc.first = inner_loc
        outside_filter = ":not(.react-datepicker__day--outside-month)" in inner
        if inner.startswith('[aria-label="') and '"]' in inner:
            label_part = inner.split('[aria-label="', 1)[1]
            label = label_part.split('"]', 1)[0].replace('\\"', '"')
            candidates = self._candidates_for_label(label)
            viable = [
                candidate
                for candidate in candidates
                if candidate.get("visible")
                and candidate.get("enabled", True)
                and (not outside_filter or not candidate.get("outside_month"))
            ]
            inner_loc.count.return_value = len(viable)

            def _click(**_kwargs: object) -> None:
                if label and viable:
                    self.clicks.append(label)
                if self._day_click_side_effect is not None and callable(
                    self._day_click_side_effect
                ):
                    self._day_click_side_effect()

            inner_loc.click.side_effect = _click
            return inner_loc
        if (
            DATE_PICKER_NEXT in inner
            or "gw-header-chevron-right" in inner
            or inner == ".gw-header-chevron-right"
        ):
            inner_loc.count.return_value = 1 if self.has_next else 0
            inner_loc.click.side_effect = self._click_next
        elif (
            DATE_PICKER_PREV in inner
            or "gw-header-chevron-left" in inner
            or inner == ".gw-header-chevron-left"
        ):
            inner_loc.count.return_value = 1 if self.has_prev else 0
            inner_loc.click.side_effect = self._click_prev
        else:
            inner_loc.count.return_value = 0
        return inner_loc

    def _popup_locator(self) -> MagicMock:
        loc = MagicMock()
        loc.first = loc
        loc.count.return_value = 1 if self.open_picker else 0
        loc.locator.side_effect = self._popup_inner_locator
        loc.filter.return_value = loc
        return loc

    def _popup_descriptor(self) -> dict:
        return {
            "strategy": ".react-datepicker-popper",
            "tag": "DIV",
            "id": None,
            "class": "react-datepicker-popper",
            "rect": {"x": 100, "y": 200, "width": 280, "height": 300},
        }

    def _navigation_candidates(self) -> list[dict]:
        candidates: list[dict] = []
        popup_width = 280
        if self.has_prev:
            candidates.append(
                {
                    "index": len(candidates),
                    "tag": "BUTTON",
                    "id": None,
                    "class": (
                        "react-datepicker__navigation react-datepicker__navigation--previous"
                        if self.use_standard_react_nav
                        else "gw-header-chevron-left gw-header-chevron"
                    ),
                    "role": "button",
                    "aria_label": (
                        "Previous month" if self.use_standard_react_nav else None
                    ),
                    "title": None,
                    "text": None,
                    "visible": True,
                    "enabled": True,
                    "popup_relative_x": 10,
                    "popup_relative_y": 8,
                    "in_upper_portion": True,
                    "near_left_edge": True,
                    "near_right_edge": False,
                    "react_prev": self.use_standard_react_nav,
                    "react_next": False,
                }
            )
        if self.has_next:
            candidates.append(
                {
                    "index": len(candidates),
                    "tag": "BUTTON",
                    "id": None,
                    "class": (
                        "react-datepicker__navigation react-datepicker__navigation--next"
                        if self.use_standard_react_nav
                        else "gw-header-chevron-right gw-header-chevron"
                    ),
                    "role": "button",
                    "aria_label": "Next month" if self.use_standard_react_nav else None,
                    "title": None,
                    "text": None,
                    "visible": True,
                    "enabled": True,
                    "popup_relative_x": popup_width - 30,
                    "popup_relative_y": 8,
                    "in_upper_portion": True,
                    "near_left_edge": False,
                    "near_right_edge": True,
                    "react_prev": False,
                    "react_next": self.use_standard_react_nav,
                }
            )
        return candidates

    def evaluate(self, expression: str, arg=None) -> object:
        if isinstance(arg, dict) and "chooseLabel" in arg:
            return self._target_day_probe(arg["chooseLabel"], arg["unavailableLabel"])
        if "triggerSelector" in expression:
            if not self.open_picker:
                return {"found": False, "popup_count": 0, "popups": [], "reason": "closed"}
            popup = self._popup_descriptor()
            return {
                "found": True,
                "popup_count": 1,
                "popup": popup,
                "popups": [popup],
            }
        if "standard_nav" in expression and "candidates" in expression:
            if not self.open_picker:
                return {"found": False, "popup": None, "candidates": []}
            popup = self._popup_descriptor()
            return {
                "found": True,
                "popup": popup,
                "candidates": self._navigation_candidates(),
                "standard_nav": {
                    "next": self.has_next and self.use_standard_react_nav,
                    "prev": self.has_prev and self.use_standard_react_nav,
                },
            }
        if "labels" in expression and "month_text" in expression:
            return {
                "month_text": self.month_text if self.open_picker else None,
                "labels": list(self.visible_labels)[:15],
            }
        return {}

    def locator(self, selector: str) -> MagicMock:
        if "[id*='-mobile']" in selector:
            loc = MagicMock()
            loc.count.return_value = 0
            loc.filter.return_value = loc
            return loc
        if ".react-datepicker-popper" in selector:
            return self._popup_locator()
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

        def _click(**_kwargs: object) -> None:
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

    def _click_next(self, **_kwargs: object) -> None:
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

    def _click_prev(self, **_kwargs: object) -> None:
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
    page._click_next = lambda **_kwargs: None  # type: ignore[method-assign]
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


def _candidate(
    *,
    index: int,
    label: str,
    visible: bool = True,
    outside_month: bool = False,
    enabled: bool = True,
) -> dict:
    return {
        "index": index,
        "tag": "DIV",
        "role": "button",
        "class": (
            "react-datepicker__day custom-datepicker-day "
            + ("react-datepicker__day--outside-month" if outside_month else "")
        ).strip(),
        "aria_label": label,
        "aria_disabled": None,
        "visible": visible,
        "enabled": enabled,
        "outside_month": outside_month,
        "clickable": visible and enabled,
        "rect": {"x": 120 + index * 10, "y": 220, "width": 24, "height": 24},
        "in_popup": True,
    }


def test_resolve_target_day_prefers_visible_in_month_over_hidden_outside_month():
    label = build_choose_aria_label(date(2026, 12, 3))
    probe = {
        "choose_label": label,
        "unavailable_label": build_unavailable_aria_label(date(2026, 12, 3)),
        "choose_candidates": [
            _candidate(index=0, label=label, visible=False, outside_month=True),
            _candidate(index=1, label=label, visible=True, outside_month=False),
        ],
        "unavailable_candidates": [],
    }
    resolution = resolve_target_day_candidates(probe)
    assert resolution.status == "choose"
    assert resolution.selected_candidate is not None
    assert resolution.selected_candidate["index"] == 1


def test_resolve_target_day_prefers_in_month_over_visible_outside_month():
    label = build_choose_aria_label(date(2026, 12, 3))
    probe = {
        "choose_label": label,
        "unavailable_label": build_unavailable_aria_label(date(2026, 12, 3)),
        "choose_candidates": [
            _candidate(index=0, label=label, visible=True, outside_month=True),
            _candidate(index=1, label=label, visible=True, outside_month=False),
        ],
        "unavailable_candidates": [],
    }
    resolution = resolve_target_day_candidates(probe)
    assert resolution.status == "choose"
    assert resolution.selected_candidate is not None
    assert resolution.selected_candidate["index"] == 1


def test_only_outside_month_candidate_is_absent():
    label = build_choose_aria_label(date(2026, 12, 3))
    probe = {
        "choose_label": label,
        "unavailable_label": build_unavailable_aria_label(date(2026, 12, 3)),
        "choose_candidates": [
            _candidate(index=0, label=label, visible=True, outside_month=True),
        ],
        "unavailable_candidates": [],
    }
    resolution = resolve_target_day_candidates(probe)
    assert resolution.status == "absent"
    assert any("outside_month=True" in reason for reason in resolution.rejection_reasons)


def test_only_outside_month_raises_typed_error_on_click():
    label = build_choose_aria_label(date(2026, 12, 3))
    page = _PickerStatePage(open_picker=True, month_text="December 2026", visible_labels=[])
    page.set_day_candidates(
        label,
        [_candidate(index=0, label=label, visible=True, outside_month=True)],
    )
    with pytest.raises(GreatWalkDatePickerError, match="No viable date-picker day button") as exc_info:
        click_target_day_in_picker(page, date(2026, 12, 3), date_iso="2026-12-03")
    diag = exc_info.value.calendar_diagnostics
    assert diag is not None
    assert "target_day_selection" in diag
    assert len(diag["target_day_selection"]["choose_candidates"]) == 1


def test_duplicate_choose_candidates_clicks_visible_in_month():
    label = build_choose_aria_label(date(2026, 12, 3))
    page = _PickerStatePage(open_picker=True, month_text="December 2026", visible_labels=[])
    page.set_day_candidates(
        label,
        [
            _candidate(index=0, label=label, visible=False, outside_month=True),
            _candidate(index=1, label=label, visible=True, outside_month=False),
        ],
    )
    page.set_day_click_side_effect(lambda: setattr(page, "open_picker", False))
    click_target_day_in_picker(page, date(2026, 12, 3), date_iso="2026-12-03")
    assert label in page.clicks


def test_not_available_candidate_raises_typed_unavailable_error():
    label = build_unavailable_aria_label(date(2026, 12, 3))
    page = _PickerStatePage(open_picker=True, month_text="December 2026", visible_labels=[])
    page.set_day_candidates(label, [_candidate(index=0, label=label, visible=True)])
    with pytest.raises(GreatWalkDateUnavailableError, match="Not available"):
        click_target_day_in_picker(page, date(2026, 12, 3), date_iso="2026-12-03")


def test_target_day_error_includes_bounded_candidate_diagnostics():
    label = build_choose_aria_label(date(2026, 12, 3))
    page = _PickerStatePage(open_picker=True, month_text="December 2026", visible_labels=[])
    page.set_day_candidates(
        label,
        [_candidate(index=0, label=label, visible=True, outside_month=True)],
    )
    with pytest.raises(GreatWalkDatePickerError) as exc_info:
        click_target_day_in_picker(page, date(2026, 12, 3), date_iso="2026-12-03")
    diag = exc_info.value.calendar_diagnostics
    assert diag is not None
    selection = diag["target_day_selection"]
    assert selection["choose_label"] == label
    assert len(selection["choose_candidates"]) == 1
    assert selection["choose_candidates"][0]["outside_month"] is True
    assert selection["rejection_reasons"]
