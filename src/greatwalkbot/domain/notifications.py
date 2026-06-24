"""Notification channel configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TelegramNotificationConfig:
    enabled: bool = False
    bot_token_env: str = "GREATWALKBOT_TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "GREATWALKBOT_TELEGRAM_CHAT_ID"


@dataclass(frozen=True)
class NotificationConfig:
    console: bool = True
    telegram: TelegramNotificationConfig = field(default_factory=TelegramNotificationConfig)

    def __post_init__(self) -> None:
        if not self.console and not self.telegram.enabled:
            raise ValueError(
                "At least one notification channel must be enabled (console or telegram)"
            )
