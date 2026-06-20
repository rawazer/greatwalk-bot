"""Notification channel protocol."""

from __future__ import annotations

from typing import Protocol

from greatwalkbot.monitoring.models import AvailableItinerary


class Notifier(Protocol):
    def notify_new_availability(self, itinerary: AvailableItinerary) -> None:
        """Deliver a notification for newly detected availability."""
