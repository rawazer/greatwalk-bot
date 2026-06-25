"""CLI for GreatWalkBot."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from greatwalkbot.config import load_watch_config
from greatwalkbot.display import format_availability_table
from greatwalkbot.infra.shutdown import ShutdownController
from greatwalkbot.logging_config import configure_logging
from greatwalkbot.monitoring.dedupe import SqliteSeenAvailabilityStore
from greatwalkbot.monitoring.metrics import RuntimeMetrics
from greatwalkbot.monitoring.watcher import Watcher
from greatwalkbot.notifications.errors import TelegramDeliveryError
from greatwalkbot.notifications.factory import build_notifiers, send_test_notifications
from greatwalkbot.sources.http import HttpAvailabilitySource
from greatwalkbot.sources.playwright import PlaywrightAvailabilitySource
from greatwalkbot.sources.protocol import AvailabilitySource
from greatwalkbot.sources.session_manager import SessionManager
from greatwalkbot.monitoring.trip_fit import check_trip_feasible_in_principle
from greatwalkbot.plan_check import format_plan_check
from greatwalkbot.bookings import format_bookings
from greatwalkbot.debug_search import run_debug_search
from greatwalkbot.preflight import format_preflight_report, run_preflight
from greatwalkbot.tracks import resolve_track

logger = logging.getLogger(__name__)

DEFAULT_LOG_DIR = Path("logs")
DEFAULT_STATUS_FILE = DEFAULT_LOG_DIR / "status.json"
DEFAULT_SEEN_DB = Path("data") / "seen.db"


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date {value!r}; use YYYY-MM-DD") from exc


def _build_http_source() -> HttpAvailabilitySource:
    return HttpAvailabilitySource()


def _build_playwright_source(
    *,
    headed: bool,
    session_manager: SessionManager | None = None,
    metrics: RuntimeMetrics | None = None,
) -> PlaywrightAvailabilitySource:
    return PlaywrightAvailabilitySource(
        headless=not headed,
        session_manager=session_manager,
        metrics=metrics,
    )


def _cmd_check(args: argparse.Namespace) -> int:
    try:
        track = resolve_track(args.track)
        from_date = args.from_date
        to_date = args.to_date
        if to_date < from_date:
            logger.error("--to must be on or after --from")
            return 1

        if args.source == "playwright":
            source = _build_playwright_source(headed=args.headed)
        else:
            source = _build_http_source()

        snapshot = source.fetch_track_availability(track, from_date, to_date)
        print(format_availability_table(snapshot))
        return 0
    except (ValueError, RuntimeError) as exc:
        logger.error("Error: %s", exc)
        return 1


def _cmd_watch(args: argparse.Namespace) -> int:
    seen_store: SqliteSeenAvailabilityStore | None = None
    session_manager: SessionManager | None = None

    try:
        configure_logging(DEFAULT_LOG_DIR)
        plan = load_watch_config(args.config)
        source_name = args.source or plan.source
        shutdown = ShutdownController()

        metrics = RuntimeMetrics(
            status_path=DEFAULT_STATUS_FILE,
            trip_name=plan.trip.name,
        )
        metrics.flush()

        seen_store = SqliteSeenAvailabilityStore(DEFAULT_SEEN_DB)

        if source_name == "playwright":
            session_manager = SessionManager(headless=not args.headed)
            session_manager.start()
            source: AvailabilitySource = _build_playwright_source(
                headed=args.headed,
                session_manager=session_manager,
                metrics=metrics,
            )
        else:
            source = _build_http_source()

        watcher = Watcher(
            plan,
            source,
            build_notifiers(plan, metrics=metrics),
            seen_store=seen_store,
            metrics=metrics,
            shutdown=shutdown,
        )

        if args.once:
            watcher.run_once()
            return 0

        watcher.run_forever()
        return 0
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        logger.error("Error: %s", exc)
        return 1
    finally:
        if session_manager is not None:
            session_manager.close()
        if seen_store is not None:
            seen_store.close()
        logging.shutdown()


def _cmd_status(args: argparse.Namespace) -> int:
    status_path = Path(args.status_file)
    snapshot = RuntimeMetrics.load(status_path)
    if snapshot is None:
        print(
            f"No status file found at {status_path}. Is the watcher running?",
            file=sys.stderr,
        )
        return 1

    print(f"Trip: {snapshot.trip_name or 'unknown'}")
    print(f"State: {snapshot.state}")
    print(f"Started: {snapshot.started_at}")
    print(f"Polls completed: {snapshot.polls_completed}")
    print(f"Successful polls: {snapshot.successful_polls}")
    print(f"Failed polls: {snapshot.failed_polls}")
    print(f"Browser restarts: {snapshot.browser_restarts}")
    print(f"Average poll duration: {snapshot.average_poll_duration_seconds:.1f}s")
    print(f"Last poll: {snapshot.last_poll_at or 'never'}")
    print(f"Last successful poll: {snapshot.last_successful_poll_at or 'never'}")
    if snapshot.last_error is not None:
        print(
            f"Last error: {snapshot.last_error.message} "
            f"(track={snapshot.last_error.track_slug or 'unknown'}, "
            f"at={snapshot.last_error.at})"
        )
    print(f"Last notification attempt: {snapshot.last_notification_attempt_at or 'never'}")
    print(
        f"Last successful notification: {snapshot.last_successful_notification_at or 'never'}"
    )
    if snapshot.last_notification_error is not None:
        print(
            f"Last notification error: {snapshot.last_notification_error.message} "
            f"(at={snapshot.last_notification_error.at})"
        )
    return 0


def _cmd_plan_check(args: argparse.Namespace) -> int:
    try:
        configure_logging(None)
        plan = load_watch_config(args.config)
        report = check_trip_feasible_in_principle(plan.trip, plan.trip_fit)
        print(format_plan_check(plan))
        if not report.feasible:
            logger.error(
                "Configured trip is not feasible in principle: %s",
                ", ".join(report.reasons),
            )
            return 1
        return 0
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        logger.error("Error: %s", exc)
        return 1


def _cmd_bookings(args: argparse.Namespace) -> int:
    try:
        configure_logging(None)
        plan = load_watch_config(args.config)
        print(format_bookings(plan))
        return 0
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        logger.error("Error: %s", exc)
        return 1


def _cmd_explain_availability(args: argparse.Namespace) -> int:
    try:
        configure_logging(None)
        plan = load_watch_config(args.config)
        track = resolve_track(args.track)
        preference = next(
            (pref for pref in plan.trip.tracks if pref.slug == track.slug),
            None,
        )
        if preference is None:
            logger.error("Track %r is not configured in %s", args.track, args.config)
            return 1

        if args.source == "playwright":
            source = _build_playwright_source(headed=args.headed)
        else:
            source = _build_http_source()

        target = args.date
        snapshot = source.fetch_track_availability(track, target, target)
        if snapshot.facility_index is None:
            logger.error("Fetched snapshot has no facility index for validation")
            return 1

        from greatwalkbot.monitoring.itinerary_validation import validate_complete_itineraries
        from greatwalkbot.explain_availability import format_explain_availability

        results = validate_complete_itineraries(
            index=snapshot.facility_index,
            snapshot=snapshot,
            preference=preference,
            start_date=target,
            party=plan.trip.party,
        )
        print(format_explain_availability(results))
        return 0
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        logger.error("Error: %s", exc)
        return 1


def _cmd_debug_search(args: argparse.Namespace) -> int:
    try:
        configure_logging(None)
        plan = load_watch_config(args.config)
        track = resolve_track(args.track)
        report = run_debug_search(
            plan,
            track,
            start_date=args.date,
            nights_override=args.nights,
            headed=args.headed,
        )
        print(report.to_text())
        return 0 if report.result == "success" else 1
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        logger.error("Error: %s", exc)
        return 1


def _cmd_preflight(args: argparse.Namespace) -> int:
    session_manager: SessionManager | None = None

    try:
        configure_logging(None)
        plan = load_watch_config(args.config)
        source_name = args.source or plan.source

        if source_name == "playwright":
            session_manager = SessionManager(headless=not args.headed)
            session_manager.start()
            source: AvailabilitySource = _build_playwright_source(
                headed=args.headed,
                session_manager=session_manager,
            )
        else:
            source = _build_http_source()

        report = run_preflight(
            plan,
            source,
            send_test_notification=args.send_test_notification,
        )
        print(format_preflight_report(report, trip_name=plan.trip.name))
        return 0 if report.ready else 1
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        logger.error("Error: %s", exc)
        return 1
    finally:
        if session_manager is not None:
            session_manager.close()


def _cmd_notify_test(args: argparse.Namespace) -> int:
    try:
        configure_logging(None)
        plan = load_watch_config(args.config)
        send_test_notifications(plan)
        print("Test notification(s) sent successfully.")
        return 0
    except TelegramDeliveryError as exc:
        logger.error("Telegram delivery failed: %s", exc)
        return 1
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        logger.error("Error: %s", exc)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gwbot", description="DOC Great Walk availability checker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Check availability for a track and date range")
    check.add_argument("--track", required=True, help="Track slug (e.g. milford, routeburn)")
    check.add_argument("--from", dest="from_date", type=_parse_date, required=True, help="Start date")
    check.add_argument("--to", dest="to_date", type=_parse_date, required=True, help="End date (inclusive)")
    check.add_argument(
        "--source",
        choices=("playwright", "http"),
        default="playwright",
        help="Data source backend (default: playwright)",
    )
    check.add_argument(
        "--headed",
        action="store_true",
        help="Show browser window (may help if AWS WAF blocks headless traffic)",
    )
    check.set_defaults(func=_cmd_check)

    watch = subparsers.add_parser("watch", help="Monitor availability using a YAML config file")
    watch.add_argument("config", type=Path, help="Path to watch configuration YAML")
    watch.add_argument(
        "--source",
        choices=("playwright", "http"),
        default=None,
        help="Override data source from config",
    )
    watch.add_argument(
        "--headed",
        action="store_true",
        help="Show browser window (may help if AWS WAF blocks headless traffic)",
    )
    watch.add_argument(
        "--once",
        action="store_true",
        help="Run a single check cycle then exit",
    )
    watch.set_defaults(func=_cmd_watch)

    status = subparsers.add_parser("status", help="Show watcher runtime metrics")
    status.add_argument(
        "--status-file",
        type=Path,
        default=DEFAULT_STATUS_FILE,
        help=f"Path to status JSON (default: {DEFAULT_STATUS_FILE})",
    )
    status.set_defaults(func=_cmd_status)

    notify_test = subparsers.add_parser(
        "notify-test",
        help="Send test notification(s) without contacting DOC",
    )
    notify_test.add_argument("config", type=Path, help="Path to watch configuration YAML")
    notify_test.set_defaults(func=_cmd_notify_test)

    plan_check = subparsers.add_parser(
        "plan-check",
        help="Inspect trip-fit feasibility without contacting DOC",
    )
    plan_check.add_argument("config", type=Path, help="Path to watch configuration YAML")
    plan_check.set_defaults(func=_cmd_plan_check)

    bookings = subparsers.add_parser(
        "bookings",
        help="List confirmed bookings without contacting DOC",
    )
    bookings.add_argument("config", type=Path, help="Path to watch configuration YAML")
    bookings.set_defaults(func=_cmd_bookings)

    explain = subparsers.add_parser(
        "explain-availability",
        help="Diagnose complete-itinerary validation for one start date",
    )
    explain.add_argument("config", type=Path, help="Path to watch configuration YAML")
    explain.add_argument("--track", required=True, help="Track slug (e.g. milford)")
    explain.add_argument("--date", type=_parse_date, required=True, help="Candidate start date")
    explain.add_argument(
        "--source",
        choices=("playwright", "http"),
        default="playwright",
        help="Data source backend (default: playwright)",
    )
    explain.add_argument(
        "--headed",
        action="store_true",
        help="Show browser window (may help if AWS WAF blocks headless traffic)",
    )
    explain.set_defaults(func=_cmd_explain_availability)

    debug_search = subparsers.add_parser(
        "debug-search",
        help="Single read-only Great Walk search attempt with sanitized diagnostics",
    )
    debug_search.add_argument("config", type=Path, help="Path to watch configuration YAML")
    debug_search.add_argument("--track", required=True, help="Track slug (e.g. routeburn)")
    debug_search.add_argument("--date", type=_parse_date, required=True, help="Candidate start date")
    debug_search.add_argument(
        "--nights",
        type=int,
        default=None,
        help="Override itinerary nights for the search form (default: registry duration)",
    )
    debug_search.add_argument(
        "--headed",
        action="store_true",
        help="Show browser window for troubleshooting",
    )
    debug_search.set_defaults(func=_cmd_debug_search)

    preflight = subparsers.add_parser(
        "preflight",
        help="Validate config, feasibility, notifications, and read-only DOC fetch",
    )
    preflight.add_argument("config", type=Path, help="Path to watch configuration YAML")
    preflight.add_argument(
        "--send-test-notification",
        action="store_true",
        help="Send test notification(s) through configured channels",
    )
    preflight.add_argument(
        "--source",
        choices=("playwright", "http"),
        default=None,
        help="Override data source from config",
    )
    preflight.add_argument(
        "--headed",
        action="store_true",
        help="Show browser window (may help if AWS WAF blocks headless traffic)",
    )
    preflight.set_defaults(func=_cmd_preflight)

    args = parser.parse_args(argv)
    if args.command in (
        "check",
        "notify-test",
        "plan-check",
        "bookings",
        "explain-availability",
        "debug-search",
        "preflight",
    ):
        configure_logging(None)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
