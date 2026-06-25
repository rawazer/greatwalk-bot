"""Tests for desktop Nights dropdown binding."""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest

from greatwalkbot.infra.errors import (
    GreatWalkNightsDropdownError,
    GreatWalkNightsTrackConstraintError,
)
from greatwalkbot.sources.gw_desktop_form import (
    DESKTOP_ROOT_SELECTOR,
    NIGHTS_LIST_SELECTOR,
    DesktopRootBinding,
    prepare_desktop_search_form,
)
from greatwalkbot.sources.gw_desktop_nights_dropdown import (
    _evaluate_zero_based_binding,
    inspect_nights_control,
    select_desktop_nights,
    zero_based_option_element_id,
)
from greatwalkbot.models import Track

MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)
ROUTEBURN = Track("routeburn", "Routeburn Track", 874, 7, fixed_nights=2)
KEPLER = Track("kepler", "Kepler Track", 872, 2, fixed_nights=3)


def _option(
    nights: int,
    *,
    mobile: bool = False,
    option_id: str | None = None,
    visible: bool = True,
    text: str | None = None,
    enabled: bool = True,
) -> dict:
    return {
        "tag": "A",
        "id": option_id or (f"great-walk-night-{nights - 1}" + ("-mobile" if mobile else "")),
        "text": text if text is not None else str(nights),
        "visible": visible,
        "enabled": enabled,
        "likely_mobile": mobile,
        "rect": {"x": 110, "y": 90 + nights * 24, "width": 60, "height": 20},
    }


class _NightsPage:
    def __init__(
        self,
        *,
        nights: int = 1,
        editable: bool = True,
        options: list[dict] | None = None,
        non_editable_evidence: list[str] | None = None,
    ) -> None:
        self.nights = nights
        self.editable = editable
        self.opened = False
        self.options = options or [_option(1), _option(2), _option(3)]
        self.non_editable_evidence = non_editable_evidence or []
        self.clicks = 0
        self._locators: dict[str, MagicMock] = {}

    def _state(self) -> dict:
        return {
            "desktop_root_count": 1,
            "desktop_root": {"selector": DESKTOP_ROOT_SELECTOR, "id": None, "class": "x"},
            "nights_control": {
                "visible_text": str(self.nights),
                "normalized_value": str(self.nights),
                "aria_label": f"Number of Nights * {self.nights}",
                "aria_expanded": "true" if self.opened else "false",
                "enabled": self.editable,
            },
            "track_control": {"visible_text": "Routeburn Track", "enabled": True},
            "people_control": {"visible_text": "1", "enabled": True},
            "start_date_control": {"visible_text": "03/12/2026", "data_date": "2026-12-03"},
            "search_button": {"visible_text": "Search", "enabled": True},
            "validation_messages": [],
            "loading_present": False,
        }

    def _trigger_probe(self) -> dict:
        return {
            "found": True,
            "trigger": {
                "id": "great-walk-night-dropdown-button",
                "text": str(self.nights),
                "visible": True,
                "enabled": self.editable,
                "aria_disabled": "true" if not self.editable else None,
                "aria_expanded": "true" if self.opened else "false",
                "class": "disabled greyed" if not self.editable else "dropdown-button",
            },
            "editable": self.editable,
            "non_editable_evidence": list(self.non_editable_evidence),
            "menu_open": self.opened,
        }

    def _zero_based_probe(self, nights: int) -> dict:
        option_id = zero_based_option_element_id(nights)
        if not self.opened:
            return {
                "requested_nights": nights,
                "computed_option_id": option_id,
                "menu_count": 0,
                "menus": [],
                "target_option_count": 0,
                "target_option": None,
                "observed_target_text": None,
                "menu_open": False,
                "trigger_value_before": str(self.nights),
                "button_aria_expanded": "false",
                "menu_options": [],
            }
        targets = [
            o
            for o in self.options
            if o.get("id") == option_id and o.get("visible") and not o.get("likely_mobile")
        ]
        target = targets[0] if len(targets) == 1 else (targets[0] if targets else None)
        return {
            "requested_nights": nights,
            "computed_option_id": option_id,
            "menu_count": 1,
            "menus": [{"id": "great-walk-night-dropdown-box", "visible": True}],
            "target_option_count": len(targets),
            "target_option": target,
            "observed_target_text": target.get("text") if target else None,
            "menu_open": True,
            "trigger_value_before": str(self.nights),
            "button_aria_expanded": "true",
            "menu_options": list(self.options),
        }

    def evaluate(self, expression: str, arg=None) -> object:
        if isinstance(arg, dict) and "rootSelector" in arg:
            return {"found": True, "clickable": self.editable, "desktop_root_count": 1}
        if isinstance(arg, dict) and "nights" in arg:
            return self._zero_based_probe(int(arg["nights"]))
        if "desktop_root_count" in expression or "readBtn" in expression:
            return self._state()
        if "great-walk-night-dropdown-button" in expression:
            return self._trigger_probe()
        return {}

    def _option_locator_for_id(self, option_id: str) -> MagicMock:
        loc = MagicMock()
        matching = self.opened and any(
            o.get("id") == option_id and o.get("visible") and not o.get("likely_mobile")
            for o in self.options
        )
        loc.count.return_value = 1 if matching else 0
        loc.first = loc
        loc.is_enabled.return_value = True
        loc.filter.return_value = loc
        match = re.fullmatch(r"great-walk-night-(\d+)", option_id)
        if match and "-mobile" not in option_id:

            def _click(**_kwargs: object) -> None:
                self.clicks += 1
                self.nights = int(match.group(1)) + 1
                self.opened = False

            loc.click.side_effect = _click
        return loc

    def _menu_locator(self) -> MagicMock:
        menu = self._locators.get("menu")
        if menu is None:
            menu = MagicMock()
            menu.first = menu
            menu.filter.return_value = menu
            menu.locator.side_effect = lambda inner: self.locator(inner)
            self._locators["menu"] = menu
        menu.count.return_value = 1 if self.opened else 0
        return menu

    def locator(self, selector: str) -> MagicMock:
        if selector == "[id*='-mobile']":
            mobile = MagicMock()
            mobile.count.return_value = 0
            return mobile
        if selector == NIGHTS_LIST_SELECTOR:
            return self._menu_locator()
        if selector.startswith("#great-walk-night-"):
            return self._option_locator_for_id(selector[1:])
        if selector not in self._locators:
            loc = MagicMock()
            loc.count.return_value = 1
            loc.first = loc
            loc.is_enabled.return_value = True
            loc.filter.return_value = loc
            loc.locator.side_effect = lambda inner: self.locator(inner)
            self._locators[selector] = loc
        return self._locators[selector]

    def wait_for_timeout(self, timeout: int) -> None:
        return None


