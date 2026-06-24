"""Notification message formatting."""

from __future__ import annotations

from greatwalkbot.monitoring.models import AvailableItinerary

DOC_BOOKING_URL = "https://bookings.doc.govt.nz/Web/"


def format_itinerary_message(itinerary: AvailableItinerary, party_size: int) -> str:
    facilities = ", ".join(itinerary.facilities) if itinerary.facilities else "n/a"
    adults = itinerary.party_size or party_size
    lines = [
        f"NEW {itinerary.preference}",
        f"{itinerary.track_name} starting {itinerary.start_date.isoformat()}",
        f"Ends {itinerary.end_date.isoformat()} ({itinerary.itinerary_nights} nights)",
        f"Complete itinerary verified for {adults} adult"
        + ("s" if adults != 1 else ""),
        f"Available spaces: {itinerary.spaces}",
        f"Facilities: {facilities}",
    ]
    if itinerary.direction:
        lines.append(f"Direction: {itinerary.direction}")
    if itinerary.trip_fit is True:
        lines.append("Fits current trip window with remaining walks.")
    lines.extend(
        [
            "",
            f"Open DOC booking site to confirm and book: {DOC_BOOKING_URL}",
        ]
    )
    return "\n".join(lines)


def format_test_message(trip_name: str) -> str:
    return (
        "[GreatWalkBot TEST] Notification delivery check.\n"
        f"Trip: {trip_name}\n"
        "This is not a real availability alert. No DOC site was contacted."
    )
