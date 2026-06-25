"""Tests for desktop People dropdown binding."""

from __future__ import annotations

from datetime import date
from pathlib import Path
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


def _button(people: int = 1, *, expanded: bool = True) -> dict:
    return {
        "tag": "BUTTON",
        "id": "great-walk-people-dropdown-button",
        "text": str(people),
        "visible_text": str(people),
        "aria_label": f"Number of People * {people}",
        "aria_expanded": "true" if expanded else "false",
        "visible": True,
        "enabled": True,
        "likely_mobile": False,
        "rect": {"x": 100, "y": 50, "width": 80, "height": 32},
    }


def _option(
    people: int,
    *,
    mobile: bool = False,
    option_id: str | None = None,
    container_id: str | None = "great-walk-people-dropdown-box",
    association_hint: str = "id-pattern",
    visible: bool = True,
    text: str | None = None,
) -> dict:
    return {
        "tag": "DIV",
        "id": option_id or f"great-walk-people-{people}" + ("-mobile" if mobile else ""),
        "text": text if text is not None else str(people),
        "aria_label": None,
        "visible": visible,
        "enabled": True,
        "likely_mobile": mobile,
        "container_id": container_id,
        "association_hint": association_hint,
        "data_attributes": {"data-value": str(people)},
        "rect": {"x": 110, "y": 90 + people * 24, "width": 60, "height": 20},
    }


def _container(
    *,
    container_id: str = "great-walk-people-dropdown-box",
    hint: str = "id-pattern",
) -> dict:
    return {
        "id": container_id,
        "tag": "UL",
        "association_hint": hint,
        "visible": True,
        "enabled": True,
        "likely_mobile": False,
        "rect": {"x": 100, "y": 85, "width": 80, "height": 120},
    }


def _discovery(
    *,
    people: int = 1,
    options: list[dict] | None = None,
    containers: list[dict] | None = None,
    expanded: bool = True,
) -> dict:
    return {
        "found": True,
        "button": _button(people, expanded=expanded),
        "containers": containers if containers is not None else [_container()],
        "options": options if options is not None else [_option(1), _option(2)],
        "dropdown_open": expanded,
    }


class _PeoplePage:
    def __init__(
        self,
        *,
        people: int = 1,
        options: list[dict] | None = None,
        containers: list[dict] | None = None,
        portal_options: list[dict] | None = None,
    ) -> None:
        self.people = people
        self.options = options or [_option(1), _option(2)]
        self.containers = containers
        self.portal_options = portal_options
        self.clicks = 0
        self.opened = False
        self._locators: dict[str, MagicMock] = {}
        self.screenshots: list[str] = []

    def _state(self) -> dict:
        return {
            "desktop_root_count": 1,
            "desktop_root": {"selector": DESKTOP_ROOT_SELECTOR, "id": None, "class": "x"},
            "people_control": {
                "visible_text": str(self.people),
                "normalized_value": str(self.people),
                "aria_label": f"Number of People * {self.people}",
                "aria_expanded": "true" if self.opened else "false",
                "enabled": True,
            },
            "track_control": {"visible_text": "Milford Track", "enabled": True},
            "nights_control": {"visible_text": "3", "enabled": True},
            "start_date_control": {"visible_text": "26/06/2026", "data_date": "2026-06-26"},
            "search_button": {"visible_text": "Search", "enabled": True},
            "validation_messages": [],
            "loading_present": False,
        }

    def _discovery_payload(self) -> dict:
        if not self.opened:
            return _discovery(
                people=self.people,
                options=[],
                containers=[],
                expanded=False,
            )
        options = list(self.options)
        if self.portal_options:
            options.extend(self.portal_options)
        containers = self.containers
        if containers is None:
            containers = [_container()] if options else []
        return _discovery(
            people=self.people,
            options=options,
            containers=containers,
            expanded=True,
        )

    def evaluate(self, expression: str, arg=None) -> object:
        if isinstance(arg, dict) and "rootSelector" in arg:
            return {"found": True, "clickable": True, "desktop_root_count": 1}
        if isinstance(arg, dict) and "buttonSelector" in arg:
            return self._discovery_payload()
        if "desktop_root_count" in expression or "readBtn" in expression:
            return self._state()
        return {}

    def _make_option_click_locator(self) -> MagicMock:
        loc = MagicMock()
        loc.count.return_value = 1
        loc.first = loc
        loc.is_enabled.return_value = True
        loc.filter.return_value = loc

        def _click(**_kwargs: object) -> None:
            self.clicks += 1
            self.people = 2

        loc.click.side_effect = _click
        return loc

    def get_by_text(self, text: str, exact: bool = False) -> MagicMock:
        if text == "2" and exact:
            return self._make_option_click_locator()
        loc = MagicMock()
        loc.count.return_value = 0
        loc.filter.return_value = loc
        return loc

    def locator(self, selector: str) -> MagicMock:
        if "great-walk-people-2" in selector and "-mobile" not in selector:
            return self._make_option_click_locator()
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
                    if "great-walk-people-2" in inner and "-mobile" not in inner:
                        self.people = 2

                inner_loc.click.side_effect = _click
                return inner_loc

            loc.locator.side_effect = nested
            self._locators[selector] = loc
        return self._locators[selector]

    def wait_for_timeout(self, timeout: int) -> None:
        return None

    def screenshot(self, **kwargs: object) -> bytes:
        path = kwargs.get("path")
        if path:
            self.screenshots.append(str(path).replace("\\", "/"))
        return b"png"


