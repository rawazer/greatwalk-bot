"""Tests for concise itinerary evaluation logging."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from greatwalkbot.domain.dates import DateRange, TravelWindow
from greatwalkbot.domain.direction import DirectionPreference
from greatwalkbot.domain.party import Party
from greatwalkbot.domain.plan import TripPlan
from greatwalkbot.domain.track import TrackPreference
from greatwalkbot.domain.trip import Trip
from greatwalkbot.models import AvailabilityDay, AvailabilitySnapshot, AvailabilityStatus, Track
from greatwalkbot.monitoring.evaluation_summary import ItineraryEvaluationSummary
from greatwalkbot.monitoring.matcher import find_matching_itineraries
from greatwalkbot.monitoring.watcher import Watcher
from greatwalkbot.notifications.protocol import Notifier
from greatwalkbot.parsing import parse_gw_facility_response

FIXTURES = Path(__file__).parent / "fixtures"
MILFORD = Track("milford", "Milford Track", 873, 4, fixed_nights=3)
ROUTEBURN = Track("routeburn", "Routeburn Track", 874, 7, fixed_nights=2)
TRAVEL_WINDOW = TravelWindow(date(2026, 11, 29), date(2026, 12, 31))
PARTY = Party(adults=2)


def _routeburn_preference() -> TrackPreference:
    return TrackPreference(
        slug="routeburn",
        direction=DirectionPreference.EITHER,
        acceptable_start_range=DateRange(date(2026, 12, 1), date(2026, 12, 31)),
        preferred_start_range=DateRange(date(2026, 12, 10), date(2026, 12, 14)),
        complete_itinerary_only=True,
    )


def test_skip_lines_are_debug_not_info(caplog):
    payload = json.loads((FIXTURES / "milford_partial.json").read_text(encoding="utf-8"))
    snapshot = parse_gw_facility_response(
        payload, MILFORD, date(2026, 12, 7), date(2026, 12, 9)
    )
    preference = TrackPreference(
        slug="milford",
        acceptable_start_range=DateRange(date(2026, 12, 1), date(2026, 12, 31)),
        preferred_start_range=DateRange(date(2026, 12, 7), date(2026, 12, 10)),
        complete_itinerary_only=True,
    )

    with caplog.at_level(logging.DEBUG, logger="greatwalkbot.monitoring.matcher"):
        find_matching_itineraries(snapshot, preference, PARTY, TRAVEL_WINDOW)

    skip_records = [
        record
        for record in caplog.records
        if "Skipped incomplete itinerary" in record.message
    ]
    assert skip_records
    assert all(record.levelno == logging.DEBUG for record in skip_records)
    assert not any(
        record.levelno == logging.INFO
        for record in caplog.records
        if "Skipped incomplete itinerary" in record.message
    )


def test_evaluation_summary_aggregates_repeated_reasons():
    summary = ItineraryEvaluationSummary(track_slug="routeburn")
    summary.record_incomplete(("facility_unavailable",))
    summary.record_incomplete(("facility_unavailable",))
    summary.record_incomplete(("missing_facility_data",))

    assert summary.candidates == 3
    assert summary.incomplete == 3
    assert summary.complete == 0
    assert summary.reason_counts == (
        ("facility_unavailable", 2),
        ("missing_facility_data", 1),
    )
    assert (
        summary.format_log_line()
        == "Evaluation summary: track=routeburn candidates=3 complete=0 "
        "incomplete=3 reasons=facility_unavailable:2,missing_facility_data:1"
    )


def test_reason_ordering_is_deterministic():
    summary = ItineraryEvaluationSummary(track_slug="kepler")
    summary.record_incomplete(("insufficient_party_spaces",))
    summary.record_incomplete(("facility_unavailable",))
    summary.record_incomplete(("missing_facility_data",))

    assert summary.reason_counts == (
        ("facility_unavailable", 1),
        ("insufficient_party_spaces", 1),
        ("missing_facility_data", 1),
    )
    line = summary.format_log_line()
    assert "reasons=facility_unavailable:1,insufficient_party_spaces:1,missing_facility_data:1" in line


def test_routeburn_directions_counted_separately():
    payload = json.loads((FIXTURES / "routeburn_directions.json").read_text(encoding="utf-8"))
    snapshot = parse_gw_facility_response(
        payload, ROUTEBURN, date(2026, 12, 10), date(2026, 12, 11)
    )

    result = find_matching_itineraries(
        snapshot, _routeburn_preference(), PARTY, TRAVEL_WINDOW
    )

    # Two start dates in range, each evaluated in both directions.
    assert result.evaluation.candidates == 4
    assert result.evaluation.complete == 1
    assert result.evaluation.incomplete == 3
    assert len(result.itineraries) == 1


def test_no_incomplete_candidates_omits_reasons():
    summary = ItineraryEvaluationSummary(track_slug="milford")
    summary.record_complete()

    assert (
        summary.format_log_line()
        == "Evaluation summary: track=milford candidates=1 complete=1 incomplete=0"
    )


def test_watcher_emits_evaluation_summary_at_info(caplog):
    snapshot = AvailabilitySnapshot(
        track=MILFORD,
        from_date=date(2026, 12, 7),
        to_date=date(2026, 12, 7),
        days=(
            AvailabilityDay(
                date(2026, 12, 7),
                AvailabilityStatus.AVAILABLE,
                5,
                ("Clinton Hut",),
            ),
        ),
        facility_index=None,
    )

    class Source:
        def reset_poll_timings(self) -> None:
            pass

        def fetch_track_availability(self, track, from_date, to_date):
            return snapshot

    class SilentNotifier(Notifier):
        def notify_new_availability(self, itinerary) -> None:
            pass

    plan = TripPlan(
        trip=Trip(
            name="Test",
            party=Party(adults=2),
            travel_window=TravelWindow(date(2026, 12, 1), date(2026, 12, 31)),
            tracks=(
                TrackPreference(
                    slug="milford",
                    acceptable_start_range=DateRange(date(2026, 12, 1), date(2026, 12, 31)),
                    preferred_start_range=DateRange(date(2026, 12, 7), date(2026, 12, 10)),
                    complete_itinerary_only=True,
                ),
            ),
        ),
        polling_interval_seconds=300,
    )

    with caplog.at_level(logging.INFO, logger="greatwalkbot.monitoring.watcher"):
        Watcher(plan, Source(), SilentNotifier()).run_once()

    summary_lines = [
        record.message
        for record in caplog.records
        if record.message.startswith("Evaluation summary:")
    ]
    assert len(summary_lines) == 1
    assert "track=milford" in summary_lines[0]
    assert "candidates=1" in summary_lines[0]
    assert "incomplete=1" in summary_lines[0]


def test_matching_results_unchanged_for_notifications(tmp_path):
    payload = json.loads((FIXTURES / "milford_complete.json").read_text(encoding="utf-8"))
    snapshot = parse_gw_facility_response(
        payload, MILFORD, date(2026, 12, 7), date(2026, 12, 9)
    )
    preference = TrackPreference(
        slug="milford",
        acceptable_start_range=DateRange(date(2026, 12, 1), date(2026, 12, 31)),
        preferred_start_range=DateRange(date(2026, 12, 7), date(2026, 12, 10)),
        complete_itinerary_only=True,
    )

    result = find_matching_itineraries(snapshot, preference, PARTY, TRAVEL_WINDOW)
    notifier = MagicMock()

    class Source:
        def reset_poll_timings(self) -> None:
            pass

        def fetch_track_availability(self, track, from_date, to_date):
            return snapshot

    plan = TripPlan(
        trip=Trip(
            name="Test",
            party=Party(adults=2),
            travel_window=TRAVEL_WINDOW,
            tracks=(preference,),
        ),
        polling_interval_seconds=300,
    )

    with patch("greatwalkbot.monitoring.watcher.resolve_track", return_value=MILFORD):
        Watcher(plan, Source(), notifier).run_once()

    assert notifier.notify_new_availability.call_count == len(result.itineraries)
    notified = notifier.notify_new_availability.call_args[0][0]
    assert notified.start_date == result.itineraries[0].start_date
