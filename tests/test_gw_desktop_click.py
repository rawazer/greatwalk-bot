"""Tests for desktop click-readiness and interception diagnostics (Milestone 9.8)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from greatwalkbot.infra.errors import GreatWalkControlNotClickableError
from greatwalkbot.sources.gw_desktop_form import (
    DESKTOP_ROOT_SELECTOR,
    NIGHTS_BUTTON_SELECTOR,
    DesktopRootBinding,
    _interceptor_is_benign_widget_overlay,
    _sanitize_click_diagnostics,
    click_desktop_control,
    probe_click_readiness,
    refresh_desktop_root_binding,
    wait_for_control_clickable,
)

_BINDING = DesktopRootBinding(
    selector=DESKTOP_ROOT_SELECTOR,
    count=1,
    root_id=None,
    root_class="themeTopsearch",
)


def _desktop_state(*, root_class: str = "themeTopsearch") -> dict:
    return {
        "desktop_root_count": 1,
        "desktop_root": {
            "selector": DESKTOP_ROOT_SELECTOR,
            "id": None,
            "class": root_class,
        },
        "track_control": {"visible_text": "Milford Track", "enabled": True},
        "nights_control": {"visible_text": "3 nights", "enabled": True},
        "people_control": {"visible_text": "2 people", "enabled": True},
        "start_date_control": {"visible_text": "07/12/2026", "data_date": "2026-12-07"},
        "search_button": {"visible_text": "Search", "enabled": True},
        "validation_messages": [],
        "loading_present": False,
    }


def _click_diag(*, clickable: bool, root_class: str = "themeTopsearch", **extra) -> dict:
    base = {
        "found": True,
        "clickable": clickable,
        "control_selector": NIGHTS_BUTTON_SELECTOR,
        "center": {"x": 100, "y": 200},
        "target": {
            "tag": "BUTTON",
            "id": "great-walk-night-dropdown-button",
            "class": "dropdown-btn",
            "role": "button",
            "text": "3 nights",
            "pointer_events": "auto",
            "position": "relative",
            "z_index": "auto",
            "opacity": "1",
            "display": "block",
            "visibility": "visible",
            "rect": {"x": 80, "y": 180, "width": 40, "height": 40},
        },
        "root_class": root_class,
        "desktop_root_count": 1,
        "target_ancestors": [{"tag": "DIV", "id": None, "class": "themeTopsearch", "role": "search"}],
    }
    if not clickable:
        base.setdefault("interceptor", {"tag": "DIV", "role": "search", "class": "themeTopsearch"})
    base.update(extra)
    return base


class ClickProbePage:
    def __init__(
        self,
        *,
        probe_sequence: list[dict] | None = None,
        state: dict | None = None,
        default_clickable: bool = True,
    ) -> None:
        self.probe_sequence = list(probe_sequence or [])
        self.state = state or _desktop_state()
        self.default_clickable = default_clickable
        self.wait_calls = 0
        self._locators: dict[str, MagicMock] = {}

    def evaluate(self, expression: str, arg=None) -> object:
        if "elementFromPoint" in expression:
            if self.probe_sequence:
                return self.probe_sequence.pop(0)
            return _click_diag(clickable=self.default_clickable)
        if "desktop_root_count" in expression or "readBtn" in expression:
            return self.state
        return {}

    def locator(self, selector: str) -> MagicMock:
        if selector not in self._locators:
            loc = MagicMock()
            loc.count.return_value = 1
            loc.first = loc
            loc.is_enabled.return_value = True
            self._locators[selector] = loc
        return self._locators[selector]

    def wait_for_timeout(self, timeout: int) -> None:
        self.wait_calls += 1


def test_visible_but_covered_raises_typed_error_with_diagnostics():
    page = ClickProbePage(
        probe_sequence=[_click_diag(clickable=False, interceptor={"tag": "DIV", "role": "search"})],
        default_clickable=False,
    )
    with pytest.raises(GreatWalkControlNotClickableError) as exc_info:
        wait_for_control_clickable(page, _BINDING, NIGHTS_BUTTON_SELECTOR, "nights", timeout_ms=50)
    err = exc_info.value
    assert err.control == "nights"
    assert err.click_diagnostics is not None
    assert err.click_diagnostics.get("clickable") is False
    assert err.click_diagnostics.get("target", {}).get("id") == "great-walk-night-dropdown-button"
    assert err.click_diagnostics.get("interceptor", {}).get("role") == "search"


def test_diagnostics_are_bounded_and_sanitized():
    raw = _click_diag(
        clickable=False,
        interceptor={"tag": "DIV"},
    )
    raw["extra_html"] = "<div>should not appear</div>"
    sanitized = _sanitize_click_diagnostics(raw)
    assert "extra_html" not in sanitized
    assert sanitized["target"]["text"] == "3 nights"
    assert len(sanitized["target_ancestors"]) == 1


def test_benign_selected_park_overlay_is_recognized():
    diag = _click_diag(
        clickable=False,
        root_class="themeTopsearch selectedPark",
        interceptor={
            "tag": "DIV",
            "role": "search",
            "class": "themeTopsearch selectedPark",
        },
        hit={"tag": "DIV", "role": "search", "class": "themeTopsearch selectedPark"},
    )
    assert _interceptor_is_benign_widget_overlay(diag) is True


def test_temporary_overlay_clears_and_retry_succeeds_without_force():
    page = ClickProbePage(
        probe_sequence=[
            _click_diag(clickable=True),
            _click_diag(
                clickable=False,
                root_class="themeTopsearch selectedPark",
                interceptor={"tag": "DIV", "role": "search", "class": "themeTopsearch selectedPark"},
            ),
            _click_diag(clickable=True),
        ]
    )
    nights_loc = page.locator(DESKTOP_ROOT_SELECTOR).locator(NIGHTS_BUTTON_SELECTOR).first
    nights_loc.click.side_effect = [
        Exception("Locator.click: div intercepts pointer events"),
        None,
    ]
    click_desktop_control(page, _BINDING, NIGHTS_BUTTON_SELECTOR, "nights", timeout_ms=500)
    assert nights_loc.click.call_count == 2
    for call in nights_loc.click.call_args_list:
        assert call.kwargs.get("force") is not True


def test_persistent_overlay_fails_without_force():
    page = ClickProbePage(
        probe_sequence=[
            _click_diag(clickable=True),
            _click_diag(
                clickable=False,
                interceptor={"tag": "DIV", "id": "blocking-panel", "role": "dialog"},
            ),
        ]
    )
    nights_loc = page.locator(DESKTOP_ROOT_SELECTOR).locator(NIGHTS_BUTTON_SELECTOR).first
    nights_loc.click.side_effect = Exception("Locator.click: div intercepts pointer events")
    with pytest.raises(GreatWalkControlNotClickableError) as exc_info:
        click_desktop_control(page, _BINDING, NIGHTS_BUTTON_SELECTOR, "nights", timeout_ms=200)
    assert nights_loc.click.call_count == 1
    assert exc_info.value.click_diagnostics is not None
    assert exc_info.value.click_diagnostics.get("interceptor", {}).get("id") == "blocking-panel"


def test_root_replacement_produces_fresh_binding():
    prior = DesktopRootBinding(
        selector=DESKTOP_ROOT_SELECTOR,
        count=1,
        root_id=None,
        root_class="themeTopsearch",
    )
    page = ClickProbePage(state=_desktop_state(root_class="themeTopsearch selectedPark"))
    binding, change = refresh_desktop_root_binding(page, prior)
    assert change["root_replaced"] is True
    assert change["prior_root"]["class"] == "themeTopsearch"
    assert change["current_root"]["class"] == "themeTopsearch selectedPark"
    assert binding.root_class == "themeTopsearch selectedPark"


def test_probe_click_readiness_delegates_to_evaluate():
    page = ClickProbePage(probe_sequence=[_click_diag(clickable=True)])
    diag = probe_click_readiness(page, _BINDING, NIGHTS_BUTTON_SELECTOR)
    assert diag["clickable"] is True
    assert diag["control_selector"] == NIGHTS_BUTTON_SELECTOR
