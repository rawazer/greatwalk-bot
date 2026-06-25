"""Error types for retry and recovery logic."""

from __future__ import annotations

from pathlib import Path


class RetryableError(Exception):
    """Transient failure that may succeed on retry."""


class SessionError(RetryableError):
    """Browser or Playwright session is unhealthy."""


class FetchError(RetryableError):
    """Availability fetch failed but may succeed on retry."""


class NavigationError(RetryableError):
    """DOC page navigation timed out or failed."""

    def __init__(
        self,
        message: str,
        *,
        stage: str | None = None,
        timeout_ms: int | None = None,
        wait_until: str | None = None,
        navigation_state: dict | None = None,
        timing: dict | None = None,
        navigation_recovered_after_timeout: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.timeout_ms = timeout_ms
        self.wait_until = wait_until
        self.navigation_state = navigation_state
        self.timing = timing
        self.navigation_recovered_after_timeout = navigation_recovered_after_timeout


class UIReadinessError(RetryableError):
    """Great Walk UI did not become ready within the bounded wait."""

    def __init__(
        self,
        message: str,
        *,
        stage: str | None = None,
        timeout_ms: int | None = None,
        navigation_state: dict | None = None,
        timing: dict | None = None,
        shell_navigation_timed_out: bool = False,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.timeout_ms = timeout_ms
        self.navigation_state = navigation_state
        self.timing = timing
        self.shell_navigation_timed_out = shell_navigation_timed_out


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


class GreatWalkControlNotClickableError(RetryableError):
    """Desktop control is visible but not receiving pointer events at its center."""

    def __init__(
        self,
        message: str,
        *,
        control: str | None = None,
        click_diagnostics: dict | None = None,
        root_change: dict | None = None,
        form_state: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.control = control
        self.click_diagnostics = click_diagnostics
        self.root_change = root_change
        self.form_state = form_state


class GreatWalkDesktopRootError(RetryableError):
    """Desktop Great Walk search widget root is missing or ambiguous."""

    def __init__(self, message: str, *, root_count: int | None = None) -> None:
        super().__init__(message)
        self.root_count = root_count


class GreatWalkDateControlDiscoveryIncompleteError(RetryableError):
    """Desktop React date-picker binding is not established from live evidence."""

    def __init__(
        self,
        message: str,
        *,
        date_iso: str | None = None,
        diagnostic_path: str | Path | None = None,
        form_state: dict | None = None,
        calendar_diagnostics: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.date_iso = date_iso
        self.diagnostic_path = str(diagnostic_path) if diagnostic_path else None
        self.form_state = form_state
        self.calendar_diagnostics = calendar_diagnostics


class GreatWalkDateUnavailableError(RetryableError):
    """Requested start date is present in the picker but marked not available."""

    def __init__(
        self,
        message: str,
        *,
        date_iso: str | None = None,
        aria_label: str | None = None,
        form_state: dict | None = None,
        calendar_diagnostics: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.date_iso = date_iso
        self.aria_label = aria_label
        self.form_state = form_state
        self.calendar_diagnostics = calendar_diagnostics


class GreatWalkDatePickerError(RetryableError):
    """Desktop React date-picker navigation or selection failed."""

    def __init__(
        self,
        message: str,
        *,
        date_iso: str | None = None,
        form_state: dict | None = None,
        calendar_diagnostics: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.date_iso = date_iso
        self.form_state = form_state
        self.calendar_diagnostics = calendar_diagnostics


class GreatWalkControlDiscoveryIncompleteError(RetryableError):
    """Live DOM inspection did not identify all required Great Walk controls."""

    def __init__(
        self,
        message: str,
        *,
        diagnostic_path: str | Path | None = None,
        discovery_report: dict | None = None,
        assessment: object | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic_path = str(diagnostic_path) if diagnostic_path else None
        self.discovery_report = discovery_report
        self.assessment = assessment

