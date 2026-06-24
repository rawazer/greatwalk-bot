"""Telegram notification channel."""

from __future__ import annotations

import logging

from greatwalkbot.monitoring.models import AvailableItinerary
from greatwalkbot.notifications.message import format_itinerary_message, format_test_message
from greatwalkbot.notifications.telegram_client import TelegramClient

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(
        self,
        client: TelegramClient,
        chat_id: str,
        *,
        party_size: int,
    ) -> None:
        self._client = client
        self._chat_id = chat_id
        self._party_size = party_size

    def notify_new_availability(self, itinerary: AvailableItinerary) -> None:
        text = format_itinerary_message(itinerary, self._party_size)
        self._client.send_message(self._chat_id, text)
        logger.info("Telegram notification sent for %s", itinerary.track_name)

    def send_test(self, trip_name: str) -> None:
        self._client.send_message(self._chat_id, format_test_message(trip_name))
        logger.info("Telegram test notification sent")