def _click_toggle_dropdown(page: _PeoplePage, *args: object, **kwargs: object) -> None:
    page.opened = not page.opened


def _click_opens_dropdown(page: _PeoplePage, *args: object, **kwargs: object) -> None:
    page.opened = True


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
    with patch(
        "greatwalkbot.sources.gw_desktop_people_dropdown.click_desktop_control",
        side_effect=_click_opens_dropdown,
    ):
        with patch(
            "greatwalkbot.sources.gw_desktop_people_dropdown.wait_for_control_clickable"
        ):
            result = select_desktop_people(page, 2, binding)
    assert result.action == "changed_and_verified"
    assert result.normalized_value == "2"
    assert page.people == 2


def test_hidden_mobile_option_ignored():
    discovery = _discovery(
        options=[
            _option(2, mobile=True, visible=False),
            _option(1),
        ]
    )
    container, method, _ = resolve_people_option_container(discovery)
    selected, _, reasons = resolve_people_option(
        discovery,
        2,
        container=container,
        association_method=method,
    )
    assert selected is None
    assert any("no semantic" in r for r in reasons)


def test_hidden_mobile_option_with_matching_text_rejected():
    discovery = _discovery(
        options=[
            {
                **_option(2, mobile=True, option_id="great-walk-people-mobile-2"),
                "visible": False,
            },
            _option(1),
        ]
    )
    container, method, _ = resolve_people_option_container(discovery)
    selected, _, reasons = resolve_people_option(
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
    selected, _, reasons = resolve_people_option(
        discovery,
        2,
        container=container,
        association_method=method,
    )
    assert selected is None
    assert any("ambiguous" in r for r in reasons)


def test_portal_options_outside_desktop_root_resolve():
    portal_container = _container(
        container_id="great-walk-people-portal-list",
        hint="geometry",
    )
    portal_option = _option(
        2,
        option_id="great-walk-people-2",
        container_id="great-walk-people-portal-list",
        association_hint="geometry",
    )
    discovery = _discovery(
        containers=[portal_container],
        options=[_option(1, container_id="great-walk-people-portal-list"), portal_option],
    )
    container, method, _ = resolve_people_option_container(discovery)
    selected, resolved_method, _ = resolve_people_option(
        discovery,
        2,
        container=container,
        association_method=method,
    )
    assert selected is not None
    assert selected["id"] == "great-walk-people-2"
    assert resolved_method in ("geometry", "id-pattern", "option-id-pattern")


def test_sibling_container_association():
    sibling = _container(
        container_id="great-walk-people-sibling-box",
        hint="id-pattern",
    )
    discovery = _discovery(
        containers=[sibling],
        options=[
            _option(1, container_id="great-walk-people-sibling-box"),
            _option(2, container_id="great-walk-people-sibling-box"),
        ],
    )
    container, method, _ = resolve_people_option_container(discovery)
    assert container is not None
    assert container["id"] == "great-walk-people-sibling-box"
    selected, _, _ = resolve_people_option(
        discovery,
        2,
        container=container,
        association_method=method,
    )
    assert selected is not None
    assert selected["text"] == "2"


def test_geometry_fallback_container():
    geometry_container = {
        **_container(container_id="popup-geometry-box", hint="geometry"),
        "horizontal_overlap": True,
        "distance_below_button": 4,
    }
    discovery = _discovery(
        containers=[geometry_container],
        options=[
            _option(2, container_id="popup-geometry-box", association_hint="geometry"),
        ],
    )
    container, method, _ = resolve_people_option_container(discovery)
    assert container is not None
    assert method == "geometry"
    selected, _, _ = resolve_people_option(
        discovery,
        2,
        container=container,
        association_method=method,
    )
    assert selected is not None


def test_select_portal_option_updates_trigger():
    portal_option = _option(
        2,
        option_id="great-walk-people-2",
        container_id="great-walk-people-portal-list",
        association_hint="option-id-pattern",
    )
    page = _PeoplePage(
        people=1,
        containers=[_container(container_id="great-walk-people-portal-list", hint="geometry")],
        portal_options=[portal_option, _option(1, container_id="great-walk-people-portal-list")],
    )
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    with patch(
        "greatwalkbot.sources.gw_desktop_people_dropdown.click_desktop_control",
        side_effect=_click_opens_dropdown,
    ):
        with patch(
            "greatwalkbot.sources.gw_desktop_people_dropdown.wait_for_control_clickable"
        ):
            result = select_desktop_people(page, 2, binding)
    assert result.normalized_value == "2"
    assert page.people == 2


def test_verification_waits_until_button_updates():
    page = _PeoplePage(people=1)
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    with patch(
        "greatwalkbot.sources.gw_desktop_people_dropdown.click_desktop_control",
        side_effect=_click_opens_dropdown,
    ):
        with patch(
            "greatwalkbot.sources.gw_desktop_people_dropdown.wait_for_control_clickable"
        ):
            result = select_desktop_people(page, 2, binding)
    assert result.normalized_value == "2"


def test_remains_one_raises_with_diagnostics():
    page = _PeoplePage(people=1)
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    noop_loc = _stub_locator(lambda **_kwargs: None)

    with patch(
        "greatwalkbot.sources.gw_desktop_people_dropdown.click_desktop_control",
        side_effect=_click_opens_dropdown,
    ):
        with patch(
            "greatwalkbot.sources.gw_desktop_people_dropdown.wait_for_control_clickable"
        ):
            with patch(
                "greatwalkbot.sources.gw_desktop_people_dropdown._option_locator",
                return_value=noop_loc,
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
    with patch(
        "greatwalkbot.sources.gw_desktop_people_dropdown.click_desktop_control",
        side_effect=_click_toggle_dropdown,
    ):
        report = inspect_people_dropdown(page, binding)
    assert "people_dropdown" in report
    section = report["people_dropdown"]
    assert section["requested_people"] == 1
    assert len(section["option_candidates"]) >= 1
    assert "before_open" in section
    assert "opened" in section
    assert "after_close" in section
    assert section["click_readiness"] is not None


def test_inspection_captures_options_only_after_opening():
    page = _PeoplePage(people=1)
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    with patch(
        "greatwalkbot.sources.gw_desktop_people_dropdown.click_desktop_control",
        side_effect=_click_toggle_dropdown,
    ):
        report = inspect_people_dropdown(page, binding)
    section = report["people_dropdown"]
    assert section["before_open"]["option_count"] == 0
    assert section["opened"]["option_count"] >= 1
    assert section["after_close"]["option_count"] == 0


def test_inspection_saves_open_screenshot(tmp_path: Path):
    page = _PeoplePage(people=1)
    binding = DesktopRootBinding(selector=DESKTOP_ROOT_SELECTOR, count=1)
    screenshot = tmp_path / "people_dropdown_open.png"
    with patch(
        "greatwalkbot.sources.gw_desktop_people_dropdown.click_desktop_control",
        side_effect=_click_toggle_dropdown,
    ):
        report = inspect_people_dropdown(page, binding, screenshot_path=screenshot)
    section = report["people_dropdown"]
    assert section["open_screenshot_path"] == str(screenshot)
    assert any("people_dropdown_open.png" in path for path in page.screenshots)


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
