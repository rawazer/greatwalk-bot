"""Trigger Great Walk selection via JS click and capture availability APIs."""

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
            if not any(k in url for k in ("getgreatwalk", "greatwalkplace", "grid", "availability")):
                return
            try:
                captured.append(
                    {
                        "url": url,
                        "method": response.request.method,
                        "post_data": response.request.post_data,
                        "data": response.json(),
                    }
                )
            except Exception:
                pass

        page.on("response", on_resp)
        page.goto(
            "https://bookings.doc.govt.nz/Web/Default.aspx",
            wait_until="networkidle",
            timeout=120_000,
        )
        page.wait_for_timeout(3000)
        page.evaluate("window.location.hash = '#!greatwalk-result'")
        page.wait_for_timeout(8000)

        ids = page.evaluate(
            """() => Array.from(document.querySelectorAll('[id^=\"great-walk\"]'))
                .map(e => ({id: e.id, visible: !!(e.offsetParent), tag: e.tagName}))"""
        )
        print("IDs:", [x for x in ids if "Milford" in str(x) or x["id"] in ("great-walk-5", "great-walk-dropdown-button")])

        clicked = page.evaluate(
            """() => {
                const el = document.getElementById('great-walk-5')
                    || document.getElementById('great-walk-mobile-5');
                if (!el) return 'no element';
                el.click();
                return el.id;
            }"""
        )
        print("Clicked:", clicked)
        page.wait_for_timeout(15000)

        browser.close()

    OUTPUT.mkdir(exist_ok=True)
    path = OUTPUT / "milford_availability.json"
    path.write_text(json.dumps(captured, indent=2), encoding="utf-8")
    print(f"Captured {len(captured)} -> {path}")
    for item in captured:
        short = item["url"].split("/rdr/")[-1]
        data = item["data"]
        print(f"\n{item['method']} {short}")
        if item.get("post_data"):
            print(f"  POST body: {item['post_data'][:200]}")
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    print(f"  {k}: [{len(v)} items]")
                    if v and isinstance(v[0], dict):
                        print(f"    sample keys: {list(v[0].keys())[:12]}")
                elif isinstance(v, dict):
                    print(f"  {k}: dict({len(v)} keys)")
                else:
                    print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
