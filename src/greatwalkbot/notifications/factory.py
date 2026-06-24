"""Build configured notification channels."""

from __future__ import annotations

import logging
import os

from greatwalkbot.domain.notifications import NotificationConfig, TelegramNotificationConfig
from greatwalkbot.domain.plan import TripPlan
from greatwalkbot.monitoring.metrics import RuntimeMetrics
from greatwalkbot.notifications.composite import CompositeNotifier
from greatwalkbot.notifications.console import ConsoleNotifier
from greatwalkbot.notifications.message import format_test_message
from greatwalkbot.notifications.protocol import Notifier
from greatwalkbot.notifications.telegram import TelegramNotifier
from greatwalkbot.notifications.telegram_client import TelegramClient

logger = logging.getLogger(__name__)


def resolve_telegram_credentials(
    config: TelegramNotificationConfig,
) -> tuple[str, str]:
    token = os.environ.get(config.bot_token_env)
    if not token:
        raise ValueError(
            f"Telegram is enabled but environment variable {config.bot_token_env} is not set"
        )
    chat_id = os.environ.get(config.chat_id_env)
    if not chat_id:
        raise ValueError(
            f"Telegram is enabled but environment variable {config.chat_id_env} is not set"
        )
    return token, chat_id


def build_notifiers(
    plan: TripPlan,
    *,
    metrics: RuntimeMetrics | None = None,
) -> Notifier:
    notifiers: list[Notifier] = []
    config = plan.notifications
    party_size = plan.trip.party.size

    if config.console:
        notifiers.append(ConsoleNotifier(party_size=party_size))

    if config.telegram.enabled:
        token, chat_id = resolve_telegram_credentials(config.telegram)
        client = TelegramClient(token)
        notifiers.append(
            TelegramNotifier(client, chat_id, party_size=party_size)
        )

    if len(notifiers) == 1:
        notifier = notifiers[0]
        return CompositeNotifier((notifier,), metrics=metrics)

    return CompositeNotifier(tuple(notifiers), metrics=metrics)


def send_test_notifications(plan: TripPlan) -> None:
    """Send test messages through all configured channels."""
    config = plan.notifications
    trip_name = plan.trip.name

    if config.console:
        logger.info("%s", format_test_message(trip_name).replace("\n", " | "))

    if config.telegram.enabled:
        token, chat_id = resolve_telegram_credentials(config.telegram)
        client = TelegramClient(token)
        try:
            TelegramNotifier(client, chat_id, party_size=plan.trip.party.size).send_test(
                trip_name
            )
        finally:
            client.close()
