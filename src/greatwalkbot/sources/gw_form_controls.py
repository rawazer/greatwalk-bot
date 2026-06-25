"""DOC Great Walk search form — delegates to desktop widget binding."""

from __future__ import annotations

from datetime import date
from typing import Any

from greatwalkbot.sources.gw_desktop_form import (
    DESKTOP_ROOT_SELECTOR,
    DATE_BUTTON_SELECTOR,
    NIGHTS_BUTTON_SELECTOR,
    PEOPLE_BUTTON_SELECTOR,
    TRACK_BUTTON_SELECTOR,
    TRACK_LIST_SELECTOR,
    capture_desktop_selection_state,
    read_desktop_form_state,
    resolve_desktop_great_walk_root,
    select_desktop_nights,
    select_desktop_people,
    set_desktop_start_date,
)
from greatwalkbot.sources.gw_active_form import normalize_date_string

# Stable constants for docs/tests (desktop widget).
TRACK_DROPDOWN_BUTTON_ID = "great-walk-dropdown-button"
TRACK_DROPDOWN_LIST_ID = "great-walk-dropdown-box"
START_DATE_BUTTON_ID = "great-walk-start-date"
NIGHTS_DROPDOWN_BUTTON_ID = "great-walk-night-dropdown-button"
PEOPLE_DROPDOWN_BUTTON_ID = "great-walk-people-dropdown-button"
DESKTOP_SEARCH_SCOPED_SELECTOR = f'{DESKTOP_ROOT_SELECTOR} >> button:has-text("Search")'


def capture_form_control_state(
    page: Any,
    *,
    track_name: str | None = None,
    start_date: date | None = None,
    nights: int | None = None,
    people_size: int | None = None,
    backend_metadata_confirmed: bool | None = None,
) -> dict[str, Any]:
    binding = resolve_desktop_great_walk_root(page)
    state = read_desktop_form_state(
        page,
        binding,
        track_name=track_name,
        start_date=start_date,
        nights=nights,
        people_size=people_size,
    )
    if backend_metadata_confirmed is not None:
        state["backend_metadata_confirmed"] = backend_metadata_confirmed
    return state


def set_start_date(page: Any, target: date) -> None:
    resolve_desktop_great_walk_root(page)
    set_desktop_start_date(page, target)


def set_nights(page: Any, nights: int) -> None:
    resolve_desktop_great_walk_root(page)
    select_desktop_nights(page, nights)


def set_people(page: Any, people_size: int) -> None:
    resolve_desktop_great_walk_root(page)
    select_desktop_people(page, people_size)


def capture_selection_state(page: Any, track: Any, *, backend_metadata_confirmed: bool) -> dict[str, Any]:
    return capture_desktop_selection_state(
        page,
        track,
        backend_metadata_confirmed=backend_metadata_confirmed,
    )
