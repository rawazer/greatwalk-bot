"""Console notification channel."""

from __future__ import annotations

import logging

from greatwalkbot.monitoring.models import AvailableItinerary
from greatwalkbot.notifications.message import format_itinerary_message

logger = logging.getLogger(__name__)


class ConsoleNotifier:
    def __init__(self, *, party_size: int = 1) -> None:
        self._party_size = party_size

    def notify_new_availability(self, itinerary: AvailableItinerary) -> None:
        message = format_itinerary_message(itinerary, self._party_size)
        for line in message.splitlines():
            logger.info("%s", line)
