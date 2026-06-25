"""Match and classify Great Walk availability network responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from greatwalkbot.sources.network_recorder import (
    AVAILABILITY_PAYLOAD_PATH,
    NetworkRecorder,
    concrete_waf_signals,
    path_is_availability,
    response_body_is_availability_payload,
    sanitize_url_path,
)

CaptureFailureStage = Literal[
    "wait_for_response",
    "read_json",
    "validate_payload",
]


@dataclass
class CaptureLifecycle:
    waiter_registered_before_search: bool = False
    search_click_observed: bool = False
    expected_response_seen: bool = False
    expected_response_status: int | None = None
    expected_response_content_type: str | None = None
    capture_timeout_ms: int = 0
    capture_failure_stage: CaptureFailureStage | None = None
    attempt: int = 1
    session_restarted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "waiter_registered_before_search": self.waiter_registered_before_search,
            "search_click_observed": self.search_click_observed,
            "expected_response_seen": self.expected_response_seen,
            "expected_response_status": self.expected_response_status,
            "expected_response_content_type": self.expected_response_content_type,
            "capture_timeout_ms": self.capture_timeout_ms,
            "capture_failure_stage": self.capture_failure_stage,
            "attempt": self.attempt,
            "session_restarted": self.session_restarted,
        }


def expected_greatwalk_facility_response(response: Any) -> bool:
    """Strict predicate for the post-search Great Walk facility POST."""
    request = getattr(response, "request", None)
    method = str(getattr(request, "method", "") or "").upper()
    if method != "POST":
        return False
    url = str(getattr(response, "url", "")).lower()
    if AVAILABILITY_PAYLOAD_PATH not in url:
        return False
    if "/nzrdr/rdr/search/greatwalkplacefacility" not in url.replace("\\", "/"):
        normalized = sanitize_url_path(url).lower()
        if AVAILABILITY_PAYLOAD_PATH not in normalized:
            return False
    status = int(getattr(response, "status", 0) or 0)
    if status != 200:
        return False
    headers = getattr(response, "headers", {}) or {}
    content_type = str(headers.get("content-type", "")).lower()
    return "json" in content_type


def post_search_response_predicate(response: Any) -> bool:
    """Loose post-search candidate predicate (diagnostics only; not used for capture)."""
    url = str(getattr(response, "url", "")).lower()
    if "getgreatwalksearchdata" in url:
        return False
    from greatwalkbot.sources.network_recorder import POST_SEARCH_RESPONSE_PATHS

    if not any(marker in url for marker in POST_SEARCH_RESPONSE_PATHS):
        return False
    status = int(getattr(response, "status", 0) or 0)
    if status not in (200, 201):
        return True
    headers = getattr(response, "headers", {}) or {}
    content_type = str(headers.get("content-type", "")).lower()
    return "json" in content_type


def availability_response_predicate(response: Any) -> bool:
    return expected_greatwalk_facility_response(response)


def bounded_response_metadata(response: Any) -> dict[str, Any]:
    headers = getattr(response, "headers", {}) or {}
    request = getattr(response, "request", None)
    return {
        "method": str(getattr(request, "method", "") or "").upper() or None,
        "path": sanitize_url_path(str(getattr(response, "url", ""))),
        "status": int(getattr(response, "status", 0) or 0) or None,
        "content_type": str(headers.get("content-type", ""))[:120] or None,
    }


def bounded_payload_shape_metadata(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"shape": type(payload).__name__}
    keys = sorted(str(key) for key in payload.keys())[:20]
    facility = payload.get("GreatWalkFacilityData")
    facility_count = len(facility) if isinstance(facility, list) else None
    return {
        "top_level_keys": keys,
        "has_great_walk_facility_data": "GreatWalkFacilityData" in payload,
        "facility_entry_count": facility_count,
    }


def build_capture_diagnostics(
    recorder: NetworkRecorder,
    lifecycle: CaptureLifecycle,
    *,
    response_metadata: dict[str, Any] | None = None,
    payload_shape: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "capture_lifecycle": lifecycle.to_dict(),
        "post_search_network_timeline": recorder.post_search_timeline_dicts(),
        "expected_post_request_seen": recorder.saw_expected_facility_request_post_search(),
        "expected_post_response_seen": recorder.saw_expected_facility_response_post_search(),
        "generic_post_search_candidate_response_seen": recorder.saw_post_search_candidate_response(),
        "response_metadata": response_metadata,
        "payload_shape": payload_shape,
    }


def parse_facility_response(
    response: Any,
    lifecycle: CaptureLifecycle,
    *,
    recorder: NetworkRecorder | None = None,
) -> dict:
    from greatwalkbot.infra.errors import AvailabilityRequestFailedError

    lifecycle.expected_response_seen = True
    lifecycle.expected_response_status = int(getattr(response, "status", 0) or 0) or None
    headers = getattr(response, "headers", {}) or {}
    lifecycle.expected_response_content_type = (
        str(headers.get("content-type", ""))[:120] or None
    )
    response_meta = bounded_response_metadata(response)
    try:
        data = response.json()
    except Exception as exc:
        lifecycle.capture_failure_stage = "read_json"
        diag = (
            build_capture_diagnostics(recorder, lifecycle, response_metadata=response_meta)
            if recorder is not None
            else {"response_metadata": response_meta}
        )
        raise AvailabilityRequestFailedError(
            "Expected Great Walk facility response was not valid JSON",
            path=AVAILABILITY_PAYLOAD_PATH,
            status=lifecycle.expected_response_status,
            capture_lifecycle=lifecycle.to_dict(),
            capture_diagnostics=diag,
        ) from exc
    if not response_body_is_availability_payload(data):
        lifecycle.capture_failure_stage = "validate_payload"
        raise AvailabilityRequestFailedError(
            "Expected Great Walk facility response missing GreatWalkFacilityData",
            path=AVAILABILITY_PAYLOAD_PATH,
            status=lifecycle.expected_response_status,
            capture_lifecycle=lifecycle.to_dict(),
            capture_diagnostics={
                **(
                    build_capture_diagnostics(
                        recorder,
                        lifecycle,
                        response_metadata=response_meta,
                        payload_shape=bounded_payload_shape_metadata(data),
                    )
                    if recorder is not None
                    else {}
                ),
                "response_metadata": response_meta,
                "payload_shape": bounded_payload_shape_metadata(data),
            },
        )
    return data


def wait_for_availability_response(
    page: Any,
    *,
    click_search: Callable[[], None],
    timeout_ms: int,
    recorder: NetworkRecorder | None = None,
    attempt: int = 1,
    session_restarted: bool = False,
) -> tuple[dict, CaptureLifecycle]:
    """Register expect_response before Search click; wait only for strict facility POST."""
    from greatwalkbot.infra.errors import AvailabilityRequestFailedError

    lifecycle = CaptureLifecycle(
        capture_timeout_ms=timeout_ms,
        attempt=attempt,
        session_restarted=session_restarted,
    )
    lifecycle.waiter_registered_before_search = True

    response: Any | None = None
    try:
        with page.expect_response(
            expected_greatwalk_facility_response,
            timeout=timeout_ms,
        ) as response_info:
            click_search()
            lifecycle.search_click_observed = True
        response = response_info.value
    except Exception as exc:
        if lifecycle.capture_failure_stage is None:
            lifecycle.capture_failure_stage = "wait_for_response"
        diagnostics = None
        if recorder is not None:
            diagnostics = build_capture_diagnostics(recorder, lifecycle)
        if isinstance(exc, AvailabilityRequestFailedError):
            raise
        message = (
            f"Timed out waiting for POST {AVAILABILITY_PAYLOAD_PATH} "
            f"JSON response within {timeout_ms}ms"
        )
        raise AvailabilityRequestFailedError(
            message,
            path=AVAILABILITY_PAYLOAD_PATH,
            capture_lifecycle=lifecycle.to_dict(),
            capture_diagnostics=diagnostics,
        ) from exc

    assert response is not None
    try:
        payload = parse_facility_response(response, lifecycle, recorder=recorder)
    except AvailabilityRequestFailedError as exc:
        if recorder is not None and exc.capture_diagnostics is None:
            exc.capture_diagnostics = build_capture_diagnostics(
                recorder,
                lifecycle,
                response_metadata=bounded_response_metadata(response),
            )
        raise
    diagnostics = None
    if recorder is not None:
        diagnostics = build_capture_diagnostics(
            recorder,
            lifecycle,
            response_metadata=bounded_response_metadata(response),
            payload_shape=bounded_payload_shape_metadata(payload),
        )
    lifecycle.expected_response_seen = True
    return payload, lifecycle


def classify_capture_failure(
    recorder: NetworkRecorder,
    *,
    selection_committed: bool,
    search_submitted: bool,
    place_id: int,
    timeout_ms: int,
    page_html: str | None = None,
    form_state: dict | None = None,
    capture_lifecycle: CaptureLifecycle | None = None,
    attempt: int = 1,
) -> Exception:
    from greatwalkbot.infra.errors import (
        AvailabilityRequestFailedError,
        AvailabilityRequestNotObservedError,
        AvailabilitySearchNotDispatchedError,
        TrackSelectionNotCommittedError,
        WafChallengeSuspectedError,
    )

    lifecycle = capture_lifecycle or CaptureLifecycle(
        capture_timeout_ms=timeout_ms,
        attempt=attempt,
        capture_failure_stage="wait_for_response",
    )
    diagnostics = build_capture_diagnostics(recorder, lifecycle)

    waf_signals = concrete_waf_signals(recorder.waf_signals, page_html=page_html)
    if waf_signals:
        return WafChallengeSuspectedError(
            "DOC/WAF challenge indicators observed in network or page content",
            signals=waf_signals,
        )

    if not selection_committed and not recorder.saw_selection_metadata(place_id):
        return TrackSelectionNotCommittedError(
            f"Track selection for place_id={place_id} did not commit within the "
            "bounded timeout (no UI state change or selection metadata request)",
            place_id=place_id,
        )

    failed_post = recorder.failed_post_search_response()
    if failed_post is not None and path_is_availability(failed_post.path):
        return AvailabilityRequestFailedError(
            f"Expected facility POST returned HTTP {failed_post.status}",
            path=failed_post.path,
            status=failed_post.status,
            capture_lifecycle=lifecycle.to_dict(),
            capture_diagnostics=diagnostics,
        )

    failed = recorder.failed_availability_response()
    if failed is not None:
        return AvailabilityRequestFailedError(
            f"Availability request returned HTTP {failed.status}",
            path=failed.path,
            status=failed.status,
            capture_lifecycle=lifecycle.to_dict(),
            capture_diagnostics=diagnostics,
        )

    if recorder.saw_expected_facility_response_post_search():
        return AvailabilityRequestFailedError(
            "Expected facility POST responded but payload was not captured by the waiter",
            path=AVAILABILITY_PAYLOAD_PATH,
            status=200,
            capture_lifecycle=lifecycle.to_dict(),
            capture_diagnostics=diagnostics,
        )

    if recorder.saw_post_search_candidate_response() and not recorder.saw_expected_facility_request_post_search():
        alt = recorder.first_post_search_candidate_response()
        return AvailabilityRequestFailedError(
            "Generic post-search candidate responded but expected facility POST was not observed",
            path=alt.path if alt else AVAILABILITY_PAYLOAD_PATH,
            status=alt.status if alt else None,
            capture_lifecycle=lifecycle.to_dict(),
            capture_diagnostics=diagnostics,
        )

    if recorder.saw_expected_facility_request_post_search():
        return AvailabilityRequestNotObservedError(
            f"Expected facility POST request was observed but no JSON response arrived within "
            f"{timeout_ms}ms",
            path=AVAILABILITY_PAYLOAD_PATH,
            capture_lifecycle=lifecycle.to_dict(),
            capture_diagnostics=diagnostics,
        )

    if search_submitted and recorder.saw_selection_metadata(place_id):
        return AvailabilitySearchNotDispatchedError(
            "Track selection committed but Search did not dispatch the expected facility POST",
            form_state=form_state,
            path=AVAILABILITY_PAYLOAD_PATH,
        )

    if recorder.saw_availability_request():
        return AvailabilityRequestNotObservedError(
            f"Availability request was observed but no JSON response arrived within "
            f"{timeout_ms}ms",
            path=AVAILABILITY_PAYLOAD_PATH,
            capture_lifecycle=lifecycle.to_dict(),
            capture_diagnostics=diagnostics,
        )

    return AvailabilitySearchNotDispatchedError(
        f"No post-search availability request observed within {timeout_ms}ms",
        form_state=form_state,
        path=AVAILABILITY_PAYLOAD_PATH,
    )
