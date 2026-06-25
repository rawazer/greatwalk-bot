"""Bounded DOC SPA navigation and Great Walk track selection."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from greatwalkbot.constants import GREATWALK_HASH, SITE_URL
from greatwalkbot.infra.errors import NavigationError, TrackSelectorError, UIReadinessError
from greatwalkbot.models import Track
from greatwalkbot.sources.spa_timing import GOTO_WAIT_UNTIL

logger = logging.getLogger(__name__)

_GREAT_WALK_UI_JS = """() => {
    const items = document.querySelectorAll('[id^="great-walk-"]');
    return items.length > 0;
}"""


class SpaPage(Protocol):
    def goto(self, url: str, *, wait_until: str, timeout: int) -> Any: ...

    def evaluate(self, expression: str) -> Any: ...

    def wait_for_function(self, expression: str, *, timeout: int) -> Any: ...


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


def track_element_present(page: SpaPage, element_id: str) -> bool:
    return bool(
        page.evaluate(
            f"() => !!document.getElementById({element_id!r})"
        )
    )


def click_track_element(page: SpaPage, element_id: str) -> bool:
    return bool(
        page.evaluate(
            f"""() => {{
                const el = document.getElementById({element_id!r});
                if (!el) return false;
                el.click();
                return true;
            }}"""
        )
    )


def select_track_with_recovery(
    page: SpaPage,
    track: Track,
    *,
    site_url: str = SITE_URL,
    greatwalk_hash: str = GREATWALK_HASH,
    navigation_timeout_ms: int,
    app_ready_timeout_ms: int,
) -> None:
    """Select a track, performing exactly one bounded view recovery if needed."""
    element_id = track.dropdown_element_id

    if click_track_element(page, element_id):
        return

    logger.warning(
        "Track element %s not found for %s; attempting one Great Walk view recovery",
        element_id,
        track.slug,
    )
    open_great_walk_view(
        page,
        site_url=site_url,
        greatwalk_hash=greatwalk_hash,
        navigation_timeout_ms=navigation_timeout_ms,
        app_ready_timeout_ms=app_ready_timeout_ms,
    )

    if click_track_element(page, element_id):
        return

    raise TrackSelectorError(
        f"Could not select track dropdown item #{element_id} for {track.name!r} "
        f"after one recovery attempt",
        track_slug=track.slug,
        element_id=element_id,
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
