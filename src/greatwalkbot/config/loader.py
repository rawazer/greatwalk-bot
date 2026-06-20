"""Load watch configuration from YAML."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from greatwalkbot.config.models import DateRange, TrackWatchConfig, WatchConfig
from greatwalkbot.tracks import resolve_track


def _parse_date(value: Any, field: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} must be YYYY-MM-DD, got {value!r}") from exc
    raise ValueError(f"{field} must be a date string, got {type(value).__name__}")


def _parse_range(raw: Any, context: str) -> DateRange:
    if not isinstance(raw, dict):
        raise ValueError(f"{context} must be a mapping with from/to")
    if "from" not in raw or "to" not in raw:
        raise ValueError(f"{context} must include from and to")
    return DateRange(
        _parse_date(raw["from"], f"{context}.from"),
        _parse_date(raw["to"], f"{context}.to"),
    )


def _parse_ranges(raw: Any, context: str) -> tuple[DateRange, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{context} must be a list")
    return tuple(_parse_range(item, f"{context}[{i}]") for i, item in enumerate(raw))


def _parse_track(raw: Any, index: int) -> TrackWatchConfig:
    context = f"tracks[{index}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{context} must be a mapping")
    slug = raw.get("track") or raw.get("slug") or raw.get("name")
    if not slug or not isinstance(slug, str):
        raise ValueError(f"{context} must include a track slug (track/slug/name)")

    preferred = _parse_ranges(raw.get("preferred"), f"{context}.preferred")
    acceptable = _parse_ranges(raw.get("acceptable"), f"{context}.acceptable")
    if not acceptable:
        raise ValueError(f"{context} must define at least one acceptable date range")
    if not preferred:
        raise ValueError(f"{context} must define at least one preferred date range")

    for i, pref in enumerate(preferred):
        if not any(
            pref.from_date >= acc.from_date and pref.to_date <= acc.to_date for acc in acceptable
        ):
            raise ValueError(
                f"{context}.preferred[{i}] must fall within an acceptable date range"
            )

    resolved = resolve_track(slug)
    return TrackWatchConfig(
        slug=resolved.slug,
        preferred=preferred,
        acceptable=acceptable,
    )


def load_watch_config(path: str | Path) -> WatchConfig:
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, dict):
        raise ValueError("Config root must be a mapping")

    party_size = raw.get("party_size")
    if not isinstance(party_size, int):
        raise ValueError("party_size must be an integer")

    interval = raw.get("polling_interval") or raw.get("polling_interval_seconds")
    if not isinstance(interval, int):
        raise ValueError("polling_interval must be an integer (seconds)")

    tracks_raw = raw.get("tracks")
    if not isinstance(tracks_raw, list) or not tracks_raw:
        raise ValueError("tracks must be a non-empty list")

    source = raw.get("source", "playwright")
    if source not in ("playwright", "http"):
        raise ValueError("source must be playwright or http")

    tracks = tuple(_parse_track(item, i) for i, item in enumerate(tracks_raw))

    return WatchConfig(
        party_size=party_size,
        polling_interval_seconds=interval,
        tracks=tracks,
        source=source,
    )
