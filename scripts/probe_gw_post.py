"""Try POST greatwalkplacefacility via jQuery after SPA session."""

from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
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
        page.evaluate("document.getElementById('great-walk-5')?.click()")
        page.wait_for_timeout(5000)

        bodies = [
            {
                "PlaceId": 873,
                "StartDate": "2026-12-07",
                "NightCount": 3,
                "CustomerClassificationId": 0,
                "SeasonId": 0,
            },
            {
                "PlaceId": 873,
                "StartDate": "2026-12-07",
                "NightCount": 3,
                "CustomerClassificationId": 0,
                "SeasonId": 0,
                "Xy": 873,
                "AP": 873,
                "xx": 3,
                "oK": "2026-12-07",
            },
        ]

        for i, body in enumerate(bodies):
            result = page.evaluate(
                """async ({body}) => {
                    const api = window.apiurl;
                    return new Promise((resolve) => {
                        $.ajax({
                            type: 'POST',
                            url: api + 'search/greatwalkplacefacility',
                            contentType: 'application/json; charset=utf-8',
                            dataType: 'json',
                            data: JSON.stringify(body),
                            success: (d) => resolve({ok: true, keys: Object.keys(d), sample: d}),
                            error: (x) => resolve({
                                ok: false,
                                status: x.status,
                                text: (x.responseText || '').slice(0, 800),
                            }),
                        });
                    });
                }""",
                {"body": body},
            )
            print(f"\n=== Body variant {i} ===")
            print(json.dumps(result, indent=2)[:6000])

        # Also try GET facility information endpoints for date range
        for path in [
            "search/getgreatwalkfacilityinformation/facilityId/0/startDate/2026-12-07",
            "search/getgreatwalkalert/placeId/873/alertId/0/startDate/2026-12-07",
        ]:
            result = page.evaluate(
                """async ({path}) => {
                    const api = window.apiurl;
                    return new Promise((resolve) => {
                        $.getJSON(api + path)
                            .done((d) => resolve({ok: true, keys: Object.keys(d), sample: d}))
                            .fail((x) => resolve({ok: false, status: x.status, text: (x.responseText||'').slice(0,400)}));
                    });
                }""",
                {"path": path},
            )
            print(f"\n=== GET {path} ===")
            print(json.dumps(result, indent=2)[:4000])

        browser.close()


if __name__ == "__main__":
    main()
