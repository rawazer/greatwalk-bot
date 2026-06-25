"""Tests for desktop date-picker popup navigation binding."""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from greatwalkbot.infra.errors import GreatWalkDatePickerError
from greatwalkbot.sources.gw_desktop_date_picker import (
    build_choose_aria_label,
    navigate_and_select_target_day,
)
from greatwalkbot.sources.gw_desktop_date_picker_popup import (
    CalendarNavigationControls,
    ResolvedNavControl,
    click_popup_navigation_control,
    inspect_date_picker_navigation,
    resolve_calendar_navigation_controls,
)

_picker_test_path = Path(__file__).with_name("test_gw_desktop_date_picker.py")
_picker_spec = importlib.util.spec_from_file_location(
    "gw_picker_test_helpers",
    _picker_test_path,
)
assert _picker_spec and _picker_spec.loader
_picker_mod = importlib.util.module_from_spec(_picker_spec)
_picker_spec.loader.exec_module(_picker_mod)
_PickerStatePage = _picker_mod._PickerStatePage


def _popup_rect(width: int = 280) -> dict:
    return {"x": 100, "y": 200, "width": width, "height": 300}


def _candidate(
    *,
    index: int,
    rel_x: int,
    aria_label: str | None = None,
    class_name: str = "gw-chevron",
    react_next: bool = False,
    react_prev: bool = False,
    near_left: bool = False,
    near_right: bool = False,
) -> dict:
    width = 280
    return {
        "index": index,
        "tag": "BUTTON",
        "id": None,
        "class": class_name,
        "role": "button",
        "aria_label": aria_label,
        "title": None,
        "text": None,
        "visible": True,
        "enabled": True,
        "popup_relative_x": rel_x,
        "popup_relative_y": 8,
        "in_upper_portion": True,
        "near_left_edge": near_left or rel_x <= width * 0.25,
        "near_right_edge": near_right or rel_x >= width * 0.75,
        "react_next": react_next,
        "react_prev": react_prev,
    }


def test_semantic_next_previous_resolution():
    discovery = {
        "popup": {"rect": _popup_rect()},
        "candidates": [
            _candidate(index=0, rel_x=10, aria_label="Previous month", react_prev=True),
            _candidate(index=1, rel_x=250, aria_label="Next month", react_next=True),
        ],
        "standard_nav": {"next": True, "prev": True},
    }
    controls = resolve_calendar_navigation_controls(discovery)
    assert controls.resolution_method == "semantic"
    assert controls.previous is not None
    assert controls.next is not None
    assert controls.previous.candidate["aria_label"] == "Previous month"
    assert controls.next.candidate["aria_label"] == "Next month"


def test_geometric_fallback_without_standard_react_classes():
    discovery = {
        "popup": {"rect": _popup_rect()},
        "candidates": [
            _candidate(index=0, rel_x=12, class_name="gw-header-chevron-left"),
            _candidate(index=1, rel_x=248, class_name="gw-header-chevron-right"),
        ],
        "standard_nav": {"next": False, "prev": False},
    }
    controls = resolve_calendar_navigation_controls(discovery)
    assert controls.resolution_method == "geometric_fallback"
    assert controls.previous is not None
    assert controls.next is not None
    assert controls.previous.candidate["class"] == "gw-header-chevron-left"
    assert controls.next.candidate["class"] == "gw-header-chevron-right"


def test_hidden_mobile_candidates_not_in_discovery_payload():
    discovery = {
        "popup": {"rect": _popup_rect()},
        "candidates": [
            _candidate(index=0, rel_x=12, class_name="mobile-only-left"),
            _candidate(index=1, rel_x=248, class_name="gw-header-chevron-right"),
        ],
        "standard_nav": {"next": False, "prev": False},
    }
    controls = resolve_calendar_navigation_controls(discovery)
    assert controls.previous is not None
    assert controls.next is not None
    assert "mobile-only-left" in controls.previous.candidate["class"]


def test_ambiguous_header_candidates_fail_safely():
    discovery = {
        "popup": {"rect": _popup_rect()},
        "candidates": [
            _candidate(index=0, rel_x=20, class_name="edge-a"),
            _candidate(index=1, rel_x=40, class_name="edge-b"),
            _candidate(index=2, rel_x=60, class_name="edge-c"),
        ],
        "standard_nav": {"next": False, "prev": False},
    }
    controls = resolve_calendar_navigation_controls(discovery)
    assert controls.resolution_method == "unresolved"
    assert controls.next is None or controls.previous is None
    assert controls.rejection_reasons


