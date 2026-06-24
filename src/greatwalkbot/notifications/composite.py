"""Compose multiple notification channels."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from greatwalkbot.monitoring.models import AvailableItinerary
from greatwalkbot.notifications.protocol import Notifier

if TYPE_CHECKING:
    from greatwalkbot.monitoring.metrics import RuntimeMetrics

logger = logging.getLogger(__name__)


class CompositeNotifier:
    """Deliver notifications to multiple channels; failures are isolated per channel."""

    def __init__(
        self,
        notifiers: tuple[Notifier, ...],
        *,
        metrics: RuntimeMetrics | None = None,
    ) -> None:
        if not notifiers:
            raise ValueError("CompositeNotifier requires at least one notifier")
        self._notifiers = notifiers
        self._metrics = metrics

    def notify_new_availability(self, itinerary: AvailableItinerary) -> None:
        for notifier in self._notifiers:
            if self._metrics is not None:
                self._metrics.record_notification_attempt()
            try:
                notifier.notify_new_availability(itinerary)
            except Exception as exc:
                logger.exception("Notification delivery failed")
                if self._metrics is not None:
                    self._metrics.record_notification_error(str(exc))
                continue
            if self._metrics is not None:
                self._metrics.record_notification_success()
