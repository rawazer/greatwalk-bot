"""Bounded DOC SPA navigation and Great Walk track selection."""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

from greatwalkbot.constants import GREATWALK_HASH, SITE_URL
from greatwalkbot.infra.errors import (
    NavigationError,
    TrackSelectionNotCommittedError,
    TrackSelectorError,
    UIReadinessError,
)
from greatwalkbot.models import Track
from greatwalkbot.sources.network_recorder import NetworkRecorder
from greatwalkbot.sources.spa_timing import GOTO_WAIT_UNTIL

logger = logging.getLogger(__name__)

_GREAT_WALK_UI_JS = """() => {
    const items = document.querySelectorAll('[id^="great-walk-"]');
    return items.length > 0;
}"""

_DROPDOWN_BUTTON_IDS = (
    "great-walk-dropdown-button",
    "great-walk-mobile-dropdown-button",
)

_SELECTION_COMMITTED_JS = """({ optionIds, trackName }) => {
    for (const id of optionIds) {
        const el = document.getElementById(id);
        if (!el) continue;
        const selected =
            el.getAttribute('aria-selected') === 'true' ||
            el.classList.contains('selected') ||
            el.classList.contains('active') ||
            el.getAttribute('aria-checked') === 'true';
        if (selected) return true;
    }
    const dropdownSelectors = [
        '#great-walk-dropdown-button',
        '#great-walk-mobile-dropdown-button',
        '[id*="great-walk-dropdown"]',
    ];
    for (const sel of dropdownSelectors) {
        const node = document.querySelector(sel);
        if (node && node.textContent && node.textContent.includes(trackName)) {
            return true;
        }
    }
    return false;
}"""


class SpaPage(Protocol):
    def goto(self, url: str, *, wait_until: str, timeout: int) -> Any: ...

    def evaluate(self, expression: str, arg: Any = None) -> Any: ...

    def wait_for_function(self, expression: str, *, timeout: int) -> Any: ...

    def wait_for_timeout(self, timeout: int) -> None: ...


def navigate_to_site(
    page: SpaPage,
    *,
    site_url: str = SITE_URL,
    timeout_ms: int,
) -> None:
    try:
        page.goto(site_url, wait_until=GOTO_WAIT_UNTIL, timeout=timeout_ms)
    except Exception as exc:
        raise NavigationError(
            f"Navigation to {site_url!r} timed out or failed "
            f"(wait_until={GOTO_WAIT_UNTIL!r}, timeout={timeout_ms}ms): {exc}"
        ) from exc


def wait_for_great_walk_ui(page: SpaPage, *, timeout_ms: int) -> None:
    try:
        page.wait_for_function(_GREAT_WALK_UI_JS, timeout=timeout_ms)
    except Exception as exc:
        raise UIReadinessError(
            f"Great Walk UI not ready within {timeout_ms}ms "
            f"(expected [id^='great-walk-'] elements): {exc}"
        ) from exc


def open_great_walk_view(
    page: SpaPage,
    *,
    site_url: str = SITE_URL,
    greatwalk_hash: str = GREATWALK_HASH,
    navigation_timeout_ms: int,
    app_ready_timeout_ms: int,
) -> None:
    navigate_to_site(page, site_url=site_url, timeout_ms=navigation_timeout_ms)
    page.evaluate(f"window.location.hash = '{greatwalk_hash}'")
    wait_for_great_walk_ui(page, timeout_ms=app_ready_timeout_ms)


def open_track_dropdown(page: SpaPage) -> bool:
    return bool(
        page.evaluate(
            f"""() => {{
                const ids = {list(_DROPDOWN_BUTTON_IDS)!r};
                for (const id of ids) {{
                    const btn = document.getElementById(id);
                    if (btn) {{ btn.click(); return true; }}
                }}
                return false;
            }}"""
        )
    )


def click_track_option(page: SpaPage, track: Track) -> str | None:
    option_ids = list(track.dropdown_option_ids)
    return page.evaluate(
        """({ optionIds }) => {
            for (const id of optionIds) {
                const el = document.getElementById(id);
                if (!el) continue;
                el.click();
                return id;
            }
            return null;
        }""",
        {"optionIds": option_ids},
    )


def is_track_selection_committed(page: SpaPage, track: Track) -> bool:
    return bool(
        page.evaluate(
            _SELECTION_COMMITTED_JS,
            {
                "optionIds": list(track.dropdown_option_ids),
                "trackName": track.name,
            },
        )
    )


def wait_for_track_selection_committed(
    page: SpaPage,
    track: Track,
    recorder: NetworkRecorder,
    *,
    timeout_ms: int,
) -> bool:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        if is_track_selection_committed(page, track):
            return True
        if recorder.saw_selection_metadata(track.place_id):
            return True
        page.wait_for_timeout(100)
    return False


def commit_track_selection(
    page: SpaPage,
    track: Track,
    recorder: NetworkRecorder,
    *,
    site_url: str = SITE_URL,
    greatwalk_hash: str = GREATWALK_HASH,
    navigation_timeout_ms: int,
    app_ready_timeout_ms: int,
    selection_commit_timeout_ms: int,
) -> None:
    """Open dropdown, select track, and wait until SPA commits the selection."""
    for recovery in range(2):
        if recovery == 1:
            logger.warning(
                "Track selection not committed for %s; attempting one view recovery",
                track.slug,
            )
            open_great_walk_view(
                page,
                site_url=site_url,
                greatwalk_hash=greatwalk_hash,
                navigation_timeout_ms=navigation_timeout_ms,
                app_ready_timeout_ms=app_ready_timeout_ms,
            )

        open_track_dropdown(page)
        clicked_id = click_track_option(page, track)
        if clicked_id is None:
            if recovery == 0:
                continue
            raise TrackSelectorError(
                f"Could not click any track option for {track.name!r} "
                f"(tried {track.dropdown_option_ids})",
                track_slug=track.slug,
                element_id=track.dropdown_element_id,
            )

        if wait_for_track_selection_committed(
            page,
            track,
            recorder,
            timeout_ms=selection_commit_timeout_ms,
        ):
            return

    raise TrackSelectionNotCommittedError(
        f"Track {track.name!r} option was clicked but selection did not commit "
        f"within {selection_commit_timeout_ms}ms",
        place_id=track.place_id,
    )


def click_search_button(page: SpaPage) -> None:
    clicked = page.evaluate(
        """() => {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.trim() === 'Search' && b.offsetParent);
            if (btn) { btn.click(); return true; }
            return false;
        }"""
    )
    if not clicked:
        raise UIReadinessError("Could not find the Great Walk Search button on the page")


# Backwards-compatible alias used in older tests.
def select_track_with_recovery(
    page: SpaPage,
    track: Track,
    *,
    site_url: str = SITE_URL,
    greatwalk_hash: str = GREATWALK_HASH,
    navigation_timeout_ms: int,
    app_ready_timeout_ms: int,
    recorder: NetworkRecorder | None = None,
    selection_commit_timeout_ms: int = 8_000,
) -> None:
    if recorder is None:
        recorder = NetworkRecorder()
    commit_track_selection(
        page,
        track,
        recorder,
        site_url=site_url,
        greatwalk_hash=greatwalk_hash,
        navigation_timeout_ms=navigation_timeout_ms,
        app_ready_timeout_ms=app_ready_timeout_ms,
        selection_commit_timeout_ms=selection_commit_timeout_ms,
    )
