"""Console notification channel."""

from __future__ import annotations

import logging

from greatwalkbot.monitoring.models import AvailableItinerary

logger = logging.getLogger(__name__)


class ConsoleNotifier:
    def notify_new_availability(self, itinerary: AvailableItinerary) -> None:
        facilities = ", ".join(itinerary.facilities)
        logger.info(
            "NEW %s availability: %s starting %s (%s spaces) - %s",
            itinerary.preference,
            itinerary.track_name,
            itinerary.start_date.isoformat(),
            itinerary.spaces,
            facilities,
        )
