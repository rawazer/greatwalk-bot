"""Capture all API calls after GW search navigation."""

from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    urls: list[str] = []

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
            if "tylerapp.com" in response.url:
                urls.append(f"{response.request.method} {response.status} {response.url.split('/rdr/')[-1]}")

        page.on("response", on_resp)
        page.goto(
            "https://bookings.doc.govt.nz/Web/Default.aspx",
            wait_until="networkidle",
            timeout=120_000,
        )
        page.wait_for_timeout(3000)
        page.evaluate("window.location.hash = '#!greatwalk-result'")
        page.wait_for_timeout(8000)

        # Routeburn = great-walk-8 (0=placeholder, 1=abel, ... 5=milford, 8=routeburn?)
        # From earlier: great-walk-mobile-8 = Routeburn
        page.evaluate("document.getElementById('great-walk-8')?.click()")
        page.wait_for_timeout(3000)

        before_hash = page.evaluate("() => window.location.hash")
        page.evaluate(
            """() => {
                const btn = Array.from(document.querySelectorAll('button'))
                    .find(b => b.textContent.trim() === 'Search' && b.offsetParent);
                btn?.click();
            }"""
        )

        for wait in (5, 10, 15, 20):
            page.wait_for_timeout(5000)
            state = page.evaluate(
                """() => ({
                    hash: window.location.hash,
                    title: document.title,
                    tables: document.querySelectorAll('table').length,
                    gwGrid: document.querySelectorAll('[class*=great-walk]').length,
                    bodyText: document.body.innerText.slice(0, 500)
                })"""
            )
            print(f"\n--- after {wait}s ---")
            print(json.dumps(state, indent=2)[:1500])

        print("\nAll Tyler URLs:")
        for u in urls:
            print(" ", u)

        browser.close()


if __name__ == "__main__":
    main()