def test_navigation_re_resolves_after_dom_replacement():
    page = _PickerStatePage(
        open_picker=True,
        month_text="June 2026",
        visible_labels=[build_choose_aria_label(date(2026, 6, 1))],
        use_standard_react_nav=False,
    )
    original_click = page._click_next

    def click_with_generation_bump(**_kwargs: object) -> None:
        page._nav_resolve_generation += 1
        original_click()

    page._click_next = click_with_generation_bump  # type: ignore[method-assign]
    label, steps = navigate_and_select_target_day(page, date(2026, 12, 7), date_iso="2026-12-07")
    assert label == build_choose_aria_label(date(2026, 12, 7))
    assert page._nav_resolve_generation == 6
    assert len([s for s in steps if s.get("action") == "next"]) == 6


def test_geometric_fallback_navigates_six_months():
    page = _PickerStatePage(
        open_picker=True,
        month_text="June 2026",
        visible_labels=[build_choose_aria_label(date(2026, 6, 1))],
        use_standard_react_nav=False,
    )
    label, steps = navigate_and_select_target_day(page, date(2026, 12, 7), date_iso="2026-12-07")
    assert label == build_choose_aria_label(date(2026, 12, 7))
    assert len([s for s in steps if s.get("action") == "next"]) == 6


def test_fingerprint_unchanged_after_click_fails_with_navigation_diagnostics():
    page = _PickerStatePage(
        open_picker=True,
        month_text=None,
        visible_labels=[build_choose_aria_label(date(2026, 6, 1))],
    )
    page._click_next = lambda **_kwargs: None  # type: ignore[method-assign]
    with pytest.raises(GreatWalkDatePickerError, match="fingerprint unchanged") as exc_info:
        navigate_and_select_target_day(page, date(2026, 12, 7), date_iso="2026-12-07")
    diag = exc_info.value.calendar_diagnostics
    assert diag is not None
    assert "date_picker_navigation" in diag
    assert diag.get("fingerprint_before") is not None
    assert diag.get("fingerprint_after") is not None


def test_inspect_date_picker_navigation_section():
    page = MagicMock()
    with patch(
        "greatwalkbot.sources.gw_desktop_date_picker_popup.resolve_visible_desktop_date_picker"
    ) as resolve_popup:
        with patch(
            "greatwalkbot.sources.gw_desktop_date_picker_popup.discover_popup_navigation_raw"
        ) as discover:
            resolve_popup.return_value = MagicMock(
                descriptor={"popup": {"strategy": ".react-datepicker-popper"}}
            )
            discover.return_value = {
                "popup": {"rect": _popup_rect()},
                "candidates": [
                    _candidate(index=0, rel_x=12, class_name="gw-header-chevron-left"),
                    _candidate(index=1, rel_x=248, class_name="gw-header-chevron-right"),
                ],
                "standard_nav": {"next": False, "prev": False},
            }
            report = inspect_date_picker_navigation(page)
    assert "date_picker_popup" in report
    nav = report["date_picker_navigation"]
    assert nav["candidate_count"] == 2
    assert nav["resolved_next"]["class"] == "gw-header-chevron-right"
    assert nav["resolution_method"] == "geometric_fallback"


def test_click_popup_navigation_control_raises_when_unresolved():
    page = MagicMock()
    popup = MagicMock()
    unresolved = CalendarNavigationControls(
        popup={},
        candidates=[],
        previous=None,
        next=None,
        resolution_method="unresolved",
        rejection_reasons=["missing"],
        popup_selector=".react-datepicker-popper",
    )
    with patch(
        "greatwalkbot.sources.gw_desktop_date_picker_popup.discover_popup_navigation_raw",
        return_value={"candidates": []},
    ):
        with patch(
            "greatwalkbot.sources.gw_desktop_date_picker_popup.resolve_calendar_navigation_controls",
            return_value=unresolved,
        ):
            with pytest.raises(GreatWalkDatePickerError, match="next-month"):
                click_popup_navigation_control(
                    page,
                    popup,
                    ResolvedNavControl(candidate={}, resolution_method="semantic"),
                    direction="next",
                )
