"""Capture all Tyler JSON after navigating to Milford via hash + click."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUTPUT = Path(__file__).resolve().parents[1] / "investigation_output"


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    captured: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
        )

        def on_response(response):
            url = response.url
            if "tylerapp.com" not in url or response.status != 200:
                return
            if "json" not in response.headers.get("content-type", ""):
                return
            try:
                data = response.json()
            except Exception:
                return
            captured.append(
                {
                    "url": url,
                    "method": response.request.method,
                    "body": response.request.post_data,
                    "data": data,
                }
            )

        page.on("response", on_response)
        page.goto(
            "https://bookings.doc.govt.nz/Web/Default.aspx",
            wait_until="networkidle",
            timeout=120_000,
        )
        page.wait_for_timeout(3000)
        page.evaluate("window.location.hash = '#!greatwalk-result'")
        page.wait_for_timeout(8000)

        # Debug: what's on page
        texts = page.evaluate(
            """() => Array.from(document.querySelectorAll('a, button, td, th, h2, h3'))
                .map(e => e.textContent?.trim()).filter(t => t && t.length < 60).slice(0, 40)"""
        )
        print("Visible text samples:", texts[:20])

        for sel in (
            "text=Milford Track",
            "a:has-text('Milford')",
            "[aria-label*='Milford']",
            "td:has-text('Milford')",
        ):
            loc = page.locator(sel)
            n = loc.count()
            print(f"selector {sel!r}: {n}")
            if n:
                try:
                    loc.first.click(timeout=5000)
                    page.wait_for_timeout(15000)
                    break
                except Exception as exc:
                    print(f"  click failed: {exc}")

        browser.close()

    path = OUTPUT / "milford_capture.json"
    # Save compact - truncate large data for inspection
    summary = []
    for item in captured:
        data = item["data"]
        entry = {"url": item["url"].split("/rdr/")[-1], "method": item["method"]}
        if isinstance(data, dict):
            entry["top_keys"] = list(data.keys())
            for k, v in data.items():
                if isinstance(v, list) and v:
                    entry[f"{k}_len"] = len(v)
                    entry[f"{k}_sample_keys"] = list(v[0].keys())[:15] if isinstance(v[0], dict) else str(v[0])[:80]
        summary.append(entry)
    print(json.dumps(summary, indent=2))
    path.write_text(json.dumps(captured, indent=2), encoding="utf-8")
    print(f"Saved {len(captured)} to {path}")


if __name__ == "__main__":
    main()
