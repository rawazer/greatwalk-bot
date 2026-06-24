"""Notification delivery errors."""

from __future__ import annotations


class TelegramDeliveryError(Exception):
    """Telegram message could not be delivered."""
