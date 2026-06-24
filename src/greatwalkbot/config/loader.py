"""Load trip plan configuration from YAML."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.direction import DirectionPreference
from greatwalkbot.domain.notifications import NotificationConfig, TelegramNotificationConfig
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.plan import RetryConfig, TripPlan
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.domain.trip import Trip
from greatwalkbot.domain.trip_fit import TripFitConfig
from greatwalkbot.notifications.factory import resolve_telegram_credentials
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


def _parse_bound_range(raw: Any, context: str) -> DateRange:
    if not isinstance(raw, dict):
        raise ValueError(f"{context} must be a mapping")
    start_key = "start" if "start" in raw else "from"
    end_key = "end" if "end" in raw else "to"
    if start_key not in raw or end_key not in raw:
        raise ValueError(f"{context} must include start/end (or from/to)")
    return DateRange(
        _parse_date(raw[start_key], f"{context}.{start_key}"),
        _parse_date(raw[end_key], f"{context}.{end_key}"),
    )


def _parse_date_list(raw: Any, context: str) -> tuple[date, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{context} must be a list of dates")
    return tuple(_parse_date(item, f"{context}[{i}]") for i, item in enumerate(raw))


def _parse_legacy_ranges(raw: Any, context: str) -> tuple[DateRange, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{context} must be a non-empty list")
    return tuple(_parse_bound_range(item, f"{context}[{i}]") for i, item in enumerate(raw))


def _union_ranges(ranges: tuple[DateRange, ...]) -> DateRange:
    return DateRange(
        min(r.start for r in ranges),
        max(r.end for r in ranges),
    )


def _parse_track_preference(raw: Any, index: int, travel_window: TravelWindow) -> TrackPreference:
    context = f"tracks[{index}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{context} must be a mapping")

    slug = raw.get("track") or raw.get("slug") or raw.get("name")
    if not slug or not isinstance(slug, str):
        raise ValueError(f"{context} must include a track slug")

    if "preferred" in raw or "acceptable" in raw:
        return _legacy_track_to_preference(raw, index, travel_window)

    acceptable = _parse_bound_range(
        raw.get("acceptable_start_range"),
        f"{context}.acceptable_start_range",
    )
    preferred_dates = _parse_date_list(
        raw.get("preferred_start_dates"),
        f"{context}.preferred_start_dates",
    )
    preferred_range_raw = raw.get("preferred_start_range")
    preferred_range = (
        _parse_bound_range(preferred_range_raw, f"{context}.preferred_start_range")
        if preferred_range_raw is not None
        else None
    )

    direction_raw = raw.get("direction", "either")
    direction = (
        DirectionPreference.parse(direction_raw)
        if isinstance(direction_raw, str)
        else DirectionPreference.EITHER
    )

    priority = raw.get("priority", 50)
    if not isinstance(priority, int):
        raise ValueError(f"{context}.priority must be an integer")

    complete = raw.get("complete_itinerary_only", False)
    if not isinstance(complete, bool):
        raise ValueError(f"{context}.complete_itinerary_only must be a boolean")

    resolved = resolve_track(slug)
    preference = TrackPreference(
        slug=resolved.slug,
        acceptable_start_range=acceptable,
        priority=priority,
        direction=direction,
        complete_itinerary_only=complete,
        preferred_start_dates=preferred_dates,
        preferred_start_range=preferred_range,
    )
    preference.validate_against(travel_window)
    return preference


def _legacy_track_to_preference(
    raw: dict[str, Any],
    index: int,
    travel_window: TravelWindow,
) -> TrackPreference:
    context = f"tracks[{index}]"
    slug = raw.get("track") or raw.get("slug") or raw.get("name")
    preferred = _parse_legacy_ranges(raw.get("preferred"), f"{context}.preferred")
    acceptable = _parse_legacy_ranges(raw.get("acceptable"), f"{context}.acceptable")

    for i, pref in enumerate(preferred):
        if not any(
            pref.start >= acc.start and pref.end <= acc.end for acc in acceptable
        ):
            raise ValueError(
                f"{context}.preferred[{i}] must fall within an acceptable date range"
            )

    resolved = resolve_track(str(slug))
    preference = TrackPreference(
        slug=resolved.slug,
        acceptable_start_range=_union_ranges(acceptable),
        preferred_start_range=_union_ranges(preferred),
        complete_itinerary_only=False,
    )
    preference.validate_against(travel_window)
    return preference


def _parse_trip_block(raw: dict[str, Any]) -> tuple[str, Party, TravelWindow]:
    trip_raw = raw.get("trip")
    if not isinstance(trip_raw, dict):
        raise ValueError("trip must be a mapping")

    name = trip_raw.get("name")
    if not name or not isinstance(name, str):
        raise ValueError("trip.name must be a non-empty string")

    party_raw = trip_raw.get("party") or raw.get("party")
    if not isinstance(party_raw, dict):
        raise ValueError("party must be a mapping (at root or under trip)")
    adults = party_raw.get("adults")
    if not isinstance(adults, int):
        raise ValueError("party.adults must be an integer")

    travel_raw = trip_raw.get("travel_window") or raw.get("travel_window")
    if not isinstance(travel_raw, dict):
        raise ValueError("travel_window must be a mapping (at root or under trip)")
    travel_window = TravelWindow(
        _parse_date(travel_raw.get("start"), "travel_window.start"),
        _parse_date(travel_raw.get("end"), "travel_window.end"),
    )

    return name.strip(), Party(adults=adults), travel_window


def _parse_trip_fit_config(raw: dict[str, Any]) -> TripFitConfig:
    trip_fit_raw = raw.get("trip_fit")
    if trip_fit_raw is None:
        return TripFitConfig()
    if not isinstance(trip_fit_raw, dict):
        raise ValueError("trip_fit must be a mapping")

    enabled = trip_fit_raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("trip_fit.enabled must be a boolean")

    min_rest = trip_fit_raw.get("min_rest_days_between_walks", 1)
    if not isinstance(min_rest, int):
        raise ValueError("trip_fit.min_rest_days_between_walks must be an integer")

    buffer_before = trip_fit_raw.get("buffer_days_before_first_walk", 1)
    if not isinstance(buffer_before, int):
        raise ValueError("trip_fit.buffer_days_before_first_walk must be an integer")

    buffer_after = trip_fit_raw.get("buffer_days_after_last_walk", 1)
    if not isinstance(buffer_after, int):
        raise ValueError("trip_fit.buffer_days_after_last_walk must be an integer")

    return TripFitConfig(
        enabled=enabled,
        min_rest_days_between_walks=min_rest,
        buffer_days_before_first_walk=buffer_before,
        buffer_days_after_last_walk=buffer_after,
    )


def _parse_notifications_config(raw: dict[str, Any]) -> NotificationConfig:
    notifications_raw = raw.get("notifications")
    if notifications_raw is None:
        return NotificationConfig()

    if not isinstance(notifications_raw, dict):
        raise ValueError("notifications must be a mapping")

    console = notifications_raw.get("console", True)
    if not isinstance(console, bool):
        raise ValueError("notifications.console must be a boolean")

    telegram_raw = notifications_raw.get("telegram")
    if telegram_raw is None:
        telegram = TelegramNotificationConfig()
    else:
        if not isinstance(telegram_raw, dict):
            raise ValueError("notifications.telegram must be a mapping")
        enabled = telegram_raw.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("notifications.telegram.enabled must be a boolean")
        bot_token_env = telegram_raw.get("bot_token_env", "GREATWALKBOT_TELEGRAM_BOT_TOKEN")
        chat_id_env = telegram_raw.get("chat_id_env", "GREATWALKBOT_TELEGRAM_CHAT_ID")
        if not isinstance(bot_token_env, str) or not bot_token_env:
            raise ValueError("notifications.telegram.bot_token_env must be a non-empty string")
        if not isinstance(chat_id_env, str) or not chat_id_env:
            raise ValueError("notifications.telegram.chat_id_env must be a non-empty string")
        telegram = TelegramNotificationConfig(
            enabled=enabled,
            bot_token_env=bot_token_env,
            chat_id_env=chat_id_env,
        )

    config = NotificationConfig(console=console, telegram=telegram)
    if telegram.enabled:
        resolve_telegram_credentials(telegram)
    return config


def _parse_retry_config(raw: dict[str, Any]) -> RetryConfig:
    retry_raw = raw.get("retry")
    if retry_raw is None:
        return RetryConfig()
    if not isinstance(retry_raw, dict):
        raise ValueError("retry must be a mapping")

    max_attempts = retry_raw.get("max_attempts", 3)
    if not isinstance(max_attempts, int):
        raise ValueError("retry.max_attempts must be an integer")

    base_delay = retry_raw.get("base_delay_seconds", 1.0)
    if not isinstance(base_delay, (int, float)):
        raise ValueError("retry.base_delay_seconds must be a number")

    max_delay = retry_raw.get("max_delay_seconds", 60.0)
    if not isinstance(max_delay, (int, float)):
        raise ValueError("retry.max_delay_seconds must be a number")

    return RetryConfig(
        max_attempts=max_attempts,
        base_delay_seconds=float(base_delay),
        max_delay_seconds=float(max_delay),
    )


def _build_trip_plan(
    raw: dict[str, Any],
    *,
    trip: Trip,
    interval: int,
    source: str,
) -> TripPlan:
    return TripPlan(
        trip=trip,
        polling_interval_seconds=interval,
        source=source,
        retry=_parse_retry_config(raw),
        notifications=_parse_notifications_config(raw),
        trip_fit=_parse_trip_fit_config(raw),
    )


def _load_trip_format(raw: dict[str, Any]) -> TripPlan:
    name, party, travel_window = _parse_trip_block(raw)

    tracks_raw = raw.get("tracks")
    if not isinstance(tracks_raw, list) or not tracks_raw:
        raise ValueError("tracks must be a non-empty list")

    tracks = tuple(
        _parse_track_preference(item, i, travel_window)
        for i, item in enumerate(tracks_raw)
    )

    interval = raw.get("polling_interval") or raw.get("polling_interval_seconds")
    if not isinstance(interval, int):
        raise ValueError("polling_interval must be an integer (seconds)")

    source = raw.get("source", "playwright")
    trip = Trip(name=name, party=party, travel_window=travel_window, tracks=tracks)
    return _build_trip_plan(raw, trip=trip, interval=interval, source=source)


def _load_legacy_format(raw: dict[str, Any]) -> TripPlan:
    party_size = raw.get("party_size")
    if not isinstance(party_size, int):
        raise ValueError("party_size must be an integer")

    interval = raw.get("polling_interval") or raw.get("polling_interval_seconds")
    if not isinstance(interval, int):
        raise ValueError("polling_interval must be an integer (seconds)")

    tracks_raw = raw.get("tracks")
    if not isinstance(tracks_raw, list) or not tracks_raw:
        raise ValueError("tracks must be a non-empty list")

    all_acceptable: list[DateRange] = []
    for i, item in enumerate(tracks_raw):
        if not isinstance(item, dict):
            raise ValueError(f"tracks[{i}] must be a mapping")
        all_acceptable.extend(
            _parse_legacy_ranges(item.get("acceptable"), f"tracks[{i}].acceptable")
        )
    envelope = _union_ranges(tuple(all_acceptable))
    travel_window = TravelWindow(envelope.start, envelope.end)

    tracks = tuple(
        _parse_track_preference(item, i, travel_window)
        for i, item in enumerate(tracks_raw)
    )

    source = raw.get("source", "playwright")
    trip = Trip(
        name="Watch",
        party=Party(adults=party_size),
        travel_window=travel_window,
        tracks=tracks,
    )
    return _build_trip_plan(raw, trip=trip, interval=interval, source=source)


def load_watch_config(path: str | Path) -> TripPlan:
    """Load a trip plan from YAML (supports trip and legacy watch formats)."""
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, dict):
        raise ValueError("Config root must be a mapping")

    if "trip" in raw:
        return _load_trip_format(raw)
    return _load_legacy_format(raw)
