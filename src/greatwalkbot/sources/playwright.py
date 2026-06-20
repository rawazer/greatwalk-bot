"""Playwright-backed availability source using a real browser session."""

from __future__ import annotations

import json
from datetime import date

from playwright.sync_api import Page, Route, sync_playwright

from greatwalkbot.constants import (
    DEFAULT_USER_AGENT,
    GREATWALK_HASH,
    GW_FACILITY_PATH,
    RDR_HOST,
    SITE_URL,
)
from greatwalkbot.models import AvailabilitySnapshot, Track
from greatwalkbot.parsing import build_gw_facility_request, parse_gw_facility_response


class PlaywrightAvailabilitySource:
    """Load the DOC SPA and capture the Great Walk facility grid API."""

    def __init__(self, headless: bool = True, timeout_ms: int = 120_000) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms

    def fetch_track_availability(
        self,
        track: Track,
        from_date: date,
        to_date: date,
    ) -> AvailabilitySnapshot:
        payload: dict | None = None
        request_body = build_gw_facility_request(track, from_date, to_date)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.headless)
            page = browser.new_page(
                viewport={"width": 1400, "height": 900},
                user_agent=DEFAULT_USER_AGENT,
            )

            def on_response(response) -> None:
                nonlocal payload
                if GW_FACILITY_PATH not in response.url or response.status != 200:
                    return
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type:
                    return
                try:
                    payload = response.json()
                except json.JSONDecodeError:
                    return

            def rewrite_facility_post(route: Route) -> None:
                if route.request.method != "POST":
                    route.continue_()
                    return
                headers = {
                    **route.request.headers,
                    "content-type": "application/json; charset=utf-8",
                }
                route.continue_(headers=headers, post_data=json.dumps(request_body))

            page.route(f"**/{GW_FACILITY_PATH}", rewrite_facility_post)
            page.on("response", on_response)

            page.goto(SITE_URL, wait_until="networkidle", timeout=self.timeout_ms)
            page.wait_for_timeout(3000)
            page.evaluate(f"window.location.hash = '{GREATWALK_HASH}'")
            page.wait_for_timeout(8000)

            self._select_track(page, track)
            page.wait_for_timeout(2000)
            self._click_search(page)
            page.wait_for_timeout(15000)

            browser.close()

        if payload is None:
            raise RuntimeError(
                "No availability data captured. AWS WAF may have blocked the session; "
                "retry with --headed."
            )

        return parse_gw_facility_response(payload, track, from_date, to_date)

    @staticmethod
    def _select_track(page: Page, track: Track) -> None:
        element_id = track.dropdown_element_id
        clicked = page.evaluate(
            f"() => {{ const el = document.getElementById('{element_id}'); if (el) el.click(); return !!el; }}"
        )
        if not clicked:
            raise RuntimeError(f"Could not select track dropdown item #{element_id}")

    @staticmethod
    def _click_search(page: Page) -> None:
        clicked = page.evaluate(
            """() => {
                const btn = Array.from(document.querySelectorAll('button'))
                    .find(b => b.textContent.trim() === 'Search' && b.offsetParent);
                if (btn) { btn.click(); return true; }
                return false;
            }"""
        )
        if not clicked:
            raise RuntimeError("Could not find the Great Walk Search button on the page")
