"""Test setting GW start date and fetching December availability."""

from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    captured = None

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

        def on_resp(response):
            nonlocal captured
            if "greatwalkplacefacility" in response.url and response.status == 200:
                captured = {
                    "post_data": response.request.post_data,
                    "data": response.json(),
                }

        page.on("response", on_resp)
        page.goto(
            "https://bookings.doc.govt.nz/Web/Default.aspx",
            wait_until="networkidle",
            timeout=120_000,
        )
        page.wait_for_timeout(3000)
        page.evaluate("window.location.hash = '#!greatwalk-result'")
        page.wait_for_timeout(8000)

        # Milford
        page.evaluate("document.getElementById('great-walk-5')?.click()")
        page.wait_for_timeout(2000)

        # Inspect date-related hidden fields / state
        state = page.evaluate(
            """() => ({
                hidden: Array.from(document.querySelectorAll('input[type=hidden]'))
                    .filter(e => /date|great|walk|night/i.test(e.id + e.name))
                    .map(e => ({id: e.id, name: e.name, value: e.value})),
                startBtn: document.getElementById('great-walk-start-date')?.textContent?.trim(),
            })"""
        )
        print("State before:", json.dumps(state, indent=2))

        # Try dispatching custom event or setting global booking params
        page.evaluate(
            """() => {
                // open date picker and see structure
                const btn = document.getElementById('great-walk-start-date');
                if (btn) btn.setAttribute('data-date', '2026-12-07');
            }"""
        )

        page.evaluate(
            """() => {
                const btn = Array.from(document.querySelectorAll('button'))
                    .find(b => b.textContent.trim() === 'Search' && b.offsetParent);
                btn?.click();
            }"""
        )
        page.wait_for_timeout(15000)

        if captured:
            print("\nPOST:", captured["post_data"])
            headers = captured["data"].get("GreatWalkFacilityHeaderData", [])
            print("Header dates:", [h["FullDate"][:10] for h in headers])
            facilities = captured["data"].get("GreatWalkFacilityData", [])
            for fac in facilities[:3]:
                avail = [d for d in fac["GreatWalkFacilityDateData"] if d.get("IsAvailable")]
                print(
                    fac["FacilityName"],
                    "available dates:",
                    [d["ArrivalDate"][:10] for d in avail[:5]],
                )
        else:
            print("No capture")

        browser.close()


if __name__ == "__main__":
    main()
