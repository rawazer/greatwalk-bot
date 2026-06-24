"""Preflight readiness checks before deploying the watcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from greatwalkbot.domain.plan import TripPlan
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.monitoring.trip_fit import check_trip_feasible_in_principle
from greatwalkbot.notifications.factory import build_notifiers, send_test_notifications
from greatwalkbot.notifications.errors import TelegramDeliveryError
from greatwalkbot.sources.protocol import AvailabilitySource
from greatwalkbot.track_itineraries import has_itinerary_definition
from greatwalkbot.tracks import resolve_track

ResolveTrackFn = Callable[[str], object]
FetchTrackFn = Callable[[object, object, object], object]


@dataclass(frozen=True)
class TrackPreflightResult:
    track_slug: str
    track_name: str
    status: str  # ok | skipped | failed
    fetch_succeeded: bool
    validation_capable: bool
    complete_itinerary_only: bool
    message: str


@dataclass(frozen=True)
class PreflightReport:
    config_valid: bool
    trip_feasible: bool
    feasibility_reasons: tuple[str, ...]
    telegram_enabled: bool
    telegram_configured: bool
    telegram_test_requested: bool
    telegram_test_succeeded: bool | None
    telegram_message: str
    track_results: tuple[TrackPreflightResult, ...]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.errors


def _telegram_status(plan: TripPlan) -> tuple[bool, bool, str]:
    telegram = plan.notifications.telegram
    if not telegram.enabled:
        return False, False, "Telegram disabled in configuration"

    from greatwalkbot.notifications.factory import resolve_telegram_credentials

    try:
        resolve_telegram_credentials(telegram)
    except ValueError as exc:
        return True, False, f"Telegram enabled but not configured: {exc}"

    return True, True, "Telegram credentials present in environment"


def _validation_capable(preference: TrackPreference, *, has_facility_index: bool) -> bool:
    if not has_facility_index:
        return False
    if preference.complete_itinerary_only:
        return has_itinerary_definition(preference.slug)
    return False


def run_preflight(
    plan: TripPlan,
    source: AvailabilitySource,
    *,
    resolve_track_fn: ResolveTrackFn = resolve_track,
    send_test_notification: bool = False,
) -> PreflightReport:
    """Run read-only readiness checks. Does not touch dedupe or send availability alerts."""
    warnings: list[str] = []
    errors: list[str] = []

    feasibility = check_trip_feasible_in_principle(plan.trip, plan.trip_fit)
    if not feasibility.feasible:
        errors.append(
            "Trip plan is not feasible in principle: "
            + ", ".join(feasibility.reasons)
        )

    telegram_enabled, telegram_configured, telegram_message = _telegram_status(plan)
    telegram_test_succeeded: bool | None = None

    if telegram_enabled and not telegram_configured:
        errors.append(telegram_message)

    try:
        build_notifiers(plan)
    except ValueError as exc:
        errors.append(f"Notifier initialization failed: {exc}")

    if send_test_notification:
        if not telegram_enabled and not plan.notifications.console:
            errors.append(
                "Cannot send test notification: no notification channels enabled"
            )
        else:
            try:
                send_test_notifications(plan)
                telegram_test_succeeded = True
                telegram_message = (
                    f"{telegram_message}; test notification sent"
                    if telegram_enabled
                    else "Console test notification sent"
                )
            except TelegramDeliveryError as exc:
                telegram_test_succeeded = False
                errors.append(f"Test notification failed: {exc}")
            except ValueError as exc:
                telegram_test_succeeded = False
                errors.append(f"Test notification failed: {exc}")

    track_results: list[TrackPreflightResult] = []
    trip = plan.trip

    for preference in trip.tracks:
        if preference.confirmed_booking is not None:
            booking = preference.confirmed_booking
            track = resolve_track_fn(preference.slug)
            track_results.append(
                TrackPreflightResult(
                    track_slug=preference.slug,
                    track_name=track.name,
                    status="skipped",
                    fetch_succeeded=True,
                    validation_capable=False,
                    complete_itinerary_only=preference.complete_itinerary_only,
                    message=(
                        f"Skipped (confirmed booking "
                        f"{booking.start_date.isoformat()}..{booking.end_date.isoformat()})"
                    ),
                )
            )
            continue

        track = resolve_track_fn(preference.slug)
        bounds = preference.query_bounds(trip.travel_window)

        try:
            snapshot = source.fetch_track_availability(
                track,
                bounds.start,
                bounds.end,
            )
            has_index = snapshot.facility_index is not None
            capable = _validation_capable(
                preference,
                has_facility_index=has_index,
            )
            day_count = len(snapshot.days)
            if capable:
                detail = (
                    f"Fetch OK ({day_count} day(s)); "
                    "complete-itinerary validation supported"
                )
            elif preference.complete_itinerary_only:
                detail = (
                    f"Fetch OK ({day_count} day(s)); "
                    "complete-itinerary validation not available from response"
                )
                warnings.append(
                    f"{preference.slug}: fetch succeeded but validation data insufficient"
                )
            else:
                detail = f"Fetch OK ({day_count} day(s)); day-level matching only"

            warnings.append(
                f"{preference.slug}: finding no matching availability during preflight is normal"
            )
            track_results.append(
                TrackPreflightResult(
                    track_slug=preference.slug,
                    track_name=track.name,
                    status="ok",
                    fetch_succeeded=True,
                    validation_capable=capable,
                    complete_itinerary_only=preference.complete_itinerary_only,
                    message=detail,
                )
            )
        except Exception as exc:
            errors.append(f"{preference.slug}: fetch failed: {exc}")
            track_results.append(
                TrackPreflightResult(
                    track_slug=preference.slug,
                    track_name=getattr(track, "name", preference.slug),
                    status="failed",
                    fetch_succeeded=False,
                    validation_capable=False,
                    complete_itinerary_only=preference.complete_itinerary_only,
                    message=str(exc),
                )
            )

    return PreflightReport(
        config_valid=True,
        trip_feasible=feasibility.feasible,
        feasibility_reasons=feasibility.reasons,
        telegram_enabled=telegram_enabled,
        telegram_configured=telegram_configured,
        telegram_test_requested=send_test_notification,
        telegram_test_succeeded=telegram_test_succeeded,
        telegram_message=telegram_message,
        track_results=tuple(track_results),
        warnings=tuple(dict.fromkeys(warnings)),
        errors=tuple(errors),
    )


def format_preflight_report(report: PreflightReport, *, trip_name: str) -> str:
    lines = [
        f"Preflight: {trip_name}",
        "",
        f"Config valid: {'YES' if report.config_valid else 'NO'}",
        (
            "Trip plan feasible: "
            + ("YES" if report.trip_feasible else "NO — " + ", ".join(report.feasibility_reasons))
        ),
        "",
        "Notifications:",
    ]

    if report.telegram_enabled:
        lines.append(f"  Telegram: enabled, configured={'YES' if report.telegram_configured else 'NO'}")
        lines.append(f"  {report.telegram_message}")
        if report.telegram_test_requested:
            if report.telegram_test_succeeded is True:
                lines.append("  Test notification: sent")
            elif report.telegram_test_succeeded is False:
                lines.append("  Test notification: FAILED")
    else:
        lines.append("  Telegram: disabled")

    lines.append("")
    lines.append("Track availability fetch:")
    for result in report.track_results:
        symbol = {"ok": "OK", "skipped": "SKIP", "failed": "FAIL"}[result.status]
        lines.append(f"  [{symbol}] {result.track_name} ({result.track_slug})")
        lines.append(f"        {result.message}")

    if report.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in report.warnings:
            lines.append(f"  - {warning}")

    if report.errors:
        lines.append("")
        lines.append("Errors:")
        for error in report.errors:
            lines.append(f"  - {error}")

    lines.append("")
    if report.ready:
        lines.append("Overall: READY")
    else:
        lines.append("Overall: NOT READY")

    return "\n".join(lines)
