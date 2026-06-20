"""Console notification channel."""

from __future__ import annotations

import sys

from greatwalkbot.monitoring.models import AvailableItinerary


class ConsoleNotifier:
    def notify_new_availability(self, itinerary: AvailableItinerary) -> None:
        facilities = ", ".join(itinerary.facilities)
        message = (
            f"NEW {itinerary.preference} availability: "
            f"{itinerary.track_name} starting {itinerary.start_date.isoformat()} "
            f"({itinerary.spaces} spaces) - {facilities}"
        )
        print(message, file=sys.stdout, flush=True)
