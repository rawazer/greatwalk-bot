"""Tests for desktop People dropdown binding."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from greatwalkbot.infra.errors import GreatWalkPeopleDropdownError
from greatwalkbot.models import Track
from greatwalkbot.sources.gw_desktop_form import (
    DESKTOP_ROOT_SELECTOR,
    DesktopRootBinding,
    prepare_desktop_search_form,
)
from greatwalkbot.sources.gw_desktop_people_dropdown import (
    build_people_dropdown_diagnostics,
    inspect_people_dropdown,
    resolve_people_option,
    resolve_people_option_container,
    select_desktop_people,
)

MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)


def _button(people: int = 1) -> dict:
    return {
        "tag": "BUTTON",
        "id": "great-walk-people-dropdown-button",
        "visible_text": str(people),
        "aria_label": f"Number of People * {people}",
        "aria_expanded": "true",
        "enabled": True,
    }


def _option(people: int, *, mobile: bool = False, option_id: str | None = None) -> dict:
    return {
        "tag": "DIV",
        "id": option_id or f"great-walk-people-{people}" + ("-mobile" if mobile else ""),
        "text": str(people),
        "aria_label": None,
        "visible": True,
        "enabled": True,
        "likely_mobile": mobile,
        "container_id": "great-walk-people-dropdown-box",
        "data_attributes": {"data-value": str(people)},
    }


def _container() -> dict:
    return {
        "id": "great-walk-people-dropdown-box",
        "tag": "UL",
        "association_hint": "id-pattern",
        "visible": True,
        "enabled": True,
        "likely_mobile": False,
    }


def _discovery(*, people: int = 1, options: list[dict] | None = None) -> dict:
    return {
        "found": True,
        "button": _button(people),
        "containers": [_container()],
        "options": options or [_option(1), _option(2)],
    }


class _PeoplePage:
    def __init__(self, *, people: int = 1, options: list[dict] | None = None) -> None:
        self.people = people
        self.options = options or [_option(1), _option(2)]
        self.clicks = 0
        self._locators: dict[str, MagicMock] = {}

    def _state(self) -> dict:
        return {
            "desktop_root_count": 1,
            "desktop_root": {"selector": DESKTOP_ROOT_SELECTOR, "id": None, "class": "x"},
            "people_control": {
                "visible_text": str(self.people),
                "aria_label": f"Number of People * {self.people}",
                "aria_expanded": "false",
                "enabled": True,
            },
            "track_control": {"visible_text": "Milford Track", "enabled": True},
            "nights_control": {"visible_text": "3", "enabled": True},
            "start_date_control": {"visible_text": "26/06/2026", "data_date": "2026-06-26"},
            "search_button": {"visible_text": "Search", "enabled": True},
            "validation_messages": [],
            "loading_present": False,
        }

    def evaluate(self, expression: str, arg=None) -> object:
        if "desktop_root_count" in expression or "readBtn" in expression:
            return self._state()
        if "buttonSelector" in str(arg):
            return _discovery(people=self.people, options=self.options)
        if "elementFromPoint" in expression:
            return {"found": True, "clickable": True, "desktop_root_count": 1}
        return {}

    def locator(self, selector: str) -> MagicMock:
        if selector not in self._locators:
            loc = MagicMock()
            loc.count.return_value = 1
            loc.first = loc
            loc.is_enabled.return_value = True
            loc.filter.return_value = loc

            def nested(inner: str) -> MagicMock:
                inner_loc = MagicMock()
                inner_loc.first = inner_loc
                inner_loc.count.return_value = 1
                inner_loc.is_enabled.return_value = True

                def _click(**_kwargs: object) -> None:
                    self.clicks += 1
                    if "great-walk-people-2" in inner:
                        self.people = 2

                inner_loc.click.side_effect = _click
                return inner_loc

            loc.locator.side_effect = nested
            self._locators[selector] = loc
        return self._locators[selector]

    def wait_for_timeout(self, timeout: int) -> None:
        return None


def test_people_already_matched_skips_click():
    page = _PeoplePage(people=2)
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    with patch(
        "greatwalkbot.sources.gw_desktop_people_dropdown.click_desktop_control"
    ) as click:
        result = select_desktop_people(page, 2, binding)
    click.assert_not_called()
    assert result.action == "already_matched"


def test_custom_dropdown_selects_semantic_option_two():
    page = _PeoplePage(people=1)
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    with patch("greatwalkbot.sources.gw_desktop_people_dropdown.click_desktop_control"):
        with patch(
            "greatwalkbot.sources.gw_desktop_people_dropdown.wait_for_control_clickable"
        ):
            result = select_desktop_people(page, 2, binding)
    assert result.action == "changed_and_verified"
    assert result.normalized_value == "2"
    assert page.people == 2


def test_hidden_mobile_option_ignored():
    discovery = _discovery(options=[_option(2, mobile=True), _option(1)])
    container, method, _ = resolve_people_option_container(discovery)
    selected, reasons = resolve_people_option(
        discovery,
        2,
        container=container,
        association_method=method,
    )
    assert selected is None
    assert any("no semantic" in r for r in reasons)


def test_ambiguous_visible_two_candidates_fail():
    discovery = _discovery(
        options=[
            {**_option(2), "id": "people-2-a"},
            {**_option(2), "id": "people-2-b", "text": "2"},
        ]
    )
    container, method, _ = resolve_people_option_container(discovery)
    selected, reasons = resolve_people_option(
        discovery,
        2,
        container=container,
        association_method=method,
    )
    assert selected is None
    assert any("ambiguous" in r for r in reasons)


def test_verification_waits_until_button_updates():
    page = _PeoplePage(people=1)
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    with patch("greatwalkbot.sources.gw_desktop_people_dropdown.click_desktop_control"):
        with patch(
            "greatwalkbot.sources.gw_desktop_people_dropdown.wait_for_control_clickable"
        ):
            result = select_desktop_people(page, 2, binding)
    assert result.normalized_value == "2"


def test_remains_one_raises_with_diagnostics():
    page = _PeoplePage(people=1)
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    root_loc = page.locator(DESKTOP_ROOT_SELECTOR)

    def noop_click(**_kwargs: object) -> None:
        page.clicks += 1

    root_loc.locator.side_effect = lambda inner: _stub_locator(noop_click)

    with patch("greatwalkbot.sources.gw_desktop_people_dropdown.click_desktop_control"):
        with patch(
            "greatwalkbot.sources.gw_desktop_people_dropdown.wait_for_control_clickable"
        ):
            with pytest.raises(GreatWalkPeopleDropdownError, match="did not verify") as exc_info:
                select_desktop_people(page, 2, binding)
    diag = exc_info.value.people_dropdown_diagnostics
    assert diag is not None
    assert diag["requested_people"] == 2
    assert diag["post_click_value"] == "1"


def _stub_locator(click_fn) -> MagicMock:
    loc = MagicMock()
    loc.first = loc
    loc.count.return_value = 1
    loc.is_enabled.return_value = True
    loc.click.side_effect = click_fn
    return loc


def test_inspector_emits_bounded_people_dropdown_section():
    page = _PeoplePage(people=1)
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    with patch("greatwalkbot.sources.gw_desktop_people_dropdown.click_desktop_control"):
        report = inspect_people_dropdown(page, binding)
    assert "people_dropdown" in report
    section = report["people_dropdown"]
    assert section["requested_people"] == 1
    assert len(section["option_candidates"]) >= 1


def test_prepare_form_raises_people_dropdown_error_with_diagnostics():
    page = _PeoplePage(people=1)
    with patch("greatwalkbot.sources.gw_desktop_form.select_desktop_track"):
        with patch("greatwalkbot.sources.gw_desktop_form.refresh_desktop_root_binding") as refresh:
            binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
            refresh.return_value = (binding, {"root_replaced": False})
            with patch(
                "greatwalkbot.sources.gw_desktop_form.set_desktop_start_date",
                return_value={"action": "already_matched"},
            ):
                with patch("greatwalkbot.sources.gw_desktop_form.select_desktop_nights"):
                    with patch(
                        "greatwalkbot.sources.gw_desktop_people_dropdown.select_desktop_people",
                        side_effect=GreatWalkPeopleDropdownError(
                            "failed",
                            people_dropdown_diagnostics=build_people_dropdown_diagnostics(
                                _discovery(),
                                requested_people=2,
                                current_people=1,
                                association_method="id-pattern",
                                selected_candidate=None,
                                rejection_reasons=["test"],
                            ),
                        ),
                    ):
                        with pytest.raises(GreatWalkPeopleDropdownError):
                            prepare_desktop_search_form(
                                page,
                                MILFORD,
                                start_date=date(2026, 12, 7),
                                nights=3,
                                people_size=2,
                            )
