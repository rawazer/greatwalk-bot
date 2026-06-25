"""DOC Great Walk search form — delegates to active-root scoped discovery."""

from __future__ import annotations

from datetime import date
from typing import Any

from greatwalkbot.sources.gw_active_form import (
    ACTIVE_ROOT_SELECTOR,
    capture_selection_state,
    click_active_search_button,
    inventory_active_form,
    normalize_date_string,
    read_active_form_state,
    resolve_active_great_walk_form,
    set_active_nights,
    set_active_start_date,
    wait_for_active_form_ready,
    wait_for_active_form_values,
)

# Re-export stable constants for docs/tests.
TRACK_DROPDOWN_BUTTON_IDS = (
    "great-walk-dropdown-button",
    "great-walk-mobile-dropdown-button",
)
START_DATE_BUTTON_ID = "great-walk-start-date"
NIGHTS_SELECT_ID = "great-walk-nights"
SEARCH_BUTTON_IDS = (
    "great-walk-search-button",
    "great-walk-search",
    "btn-great-walk-search",
)


def capture_form_control_state(
    page: Any,
    *,
    track_name: str | None = None,
    start_date: date | None = None,
    nights: int | None = None,
    backend_metadata_confirmed: bool | None = None,
) -> dict[str, Any]:
    resolution = resolve_active_great_walk_form(page)
    state = read_active_form_state(
        page,
        resolution,
        track_name=track_name,
        start_date=start_date,
        nights=nights,
    )
    if backend_metadata_confirmed is not None:
        state["backend_metadata_confirmed"] = backend_metadata_confirmed
    return state


def set_start_date(page: Any, target: date) -> None:
    resolve_active_great_walk_form(page)
    set_active_start_date(page, target)


def set_nights(page: Any, nights: int) -> None:
    resolve_active_great_walk_form(page)
    set_active_nights(page, nights)


def wait_for_form_values(
    page: Any,
    *,
    track_name: str,
    start_date: date,
    nights: int,
    timeout_ms: int = 5_000,
) -> dict[str, Any]:
    resolution = resolve_active_great_walk_form(page)
    return wait_for_active_form_values(
        page,
        resolution,
        track_name=track_name,
        start_date=start_date,
        nights=nights,
        timeout_ms=timeout_ms,
    )
