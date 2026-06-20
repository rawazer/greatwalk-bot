"""Capture network requests from the DOC booking site (read-only investigation)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

OUTPUT = Path(__file__).resolve().parents[1] / "investigation_output"
BASE_URL = "https://bookings.doc.govt.nz/Web/Default.aspx"
RDR_HOST = "prod-nz-rdr.recreation-management.tylerapp.com"

INTERESTING_PATTERNS = (
    RDR_HOST,
    "bookings.doc.govt.nz/Web/",
    ".asmx/",
    "Default.aspx/",
)


def is_interesting(url: str) -> bool:
    return any(p in url for p in INTERESTING_PATTERNS)


def summarize_request(request, response) -> dict:
    entry = {
        "url": request.url,
        "method": request.method,
        "resource_type": request.resource_type,
        "request_headers": {
            k: v
            for k, v in request.headers.items()
            if k.lower()
            not in {
                "cookie",
                "authorization",
                "x-amz-security-token",
            }
        },
        "status": response.status if response else None,
        "response_headers": {},
        "response_body_preview": None,
        "response_content_type": None,
    }
    if response:
        entry["response_headers"] = {
            k: v
            for k, v in response.headers.items()
            if k.lower() not in {"set-cookie"}
        }
        entry["response_content_type"] = response.headers.get("content-type")
        try:
            body = response.text()
            if len(body) > 8000:
                entry["response_body_preview"] = body[:8000] + "\n... [truncated]"
            else:
                entry["response_body_preview"] = body
        except Exception as exc:  # noqa: BLE001
            entry["response_body_preview"] = f"<unable to read body: {exc}>"
    post = request.post_data
    if post:
        entry["request_body"] = post[:4000] + ("..." if len(post) > 4000 else "")
    return entry


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    captured: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        def on_response(response):
            request = response.request
            if not is_interesting(request.url):
                return
            captured.append(summarize_request(request, response))

        page.on("response", on_response)

        print("Loading Default.aspx ...")
        page.goto(BASE_URL, wait_until="networkidle", timeout=120_000)
        page.wait_for_timeout(5000)

        # Try navigating to Great Walks hash route used by SPA
        print("Navigating to Great Walks view ...")
        page.evaluate("window.location.hash = '#!greatwalk-result'")
        page.wait_for_timeout(8000)

        # Try clicking Great Walk link if present
        for selector in [
            "text=Great Walk",
            "a[href*='greatwalk']",
            "[aria-label*='Great Walk']",
        ]:
            loc = page.locator(selector)
            if loc.count() > 0:
                try:
                    loc.first.click(timeout=5000)
                    page.wait_for_timeout(8000)
                    break
                except Exception:
                    pass

        # Save page title and any embedded config
        page_info = {
            "title": page.title(),
            "url": page.url,
            "apiurl": page.evaluate("() => window.apiurl || null"),
            "defaultPlaceID": page.evaluate("() => window.defaultPlaceID || null"),
            "enterpriceName": page.evaluate("() => window.enterpriceName || null"),
        }
        (OUTPUT / "page_info.json").write_text(
            json.dumps(page_info, indent=2), encoding="utf-8"
        )

        browser.close()

    # Deduplicate by URL+method, keep latest
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for item in reversed(captured):
        key = (item["method"], item["url"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    unique.reverse()

    (OUTPUT / "network_capture.json").write_text(
        json.dumps(unique, indent=2), encoding="utf-8"
    )

    rdr = [u for u in unique if RDR_HOST in u["url"]]
    aspnet = [
        u
        for u in unique
        if "bookings.doc.govt.nz" in u["url"]
        and (".asmx" in u["url"] or "Default.aspx/" in u["url"])
    ]

    print(f"Captured {len(unique)} unique interesting requests")
    print(f"  Tyler RDR API: {len(rdr)}")
    print(f"  ASP.NET endpoints: {len(aspnet)}")
    print("\nTyler RDR endpoints:")
    for item in rdr:
        path = urlparse(item["url"]).path
        print(f"  {item['method']} {item['status']} {path}")

    print("\nASP.NET endpoints:")
    for item in aspnet:
        print(f"  {item['method']} {item['status']} {item['url']}")


if __name__ == "__main__":
    main()