def _click_opens_menu(page: _NightsPage, *args: object, **kwargs: object) -> None:
    page.opened = True


def test_zero_based_nights_option_id_mapping():
    assert zero_based_option_element_id(2) == "great-walk-night-1"
    assert zero_based_option_element_id(3) == "great-walk-night-2"


def test_milford_disabled_already_matched_no_click():
    page = _NightsPage(nights=3, editable=False, non_editable_evidence=["aria-disabled=true"])
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    with patch("greatwalkbot.sources.gw_desktop_nights_dropdown.click_desktop_control") as click:
        result = select_desktop_nights(page, 3, binding)
    click.assert_not_called()
    assert result.action == "already_matched_track_controlled"


def test_disabled_mismatch_raises_track_constraint_error():
    page = _NightsPage(nights=3, editable=False, non_editable_evidence=["class-contains-grey"])
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    with pytest.raises(GreatWalkNightsTrackConstraintError, match="track-controlled") as exc_info:
        select_desktop_nights(page, 2, binding)
    diag = exc_info.value.nights_dropdown_diagnostics
    assert diag is not None
    assert diag["current_nights"] == 3
    assert diag["requested_nights"] == 2
    assert diag["non_editable_evidence"]


def test_routeburn_selects_two_from_default_one():
    page = _NightsPage(nights=1, editable=True, options=[_option(1), _option(2), _option(3)])
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    with patch(
        "greatwalkbot.sources.gw_desktop_nights_dropdown.click_desktop_control",
        side_effect=_click_opens_menu,
    ):
        with patch(
            "greatwalkbot.sources.gw_desktop_nights_dropdown.wait_for_control_clickable"
        ):
            result = select_desktop_nights(page, 2, binding)
    assert result.action == "changed_and_verified"
    assert result.normalized_value == "2"
    assert page.nights == 2
    assert not page.opened
    assert result.nights_dropdown_diagnostics is not None
    assert result.nights_dropdown_diagnostics["resolution_method"] == "zero_based_option_id"


