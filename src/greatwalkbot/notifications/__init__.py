"""Notification channel interface and implementations."""

from greatwalkbot.notifications.composite import CompositeNotifier
from greatwalkbot.notifications.console import ConsoleNotifier
from greatwalkbot.notifications.factory import build_notifiers, send_test_notifications
from greatwalkbot.notifications.protocol import Notifier
from greatwalkbot.notifications.telegram import TelegramNotifier

__all__ = [
    "CompositeNotifier",
    "ConsoleNotifier",
    "Notifier",
    "TelegramNotifier",
    "build_notifiers",
    "send_test_notifications",
]
