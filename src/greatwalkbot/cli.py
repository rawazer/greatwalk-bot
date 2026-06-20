"""CLI for GreatWalkBot."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from greatwalkbot.config import load_watch_config
from greatwalkbot.display import format_availability_table
from greatwalkbot.monitoring.watcher import Watcher
from greatwalkbot.notifications.console import ConsoleNotifier
from greatwalkbot.sources.http import HttpAvailabilitySource
from greatwalkbot.sources.playwright import PlaywrightAvailabilitySource
from greatwalkbot.sources.protocol import AvailabilitySource
from greatwalkbot.tracks import resolve_track


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date {value!r}; use YYYY-MM-DD") from exc


def _build_source(name: str, headed: bool) -> AvailabilitySource:
    if name == "playwright":
        return PlaywrightAvailabilitySource(headless=not headed)
    if name == "http":
        return HttpAvailabilitySource()
    raise ValueError(f"Unknown source {name!r}")


def _cmd_check(args: argparse.Namespace) -> int:
    try:
        track = resolve_track(args.track)
        from_date = args.from_date
        to_date = args.to_date
        if to_date < from_date:
            print("--to must be on or after --from", file=sys.stderr)
            return 1

        source = _build_source(args.source, args.headed)
        snapshot = source.fetch_track_availability(track, from_date, to_date)
        print(format_availability_table(snapshot))
        return 0
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_watch(args: argparse.Namespace) -> int:
    try:
        config = load_watch_config(args.config)
        source_name = args.source or config.source
        source = _build_source(source_name, args.headed)
        watcher = Watcher(
            config,
            source,
            ConsoleNotifier(),
        )

        if args.once:
            watcher.run_once()
            return 0

        watcher.run_forever()
        return 0
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
