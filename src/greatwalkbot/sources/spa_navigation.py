"""Bounded DOC SPA navigation and Great Walk track selection."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

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

_DOC_BOOKING_HOST_SUFFIX = "bookings.doc.govt.nz"

_GREAT_WALK_UI_JS = """() => {
    const items = document.querySelectorAll('[id^="great-walk-"]');
    return items.length > 0;
}"""

_DROPDOWN_BUTTON_IDS = ("great-walk-dropdown-button",)

_NAVIGATION_STATE_JS = """() => {
    const roots = Array.from(document.querySelectorAll('div[role="search"]'))
        .filter(el => (el.className || '').toString().includes('themeTopsearch')
            && el.getBoundingClientRect().width > 0
            && el.getBoundingClientRect().height > 0);
    const dropdowns = Array.from(document.querySelectorAll('#great-walk-dropdown-button'))
        .filter(el => el.getBoundingClientRect().width > 0 && !el.id.includes('-mobile'));
    return {
        ready_state: document.readyState,
        visible_desktop_search_root_count: roots.length,
        visible_great_walk_dropdown_count: dropdowns.length,
    };
}"""

_SELECTION_COMMITTED_JS = """({ optionId, trackName }) => {
    const root = Array.from(document.querySelectorAll('div[role="search"]'))
        .find(el => (el.className || '').toString().includes('themeTopsearch')
            && el.getBoundingClientRect().width > 0);
    if (root) {
        const list = root.querySelector('#great-walk-dropdown-box');
        if (list) {
            const el = list.querySelector('#' + optionId);
            if (el) {
                const selected =
                    el.getAttribute('aria-selected') === 'true' ||
                    el.classList.contains('selected') ||
                    el.classList.contains('active');
                if (selected) return true;
            }
        }
        const btn = root.querySelector('#great-walk-dropdown-button');
        if (btn && btn.textContent && btn.textContent.includes(trackName)) return true;
    }
    return false;
}"""


class SpaPage(Protocol):
    @property
    def url(self) -> str: ...

    def goto(self, url: str, *, wait_until: str, timeout: int) -> Any: ...

    def evaluate(self, expression: str, arg: Any = None) -> Any: ...

    def wait_for_function(self, expression: str, *, timeout: int) -> Any: ...

    def wait_for_timeout(self, timeout: int) -> None: ...

    def title(self) -> str: ...


@dataclass(frozen=True)
class StageNavigationTiming:
    browser_start_seconds: float
    shell_navigation_seconds: float
    route_navigation_seconds: float
    spa_readiness_seconds: float
    total_seconds: float
    navigation_recovered_after_timeout: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "browser_start_seconds": round(self.browser_start_seconds, 3),
            "shell_navigation_seconds": round(self.shell_navigation_seconds, 3),
            "route_navigation_seconds": round(self.route_navigation_seconds, 3),
            "spa_readiness_seconds": round(self.spa_readiness_seconds, 3),
            "total_seconds": round(self.total_seconds, 3),
        }
        if self.navigation_recovered_after_timeout:
            payload["navigation_recovered_after_timeout"] = True
        return payload


def is_doc_booking_host(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return _DOC_BOOKING_HOST_SUFFIX in url.lower()
    return host.endswith(_DOC_BOOKING_HOST_SUFFIX)


def collect_navigation_state(
    page: SpaPage,
    recorder: NetworkRecorder | None = None,
) -> dict[str, Any]:
    """Bounded snapshot of page transport and early SPA evidence."""
    state: dict[str, Any] = {}
    try:
        state["url"] = str(page.url)[:500]
    except Exception:
        state["url"] = None
    try:
        state["title"] = str(page.title())[:200]
    except Exception:
        state["title"] = None
    try:
        dom = page.evaluate(_NAVIGATION_STATE_JS)
        if isinstance(dom, dict):
            state["ready_state"] = dom.get("ready_state")
            state["visible_desktop_search_root_count"] = dom.get(
                "visible_desktop_search_root_count"
            )
            state["visible_great_walk_dropdown_count"] = dom.get(
                "visible_great_walk_dropdown_count"
            )
    except Exception as exc:
        state["dom_probe_error"] = str(exc)[:200]
    state["on_doc_booking_host"] = is_doc_booking_host(state.get("url") or "")
    if recorder is not None:
        timeline = recorder.timeline_dicts()
        state["network_timeline_summary"] = {
            "event_count": len(timeline),
            "recent": [
                {
                    "path": event.get("path"),
                    "status": event.get("status"),
                    "phase": event.get("phase"),
                }
                for event in timeline[-10:]
            ],
        }
    return state


def navigate_to_site(
    page: SpaPage,
    *,
    site_url: str = SITE_URL,
    timeout_ms: int,
) -> None:
    """Navigate DOC shell only. Raises on failure without SPA recovery."""
    try:
        page.goto(site_url, wait_until=GOTO_WAIT_UNTIL, timeout=timeout_ms)
    except Exception as exc:
        raise NavigationError(
            f"Navigation to {site_url!r} timed out or failed "
            f"(wait_until={GOTO_WAIT_UNTIL!r}, timeout={timeout_ms}ms): {exc}",
            stage="shell_navigation",
            timeout_ms=timeout_ms,
            wait_until=GOTO_WAIT_UNTIL,
            navigation_state=collect_navigation_state(page),
        ) from exc


def apply_great_walk_route(
    page: SpaPage,
    *,
    greatwalk_hash: str = GREATWALK_HASH,
) -> None:
    page.evaluate(f"window.location.hash = '{greatwalk_hash}'")


def wait_for_great_walk_ui(page: SpaPage, *, timeout_ms: int) -> None:
    try:
        page.wait_for_function(_GREAT_WALK_UI_JS, timeout=timeout_ms)
    except Exception as exc:
        raise UIReadinessError(
            f"Great Walk UI not ready within {timeout_ms}ms "
            f"(expected [id^='great-walk-'] elements): {exc}",
            stage="spa_readiness",
            timeout_ms=timeout_ms,
            navigation_state=collect_navigation_state(page),
        ) from exc


def bootstrap_great_walk_ui(
    page: SpaPage,
    *,
    site_url: str = SITE_URL,
    greatwalk_hash: str = GREATWALK_HASH,
    shell_timeout_ms: int,
    spa_ready_timeout_ms: int,
    recorder: NetworkRecorder | None = None,
    browser_start_seconds: float = 0.0,
) -> StageNavigationTiming:
    """Navigate DOC shell, apply Great Walk route, and wait for UI readiness."""
    bootstrap_started = time.monotonic()
    shell_started = time.monotonic()
    shell_timed_out = False
    navigation_state_at_timeout: dict[str, Any] | None = None

    try:
        page.goto(site_url, wait_until=GOTO_WAIT_UNTIL, timeout=shell_timeout_ms)
    except Exception as exc:
        shell_timed_out = True
        navigation_state_at_timeout = collect_navigation_state(page, recorder)
        if not navigation_state_at_timeout.get("on_doc_booking_host"):
            shell_elapsed = time.monotonic() - shell_started
            timing = StageNavigationTiming(
                browser_start_seconds=browser_start_seconds,
                shell_navigation_seconds=shell_elapsed,
                route_navigation_seconds=0.0,
                spa_readiness_seconds=0.0,
                total_seconds=time.monotonic() - bootstrap_started + browser_start_seconds,
            )
            raise NavigationError(
                f"Navigation to {site_url!r} timed out or failed "
                f"(wait_until={GOTO_WAIT_UNTIL!r}, timeout={shell_timeout_ms}ms): {exc}",
                stage="shell_navigation",
                timeout_ms=shell_timeout_ms,
                wait_until=GOTO_WAIT_UNTIL,
                navigation_state=navigation_state_at_timeout,
                timing={
                    **timing.to_dict(),
                    "total_before_failure_seconds": timing.total_seconds,
                },
            ) from exc

        if shell_timed_out:
            logger.warning(
                "Shell navigation timed out on DOC booking host; "
                "attempting Great Walk SPA readiness wait"
            )

    shell_elapsed = time.monotonic() - shell_started
    route_started = time.monotonic()
    apply_great_walk_route(page, greatwalk_hash=greatwalk_hash)
    route_elapsed = time.monotonic() - route_started

    spa_started = time.monotonic()
    try:
        wait_for_great_walk_ui(page, timeout_ms=spa_ready_timeout_ms)
    except UIReadinessError as exc:
        spa_elapsed = time.monotonic() - spa_started
        timing = StageNavigationTiming(
            browser_start_seconds=browser_start_seconds,
            shell_navigation_seconds=shell_elapsed,
            route_navigation_seconds=route_elapsed,
            spa_readiness_seconds=spa_elapsed,
            total_seconds=time.monotonic() - bootstrap_started + browser_start_seconds,
        )
        if shell_timed_out:
            raise NavigationError(
                "Shell navigation timed out but DOC host was reachable; "
                f"Great Walk UI did not become ready within {spa_ready_timeout_ms}ms",
                stage="spa_readiness_after_shell_timeout",
                timeout_ms=spa_ready_timeout_ms,
                wait_until=GOTO_WAIT_UNTIL,
                navigation_state=navigation_state_at_timeout
                or collect_navigation_state(page, recorder),
                timing={
                    **timing.to_dict(),
                    "total_before_failure_seconds": timing.total_seconds,
                },
                navigation_recovered_after_timeout=False,
            ) from exc
        raise UIReadinessError(
            str(exc),
            stage="spa_readiness",
            timeout_ms=spa_ready_timeout_ms,
            navigation_state=exc.navigation_state or collect_navigation_state(page, recorder),
            timing={
                **timing.to_dict(),
                "total_before_failure_seconds": timing.total_seconds,
            },
        ) from exc

    spa_elapsed = time.monotonic() - spa_started
    return StageNavigationTiming(
        browser_start_seconds=browser_start_seconds,
        shell_navigation_seconds=shell_elapsed,
        route_navigation_seconds=route_elapsed,
        spa_readiness_seconds=spa_elapsed,
        total_seconds=time.monotonic() - bootstrap_started + browser_start_seconds,
        navigation_recovered_after_timeout=shell_timed_out,
    )


def open_great_walk_view(
    page: SpaPage,
    *,
    site_url: str = SITE_URL,
    greatwalk_hash: str = GREATWALK_HASH,
    navigation_timeout_ms: int,
    app_ready_timeout_ms: int,
    recorder: NetworkRecorder | None = None,
) -> StageNavigationTiming:
    return bootstrap_great_walk_ui(
        page,
        site_url=site_url,
        greatwalk_hash=greatwalk_hash,
        shell_timeout_ms=navigation_timeout_ms,
        spa_ready_timeout_ms=app_ready_timeout_ms,
        recorder=recorder,
    )


def open_track_dropdown(page: SpaPage) -> bool:
    return bool(
        page.evaluate(
            """() => {
                const root = Array.from(document.querySelectorAll('div[role="search"]'))
                    .find(el => (el.className || '').toString().includes('themeTopsearch')
                        && el.getBoundingClientRect().width > 0);
                if (!root) return false;
                const btn = root.querySelector('#great-walk-dropdown-button');
                if (!btn) return false;
                btn.click();
                return true;
            }"""
        )
    )


def click_track_option(page: SpaPage, track: Track) -> str | None:
    option_id = f"great-walk-{track.list_index + 1}"
    return page.evaluate(
        """({ optionId }) => {
            const root = Array.from(document.querySelectorAll('div[role="search"]'))
                .find(el => (el.className || '').toString().includes('themeTopsearch')
                    && el.getBoundingClientRect().width > 0);
            if (!root) return null;
            const list = root.querySelector('#great-walk-dropdown-box');
            if (!list) return null;
            const el = list.querySelector('#' + optionId);
            if (!el || el.id.includes('-mobile')) return null;
            el.click();
            return optionId;
        }""",
        {"optionId": option_id},
    )


def is_track_selection_committed(page: SpaPage, track: Track) -> bool:
    option_id = f"great-walk-{track.list_index + 1}"
    return bool(
        page.evaluate(
            _SELECTION_COMMITTED_JS,
            {
                "optionId": option_id,
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


def ensure_great_walk_session_ready(
    page: SpaPage,
    *,
    site_url: str = SITE_URL,
    greatwalk_hash: str = GREATWALK_HASH,
    shell_timeout_ms: int,
    spa_ready_timeout_ms: int,
    recorder: NetworkRecorder | None = None,
    browser_start_seconds: float = 0.0,
    full_bootstrap_required: bool = True,
) -> StageNavigationTiming:
    """Navigate or refresh the Great Walk SPA without redundant full reloads."""
    if full_bootstrap_required or not is_doc_booking_host(page.url):
        return bootstrap_great_walk_ui(
            page,
            site_url=site_url,
            greatwalk_hash=greatwalk_hash,
            shell_timeout_ms=shell_timeout_ms,
            spa_ready_timeout_ms=spa_ready_timeout_ms,
            recorder=recorder,
            browser_start_seconds=browser_start_seconds,
        )

    bootstrap_started = time.monotonic()
    try:
        ui_ready = bool(page.evaluate(_GREAT_WALK_UI_JS))
    except Exception:
        ui_ready = False

    route_started = time.monotonic()
    if greatwalk_hash not in (page.url or ""):
        apply_great_walk_route(page, greatwalk_hash=greatwalk_hash)
    route_elapsed = time.monotonic() - route_started

    spa_started = time.monotonic()
    if not ui_ready:
        wait_for_great_walk_ui(page, timeout_ms=spa_ready_timeout_ms)
    spa_elapsed = time.monotonic() - spa_started

    return StageNavigationTiming(
        browser_start_seconds=browser_start_seconds,
        shell_navigation_seconds=0.0,
        route_navigation_seconds=route_elapsed,
        spa_readiness_seconds=spa_elapsed,
        total_seconds=time.monotonic() - bootstrap_started + browser_start_seconds,
    )


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
    prior_track_slug: str | None = None,
    attempt: int = 1,
    session_restarted: bool = False,
) -> dict[str, Any]:
    """Re-resolve desktop root, select track, and verify visible trigger."""
    from greatwalkbot.sources.track_transition import transition_track_selection

    del site_url, greatwalk_hash
    diagnostics = transition_track_selection(
        page,
        track,
        recorder,
        navigation_timeout_ms=navigation_timeout_ms,
        app_ready_timeout_ms=app_ready_timeout_ms,
        selection_commit_timeout_ms=selection_commit_timeout_ms,
        prior_track_slug=prior_track_slug,
        attempt=attempt,
        session_restarted=session_restarted,
    )
    return diagnostics.to_dict()


def click_search_button(page: SpaPage) -> None:
    from greatwalkbot.sources.gw_desktop_form import click_desktop_search_button

    click_desktop_search_button(page)


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
