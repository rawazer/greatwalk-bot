"""Direct HTTP availability source (typically blocked by AWS WAF)."""

from __future__ import annotations

from datetime import date

import httpx

from greatwalkbot.constants import GW_FACILITY_PATH, RDR_BASE_URL
from greatwalkbot.models import AvailabilitySnapshot, Track
from greatwalkbot.parsing import build_gw_facility_request, parse_gw_facility_response


class HttpAvailabilitySource:
    """POST to Tyler RDR without a browser. Useful for tests and future WAF bypass work."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=30.0)

    def fetch_track_availability(
        self,
        track: Track,
        from_date: date,
        to_date: date,
    ) -> AvailabilitySnapshot:
        body = build_gw_facility_request(track, from_date, to_date)
        response = self._client.post(
            f"{RDR_BASE_URL}{GW_FACILITY_PATH}",
            json=body,
            headers={
                "Accept": "application/json",
                "Referer": "https://bookings.doc.govt.nz/",
                "Origin": "https://bookings.doc.govt.nz",
            },
        )
        if response.status_code != 200 or "json" not in response.headers.get("content-type", ""):
            raise RuntimeError(
                f"HTTP availability request failed ({response.status_code}). "
                "Direct calls are usually blocked by AWS WAF; use the playwright source."
            )
        payload = response.json()
        return parse_gw_facility_response(payload, track, from_date, to_date)
