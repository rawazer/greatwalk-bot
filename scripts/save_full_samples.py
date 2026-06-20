"""Save full JSON responses for key Tyler RDR endpoints during page load."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUTPUT = Path(__file__).resolve().parents[1] / "investigation_output" / "samples"
BASE = "https://bookings.doc.govt.nz/Web/Default.aspx"

KEY_SUFFIXES = (
    "search/bookingwindow",
    "search/getgreatwalkplaces/false/isCashier",
    "enterprise/websitesettings",
    "search/popular/places/10",
    "search/filters/0",
)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    saved: dict[str, dict] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def on_response(response):
            url = response.url
            if not any(url.endswith(s) or f"/{s}" in url for s in KEY_SUFFIXES):
                return
            for suffix in KEY_SUFFIXES:
                if suffix in url:
                    key = suffix.replace("/", "_")
                    break
            else:
                return
            if response.status != 200:
                return
            try:
                data = response.json()
            except Exception:
                return
            saved[key] = {
                "url": url,
                "method": response.request.method,
                "status": response.status,
                "request_headers": {
                    k: v
                    for k, v in response.request.headers.items()
                    if k.lower() not in {"cookie"}
                },
                "data": data,
            }

        page.on("response", on_response)
        page.goto(BASE, wait_until="networkidle", timeout=120_000)
        page.wait_for_timeout(3000)
        page.evaluate("window.location.hash = '#!greatwalk-result'")
        page.wait_for_timeout(8000)
        browser.close()

    for key, payload in saved.items():
        (OUTPUT / f"{key}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"saved {key}")

    if "search_getgreatwalkplaces_false_isCashier" in saved:
        places = saved["search_getgreatwalkplaces_false_isCashier"]["data"]["GWPlaceData"]
        print(f"Great Walk places: {len(places)}")
        for place in places[:3]:
            print(f"  - {place['PlaceId']}: {place['Name']}")


if __name__ == "__main__":
    main()
