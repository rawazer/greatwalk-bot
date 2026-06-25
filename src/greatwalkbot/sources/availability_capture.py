"""Match and classify Great Walk availability network responses."""

from __future__ import annotations

from typing import Any, Callable

from greatwalkbot.sources.network_recorder import (
    AVAILABILITY_PAYLOAD_PATH,
    NetworkRecorder,
    response_body_is_availability_payload,
)


def availability_response_predicate(response: Any) -> bool:
    url = str(getattr(response, "url", "")).lower()
    if AVAILABILITY_PAYLOAD_PATH not in url:
        return False
    status = int(getattr(response, "status", 0) or 0)
    if status != 200:
        return False
    headers = getattr(response, "headers", {}) or {}
    content_type = str(headers.get("content-type", "")).lower()
    return "json" in content_type


def parse_availability_response(response: Any) -> dict | None:
    try:
        data = response.json()
    except Exception:
        return None
    if response_body_is_availability_payload(data):
        return data
    return None


def wait_for_availability_response(
    page: Any,
    *,
    click_search: Callable[[], None],
    timeout_ms: int,
) -> dict:
    """Register expect_response before triggering search (no race with click)."""
    with page.expect_response(availability_response_predicate, timeout=timeout_ms) as info:
        click_search()
    response = info.value
    payload = parse_availability_response(response)
    if payload is None:
        from greatwalkbot.infra.errors import AvailabilityRequestFailedError

        raise AvailabilityRequestFailedError(
            f"Availability response matched path but payload was not parseable "
            f"(status={response.status})",
            path=AVAILABILITY_PAYLOAD_PATH,
            status=response.status,
        )
    return payload


def classify_capture_failure(
    recorder: NetworkRecorder,
    *,
    selection_committed: bool,
    place_id: int,
    timeout_ms: int,
    page_html: str | None = None,
) -> Exception:
    from greatwalkbot.infra.errors import (
        AvailabilityRequestFailedError,
        AvailabilityRequestNotObservedError,
        TrackSelectionNotCommittedError,
        WafChallengeSuspectedError,
    )

    waf_signals = list(recorder.waf_signals)
    if page_html:
        lowered = page_html.lower()
        for marker in ("awswaf", "captcha", "x-amzn-waf-action"):
            if marker in lowered and marker not in waf_signals:
                waf_signals.append(f"html:{marker}")

    if waf_signals:
        return WafChallengeSuspectedError(
            "DOC/WAF challenge indicators observed in network or page content",
            signals=tuple(waf_signals),
        )

    if not selection_committed and not recorder.saw_selection_metadata(place_id):
        return TrackSelectionNotCommittedError(
            f"Track selection for place_id={place_id} did not commit within the "
            "bounded timeout (no UI state change or selection metadata request)",
            place_id=place_id,
        )

    failed = recorder.failed_availability_response()
    if failed is not None:
        return AvailabilityRequestFailedError(
            f"Availability request returned HTTP {failed.status}",
            path=failed.path,
            status=failed.status,
        )

    if recorder.saw_availability_response():
        return AvailabilityRequestFailedError(
            "Availability endpoint responded but payload was not captured",
            path=AVAILABILITY_PAYLOAD_PATH,
            status=200,
        )

    if recorder.saw_availability_request():
        return AvailabilityRequestNotObservedError(
            f"Availability request was observed but no JSON response arrived within "
            f"{timeout_ms}ms",
            path=AVAILABILITY_PAYLOAD_PATH,
        )

    return AvailabilityRequestNotObservedError(
        f"No greatwalkplacefacility request observed within {timeout_ms}ms after search",
        path=AVAILABILITY_PAYLOAD_PATH,
    )
