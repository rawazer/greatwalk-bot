"""Error types for retry and recovery logic."""

from __future__ import annotations


class RetryableError(Exception):
    """Transient failure that may succeed on retry."""


class SessionError(RetryableError):
    """Browser or Playwright session is unhealthy."""


class FetchError(RetryableError):
    """Availability fetch failed but may succeed on retry."""


class NavigationError(RetryableError):
    """DOC page navigation timed out or failed."""


class UIReadinessError(RetryableError):
    """Great Walk UI did not become ready within the bounded wait."""


class TrackSelectorError(RetryableError):
    """Expected track dropdown item was not found after bounded recovery."""

    def __init__(
        self,
        message: str,
        *,
        track_slug: str | None = None,
        element_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.track_slug = track_slug
        self.element_id = element_id


class TrackSelectionNotCommittedError(RetryableError):
    """Track option was clicked but SPA state did not commit the selection."""

    def __init__(self, message: str, *, place_id: int | None = None) -> None:
        super().__init__(message)
        self.place_id = place_id


class AvailabilityRequestNotObservedError(RetryableError):
    """Expected availability request never appeared on the network timeline."""

    def __init__(self, message: str, *, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path


class AvailabilityRequestFailedError(RetryableError):
    """Availability request was observed but returned a non-success response."""

    def __init__(self, message: str, *, path: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.path = path
        self.status = status


class WafChallengeSuspectedError(RetryableError):
    """Concrete WAF/challenge indicators were observed."""

    def __init__(self, message: str, *, signals: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.signals = signals


class SearchFormValidationError(RetryableError):
    """Great Walk search form is invalid or Search is not actionable."""

    def __init__(self, message: str, *, form_state: dict | None = None) -> None:
        super().__init__(message)
        self.form_state = form_state


class AvailabilitySearchNotDispatchedError(RetryableError):
    """Selection committed but Search did not dispatch an availability request."""

    def __init__(
        self,
        message: str,
        *,
        form_state: dict | None = None,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.form_state = form_state
        self.path = path


class GreatWalkFormNotReadyError(RetryableError):
    """Active Great Walk form did not finish loading within the bounded wait."""

    def __init__(self, message: str, *, form_state: dict | None = None) -> None:
        super().__init__(message)
        self.form_state = form_state


class GreatWalkControlNotFoundError(RetryableError):
    """Required control was not found within the active Great Walk form root."""

    def __init__(
        self,
        message: str,
        *,
        control: str | None = None,
        form_state: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.control = control
        self.form_state = form_state

