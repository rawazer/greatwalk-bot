"""Tests for notification configuration validation."""

import os
from pathlib import Path

import pytest

from greatwalkbot.config.loader import load_watch_config
from greatwalkbot.domain.notifications import NotificationConfig, TelegramNotificationConfig
from greatwalkbot.notifications.factory import resolve_telegram_credentials


def test_missing_bot_token_env(monkeypatch):
    monkeypatch.delenv("GREATWALKBOT_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("GREATWALKBOT_TELEGRAM_CHAT_ID", raising=False)

    config = TelegramNotificationConfig(enabled=True)
    with pytest.raises(ValueError, match="GREATWALKBOT_TELEGRAM_BOT_TOKEN"):
        resolve_telegram_credentials(config)


def test_missing_chat_id_env(monkeypatch):
    monkeypatch.setenv("GREATWALKBOT_TELEGRAM_BOT_TOKEN", "token-value")
    monkeypatch.delenv("GREATWALKBOT_TELEGRAM_CHAT_ID", raising=False)

    config = TelegramNotificationConfig(enabled=True)
    with pytest.raises(ValueError, match="GREATWALKBOT_TELEGRAM_CHAT_ID"):
        resolve_telegram_credentials(config)


def test_load_config_validates_telegram_env(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("GREATWALKBOT_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("GREATWALKBOT_TELEGRAM_CHAT_ID", raising=False)

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
polling_interval: 60
trip:
  name: Test
party:
  adults: 2
travel_window:
  start: 2026-12-01
  end: 2026-12-31
notifications:
  console: false
  telegram:
    enabled: true
tracks:
  - track: milford
    preferred_start_dates:
      - 2026-12-07
    acceptable_start_range:
      start: 2026-12-01
      end: 2026-12-31
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="GREATWALKBOT_TELEGRAM_BOT_TOKEN"):
        load_watch_config(config_file)


def test_error_message_never_contains_secret_values(monkeypatch):
    monkeypatch.setenv("GREATWALKBOT_TELEGRAM_BOT_TOKEN", "super-secret-token")
    monkeypatch.delenv("GREATWALKBOT_TELEGRAM_CHAT_ID", raising=False)

    config = TelegramNotificationConfig(enabled=True)
    with pytest.raises(ValueError) as exc_info:
        resolve_telegram_credentials(config)
    assert "super-secret-token" not in str(exc_info.value)
