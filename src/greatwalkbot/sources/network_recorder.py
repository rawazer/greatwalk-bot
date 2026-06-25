"""Sanitized Tyler RDR network timeline for DOC SPA diagnostics."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

# Paths that may participate in Great Walk availability discovery.
GREAT_WALK_CANDIDATE_PATHS: tuple[str, ...] = (
    "search/greatwalkplacefacility",
    "search/getgreatwalksearchdata",
    "search/getgreatwalkfacilityinformation",
    "search/grid",
    "fd/availability/getbyunit",
)

AVAILABILITY_PAYLOAD_PATH = "search/greatwalkplacefacility"
SELECTION_METADATA_PATH = "search/getgreatwalksearchdata"

_WAF_URL_MARKERS = ("awswaf", "captcha", "challenge")
_WAF_CONTENT_MARKERS = ("x-amzn-waf-action", "captcha", "aws-waf")


@dataclass(frozen=True)
class SanitizedNetworkEvent:
    order: int
    phase: str  # request | response
    method: str
    path: str
    status: int | None
    content_type: str | None
    candidate_match: bool
    availability_match: bool
    selection_metadata_match: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "phase": self.phase,
            "method": self.method,
            "path": self.path,
            "status": self.status,
            "content_type": self.content_type,
            "candidate_match": self.candidate_match,
            "availability_match": self.availability_match,
            "selection_metadata_match": self.selection_metadata_match,
        }


def sanitize_url_path(url: str) -> str:
    """Return path only with numeric/query segments redacted."""
    parsed = urlparse(url)
    path = parsed.path or url
    path = re.sub(r"/\d+", "/{id}", path)
    if "?" in url:
        return f"{path}?…"
    return path


def path_matches_candidate(path: str) -> bool:
    normalized = path.lower()
    return any(marker in normalized for marker in GREAT_WALK_CANDIDATE_PATHS)


def path_is_availability(path: str) -> bool:
    return AVAILABILITY_PAYLOAD_PATH in path.lower()


def path_is_selection_metadata(path: str, *, place_id: int | None = None) -> bool:
    if SELECTION_METADATA_PATH not in path.lower():
        return False
    if place_id is None:
        return True
    return f"placeid/{place_id}" in path.lower().replace("-", "")


def response_body_is_availability_payload(data: Any) -> bool:
    return isinstance(data, dict) and "GreatWalkFacilityData" in data


class NetworkRecorder:
    """Persistent sanitized request/response log for the active page."""

    MAX_EVENTS = 80

    def __init__(self) -> None:
        self._events: list[SanitizedNetworkEvent] = []
        self._order = 0
        self._waf_signals: list[str] = []
        self._active_place_id: int | None = None

    def begin_cycle(self, *, place_id: int | None = None) -> None:
        self._events.clear()
        self._order = 0
        self._waf_signals.clear()
        self._active_place_id = place_id

    @property
    def events(self) -> tuple[SanitizedNetworkEvent, ...]:
        return tuple(self._events)

    @property
    def waf_signals(self) -> tuple[str, ...]:
        return tuple(self._waf_signals)

    def attach(self, page: Any) -> None:
        page.on("request", self._on_request)
        page.on("response", self._on_response)

    def _append(
        self,
        *,
        phase: str,
        method: str,
        path: str,
        status: int | None,
        content_type: str | None,
        selection_metadata_match: bool | None = None,
    ) -> None:
        self._order += 1
        candidate = path_matches_candidate(path)
        if selection_metadata_match is None:
            selection_metadata_match = path_is_selection_metadata(
                path, place_id=self._active_place_id
            )
        self._events.append(
            SanitizedNetworkEvent(
                order=self._order,
                phase=phase,
                method=method,
                path=path,
                status=status,
                content_type=content_type,
                candidate_match=candidate,
                availability_match=path_is_availability(path),
                selection_metadata_match=selection_metadata_match,
            )
        )
        if len(self._events) > self.MAX_EVENTS:
            del self._events[: len(self._events) - self.MAX_EVENTS]

    def _on_request(self, request: Any) -> None:
        url = str(getattr(request, "url", ""))
        if "tylerapp.com" not in url and "recreation-management" not in url:
            return
        self._append(
            phase="request",
            method=str(getattr(request, "method", "GET")),
            path=sanitize_url_path(url),
            status=None,
            content_type=None,
        )

    def _on_response(self, response: Any) -> None:
        url = str(getattr(response, "url", ""))
        if "tylerapp.com" not in url and "recreation-management" not in url:
            return
        headers = getattr(response, "headers", {}) or {}
        content_type = str(headers.get("content-type", ""))[:120] or None
        sanitized_path = sanitize_url_path(url)
        self._append(
            phase="response",
            method=str(getattr(response.request, "method", "?")),
            path=sanitized_path,
            status=int(getattr(response, "status", 0) or 0),
            content_type=content_type,
            selection_metadata_match=path_is_selection_metadata(
                url.lower(), place_id=self._active_place_id
            ),
        )
        lowered_url = url.lower()
        for marker in _WAF_URL_MARKERS:
            if marker in lowered_url:
                self._waf_signals.append(f"url:{marker}")
        for key, value in headers.items():
            joined = f"{key}:{value}".lower()
            for marker in _WAF_CONTENT_MARKERS:
                if marker in joined:
                    self._waf_signals.append(f"header:{marker}")

    def saw_selection_metadata(self, place_id: int) -> bool:
        if self._active_place_id is not None and self._active_place_id != place_id:
            return False
        return any(
            event.phase == "response"
            and event.selection_metadata_match
            and event.status == 200
            for event in self._events
        )

    def saw_availability_request(self) -> bool:
        return any(
            event.phase == "request" and event.availability_match for event in self._events
        )

    def saw_availability_response(self) -> bool:
        return any(
            event.phase == "response" and event.availability_match
            for event in self._events
        )

    def failed_availability_response(self) -> SanitizedNetworkEvent | None:
        for event in reversed(self._events):
            if event.phase == "response" and event.availability_match:
                if event.status is not None and event.status != 200:
                    return event
        return None

    def timeline_dicts(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self._events]
