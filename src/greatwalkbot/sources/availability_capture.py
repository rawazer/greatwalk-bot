"""Match and classify Great Walk availability network responses."""

from __future__ import annotations

from typing import Any, Callable

from greatwalkbot.sources.network_recorder import (
    AVAILABILITY_PAYLOAD_PATH,
    POST_SEARCH_RESPONSE_PATHS,
    NetworkRecorder,
    concrete_waf_signals,
    response_body_is_availability_payload,
)


def post_search_response_predicate(response: Any) -> bool:
    """Match any post-search candidate endpoint (not selection metadata)."""
    url = str(getattr(response, "url", "")).lower()
    if not any(marker in url for marker in POST_SEARCH_RESPONSE_PATHS):
        return False
    if "getgreatwalksearchdata" in url:
        return False
    status = int(getattr(response, "status", 0) or 0)
    if status not in (200, 201):
        return True
    headers = getattr(response, "headers", {}) or {}
    content_type = str(headers.get("content-type", "")).lower()
    return "json" in content_type


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


def parse_post_search_response(response: Any) -> tuple[dict | None, str]:
    """Parse response body; return (payload, sanitized_path_marker)."""
    from greatwalkbot.sources.network_recorder import sanitize_url_path

    path = sanitize_url_path(str(getattr(response, "url", "")))
    marker = next(
        (m for m in POST_SEARCH_RESPONSE_PATHS if m in path.lower()),
        path,
    )
    try:
        data = response.json()
    except Exception:
        return None, marker
    if response_body_is_availability_payload(data):
        return data, marker
    return None, marker


def wait_for_availability_response(
    page: Any,
    *,
    click_search: Callable[[], None],
    timeout_ms: int,
) -> dict:
    """Register expect_response before triggering search (no race with click)."""
    with page.expect_response(post_search_response_predicate, timeout=timeout_ms) as info:
        click_search()
    response = info.value
    payload, marker = parse_post_search_response(response)
    if payload is None:
        from greatwalkbot.infra.errors import AvailabilityRequestFailedError

        raise AvailabilityRequestFailedError(
            f"Post-search response on {marker!r} was not a GreatWalk facility payload "
            f"(status={response.status})",
            path=marker,
            status=response.status,
        )
    return payload


def classify_capture_failure(
    recorder: NetworkRecorder,
    *,
    selection_committed: bool,
    search_submitted: bool,
    place_id: int,
    timeout_ms: int,
    page_html: str | None = None,
    form_state: dict | None = None,
) -> Exception:
    from greatwalkbot.infra.errors import (
        AvailabilityRequestFailedError,
        AvailabilityRequestNotObservedError,
        AvailabilitySearchNotDispatchedError,
        TrackSelectionNotCommittedError,
        WafChallengeSuspectedError,
    )

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
    if failed_post is not None:
        return AvailabilityRequestFailedError(
            f"Post-search request returned HTTP {failed_post.status}",
            path=failed_post.path,
            status=failed_post.status,
        )

    failed = recorder.failed_availability_response()
    if failed is not None:
        return AvailabilityRequestFailedError(
            f"Availability request returned HTTP {failed.status}",
            path=failed.path,
            status=failed.status,
        )

    if recorder.saw_post_search_candidate_response():
        alt = recorder.first_post_search_candidate_response()
        return AvailabilityRequestFailedError(
            "Post-search candidate responded but GreatWalk facility payload was not captured",
            path=alt.path if alt else AVAILABILITY_PAYLOAD_PATH,
            status=alt.status if alt else None,
        )

    if recorder.saw_availability_response():
        return AvailabilityRequestFailedError(
            "Availability endpoint responded but payload was not captured",
            path=AVAILABILITY_PAYLOAD_PATH,
            status=200,
        )

    if recorder.saw_post_search_candidate_request():
        return AvailabilityRequestNotObservedError(
            f"Post-search request was observed but no JSON response arrived within "
            f"{timeout_ms}ms",
            path=AVAILABILITY_PAYLOAD_PATH,
        )

    if search_submitted and recorder.saw_selection_metadata(place_id):
        return AvailabilitySearchNotDispatchedError(
            "Track selection committed but Search did not dispatch an availability request",
            form_state=form_state,
            path=AVAILABILITY_PAYLOAD_PATH,
        )

    if recorder.saw_availability_request():
        return AvailabilityRequestNotObservedError(
            f"Availability request was observed but no JSON response arrived within "
            f"{timeout_ms}ms",
            path=AVAILABILITY_PAYLOAD_PATH,
        )

    return AvailabilitySearchNotDispatchedError(
        f"No post-search availability request observed within {timeout_ms}ms",
        form_state=form_state,
        path=AVAILABILITY_PAYLOAD_PATH,
    )
