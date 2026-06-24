"""Notification message formatting."""

from __future__ import annotations

from greatwalkbot.monitoring.models import AvailableItinerary

DOC_BOOKING_URL = "https://bookings.doc.govt.nz/Web/"


def format_itinerary_message(itinerary: AvailableItinerary, party_size: int) -> str:
    facilities = ", ".join(itinerary.facilities) if itinerary.facilities else "n/a"
    return (
        f"NEW {itinerary.preference}\n"
        f"{itinerary.track_name} starting {itinerary.start_date.isoformat()}\n"
        f"Party: {party_size} | Available spaces: {itinerary.spaces}\n"
        f"Facilities: {facilities}\n"
        f"\n"
        f"Open DOC booking site to confirm and book: {DOC_BOOKING_URL}"
    )


def format_test_message(trip_name: str) -> str:
    return (
        "[GreatWalkBot TEST] Notification delivery check.\n"
        f"Trip: {trip_name}\n"
        "This is not a real availability alert. No DOC site was contacted."
    )
