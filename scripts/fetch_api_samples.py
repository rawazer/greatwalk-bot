"""Fetch Tyler RDR samples using Playwright request context after page load."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUTPUT = Path(__file__).resolve().parents[1] / "investigation_output" / "samples"
RDR = "https://prod-nz-rdr.recreation-management.tylerapp.com/nzrdr/rdr"
SITE = "https://bookings.doc.govt.nz/Web/Default.aspx"


def get_json(request, path: str) -> tuple[int, dict | list]:
    url = f"{RDR}/{path.lstrip('/')}"
    resp = request.get(
        url,
        headers={
            "Accept": "application/json",
            "Referer": "https://bookings.doc.govt.nz/",
        },
    )
    return resp.status, resp.json()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(SITE, wait_until="networkidle", timeout=120_000)
        request = context.request

        endpoints = {
            "greatwalk_places": "search/getgreatwalkplaces/false/isCashier",
            "booking_window": "search/bookingwindow",
            "website_settings": "enterprise/websitesettings",
            "popular_places": "search/popular/places/10",
            "filters": "search/filters/0",
        }

        results = {}
        for name, path in endpoints.items():
            status, data = get_json(request, path)
            results[name] = {"status": status, "path": path, "data": data}
            (OUTPUT / f"{name}.json").write_text(
                json.dumps(results[name], indent=2), encoding="utf-8"
            )
            print(f"{name}: {status}")

        start = results["booking_window"]["data"].get("FutureBookingStartDate", "2026-10-01")
        place = results["greatwalk_places"]["data"]["GWPlaceData"][0]
        place_id = place["PlaceId"]
        place_name = place["Name"]

        status, gw_data = get_json(request, f"search/getgreatwalksearchdata/placeId/{place_id}")
        (OUTPUT / "greatwalk_search_data.json").write_text(
            json.dumps(
                {
                    "status": status,
                    "place_id": place_id,
                    "place_name": place_name,
                    "data": gw_data,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"greatwalk_search_data ({place_name}): {status}")

        # Facility information for first facility if present in search data
        facilities = gw_data.get("GWFacilityData") or gw_data.get("FacilityData") or []
        if facilities:
            fac = facilities[0]
            fac_id = fac.get("FacilityId") or fac.get("Id")
            if fac_id:
                status, fac_info = get_json(
                    request,
                    f"search/getgreatwalkfacilityinformation/facilityId/{fac_id}/startDate/{start}",
                )
                (OUTPUT / "greatwalk_facility_info.json").write_text(
                    json.dumps(
                        {
                            "status": status,
                            "facility_id": fac_id,
                            "start_date": start,
                            "data": fac_info,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                print(f"greatwalk_facility_info ({fac_id}): {status}")

                # POST greatwalkplacefacility - inspect request shape from main.js
                resp = request.post(
                    f"{RDR}/search/greatwalkplacefacility",
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Referer": "https://bookings.doc.govt.nz/",
                    },
                    data=json.dumps(
                        {
                            "PlaceId": place_id,
                            "StartDate": start,
                            "NightCount": 1,
                            "CustomerClassificationId": 0,
                            "SeasonId": fac.get("SeasonId", 0),
                        }
                    ),
                )
                body = resp.text()
                try:
                    parsed = resp.json()
                except Exception:
                    parsed = body[:2000]
                (OUTPUT / "greatwalk_place_facility_post.json").write_text(
                    json.dumps(
                        {
                            "status": resp.status,
                            "request_body": {
                                "PlaceId": place_id,
                                "StartDate": start,
                                "NightCount": 1,
                            },
                            "data": parsed,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                print(f"greatwalkplacefacility POST: {resp.status}")

        browser.close()


if __name__ == "__main__":
    main()
