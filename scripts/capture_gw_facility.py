"""Capture greatwalkplacefacility POST request/response for Routeburn."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUTPUT = Path(__file__).resolve().parents[1] / "investigation_output"


def run_track(page, track_element_id: str, label: str) -> dict | None:
    captured = None

    def on_resp(response):
        nonlocal captured
        if "greatwalkplacefacility" not in response.url or response.status != 200:
            return
        captured = {
            "url": response.url,
            "method": response.request.method,
            "post_data": response.request.post_data,
            "data": response.json(),
        }

    page.on("response", on_resp)
    page.evaluate(f"document.getElementById('{track_element_id}')?.click()")
    page.wait_for_timeout(3000)
    page.evaluate(
        """() => {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.trim() === 'Search' && b.offsetParent);
            btn?.click();
        }"""
    )
    page.wait_for_timeout(15000)
    print(f"\n=== {label} ===")
    if captured:
        print("POST body:", captured["post_data"])
        data = captured["data"]
        print("Response keys:", list(data.keys()) if isinstance(data, dict) else type(data))
        dump = json.dumps(data, indent=2)
        print(dump[:6000])
        if len(dump) > 6000:
            print("... [truncated, total", len(dump), "chars]")
    else:
        print("No capture")
    return captured


def main() -> None:
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1400, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page.goto(
            "https://bookings.doc.govt.nz/Web/Default.aspx",
            wait_until="networkidle",
            timeout=120_000,
        )
        page.wait_for_timeout(3000)
        page.evaluate("window.location.hash = '#!greatwalk-result'")
        page.wait_for_timeout(8000)

        results["routeburn"] = run_track(page, "great-walk-8", "Routeburn (874)")
        browser.close()

    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / "gw_place_facility.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
