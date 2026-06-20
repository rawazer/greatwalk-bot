"""Milford: select track, set date, search, capture grid."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUTPUT = Path(__file__).resolve().parents[1] / "investigation_output"


def main() -> None:
    captured: list[dict] = []

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
            url = response.url
            if "tylerapp.com" not in url or response.status != 200:
                return
            if "json" not in response.headers.get("content-type", ""):
                return
            captured.append(
                {
                    "url": url.split("/rdr/")[-1],
                    "method": response.request.method,
                    "post_data": response.request.post_data,
                    "data": response.json(),
                }
            )

        page.on("response", on_resp)
        page.goto(
            "https://bookings.doc.govt.nz/Web/Default.aspx",
            wait_until="networkidle",
            timeout=120_000,
        )
        page.wait_for_timeout(3000)
        page.evaluate("window.location.hash = '#!greatwalk-result'")
        page.wait_for_timeout(8000)

        date_els = page.evaluate(
            """() => Array.from(document.querySelectorAll('[id*=great-walk][id*=date], [id*=start-date], input[type=date], .custom-date-input-btn'))
                .map(e => ({id: e.id, tag: e.tagName, value: e.value, text: (e.textContent||'').trim().slice(0,30), visible: !!e.offsetParent}))"""
        )
        print("Date elements:", json.dumps(date_els, indent=2))

        result = page.evaluate(
            """() => {
                document.getElementById('great-walk-5')?.click();
                const searchBtn = Array.from(document.querySelectorAll('button'))
                    .find(b => b.textContent.trim() === 'Search' && b.offsetParent);
                if (searchBtn) { searchBtn.click(); return 'search clicked'; }
                return 'no search btn';
            }"""
        )
        print("Action:", result)
        page.wait_for_timeout(25000)
        browser.close()

    avail = [
        c
        for c in captured
        if any(x in c["url"] for x in ("greatwalkplace", "grid", "occupancy", "facilityinformation", "getgreatwalk"))
    ]
    path = OUTPUT / "milford_grid2.json"
    path.write_text(json.dumps(avail, indent=2), encoding="utf-8")
    print(f"Captured {len(avail)} avail endpoints (of {len(captured)} total)")
    for item in avail:
        print(f"\n=== {item['method']} {item['url']} ===")
        if item.get("post_data"):
            print("POST:", item["post_data"])
        dump = json.dumps(item["data"], indent=2)
        print(dump[:4000])
        if len(dump) > 4000:
            print("... [truncated]")


if __name__ == "__main__":
    main()