def test_kepler_selects_three_from_default_one():
    page = _NightsPage(nights=1, editable=True, options=[_option(1), _option(2), _option(3)])
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    with patch(
        "greatwalkbot.sources.gw_desktop_nights_dropdown.click_desktop_control",
        side_effect=_click_opens_menu,
    ):
        with patch(
            "greatwalkbot.sources.gw_desktop_nights_dropdown.wait_for_control_clickable"
        ):
            result = select_desktop_nights(page, 3, binding)
    assert result.normalized_value == "3"
    assert page.nights == 3


def test_mobile_option_excluded_from_deterministic_binding():
    probe = {
        "menu_count": 1,
        "target_option_count": 0,
        "computed_option_id": "great-walk-night-1",
        "menu_options": [_option(2, mobile=True, option_id="great-walk-night-mobile-1")],
    }
    status, reasons = _evaluate_zero_based_binding(probe, 2)
    assert status == "absent"
    assert any("not found" in reason for reason in reasons)


def test_text_mismatch_raises_typed_error():
    page = _NightsPage(
        nights=1,
        editable=True,
        options=[_option(2, text="99")],
    )
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    with patch(
        "greatwalkbot.sources.gw_desktop_nights_dropdown.click_desktop_control",
        side_effect=_click_opens_menu,
    ):
        with patch(
            "greatwalkbot.sources.gw_desktop_nights_dropdown.wait_for_control_clickable"
        ):
            with pytest.raises(GreatWalkNightsDropdownError, match="Deterministic") as exc_info:
                select_desktop_nights(page, 2, binding)
    diag = exc_info.value.nights_dropdown_diagnostics
    assert diag is not None
    assert "text mismatch" in diag["deterministic_binding"]["failure_reason"]


def test_inspect_nights_control_records_semantics():
    page = _NightsPage(nights=3, editable=False, non_editable_evidence=["aria-disabled=true"])
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    inspection = inspect_nights_control(page, binding, requested_nights=3)
    assert inspection["editable"] is False
    assert inspection["current_nights"] == 3
    assert inspection["requested_nights"] == 3
    assert inspection["trigger"]["id"] == "great-walk-night-dropdown-button"


def test_prepare_form_milford_uses_track_controlled_action():
    from datetime import date
    from greatwalkbot.sources.gw_desktop_people_dropdown import PeopleSelectionResult

    class _PrepPage(_NightsPage):
        def _state(self) -> dict:
            state = super()._state()
            state["track_control"] = {"visible_text": "Milford Track", "enabled": True}
            state["people_control"] = {"visible_text": "2", "enabled": True}
            state["start_date_control"] = {
                "visible_text": "07/12/2026",
                "data_date": "2026-12-07",
                "enabled": True,
            }
            return state

    prep_page = _PrepPage(nights=3, editable=False, non_editable_evidence=["class-contains-grey"])
    with patch("greatwalkbot.sources.gw_desktop_form.select_desktop_track"):
        with patch("greatwalkbot.sources.gw_desktop_form.refresh_desktop_root_binding") as refresh:
            binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
            refresh.return_value = (binding, {"root_replaced": False})
            with patch(
                "greatwalkbot.sources.gw_desktop_form.set_desktop_start_date",
                return_value={"action": "already_matched"},
            ):
                with patch(
                    "greatwalkbot.sources.gw_desktop_form.select_desktop_people",
                    return_value=PeopleSelectionResult(
                        action="already_matched",
                        requested_people=2,
                        normalized_value="2",
                    ),
                ):
                    state = prepare_desktop_search_form(
                        prep_page,
                        MILFORD,
                        start_date=date(2026, 12, 7),
                        nights=3,
                        people_size=2,
                    )
    assert state["control_actions"]["nights"] == "already_matched_track_controlled"
