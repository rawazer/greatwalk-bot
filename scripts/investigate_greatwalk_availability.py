"""Deep-dive: capture Great Walk availability grid API calls."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUTPUT = Path(__file__).resolve().parents[1] / "investigation_output"
BASE = "https://bookings.doc.govt.nz/Web/Default.aspx"


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    captured: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def on_response(response):
            url = response.url
            if "tylerapp.com" not in url:
                return
            if not any(
                k in url
                for k in (
                    "greatwalk",
                    "search/grid",
                    "search/place",
                    "search/details",
                    "availability",
                    "getbyunit",
                )
            ):
                return
            body = None
            try:
                body = response.text()
            except Exception:
                body = None
            captured.append(
                {
                    "url": url,
                    "method": response.request.method,
                    "status": response.status,
                    "request_body": response.request.post_data,
                    "response_preview": (body[:12000] + "...") if body and len(body) > 12000 else body,
                }
            )

        page.on("response", on_response)
        page.goto(f"{BASE}#!greatwalk-result", wait_until="networkidle", timeout=120_000)
        page.wait_for_timeout(6000)

        # Click first Great Walk place card if rendered
        selectors = [
            "text=Abel Tasman",
            "text=Milford",
            "text=Routeburn",
            "[class*='greatwalk'] a",
            "table tbody tr",
        ]
        for sel in selectors:
            loc = page.locator(sel)
            if loc.count():
                try:
                    loc.first.click(timeout=5000)
                    page.wait_for_timeout(10000)
                    break
                except Exception:
                    continue

        browser.close()

    (OUTPUT / "greatwalk_availability_capture.json").write_text(
        json.dumps(captured, indent=2), encoding="utf-8"
    )
    print(f"Captured {len(captured)} availability-related RDR requests")
    for item in captured:
        print(f"  {item['method']} {item['status']} {item['url'][:120]}")


if __name__ == "__main__":
    main()
