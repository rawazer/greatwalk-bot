"""Tests for gwbot notify-test command."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from greatwalkbot.cli import main


def test_notify_test_does_not_create_doc_source(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GREATWALKBOT_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("GREATWALKBOT_TELEGRAM_CHAT_ID", "12345")

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
polling_interval: 60
trip:
  name: Test Trip
party:
  adults: 2
travel_window:
  start: 2026-12-01
  end: 2026-12-31
notifications:
  console: true
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

    with patch("greatwalkbot.cli.send_test_notifications") as send_test:
        with patch("greatwalkbot.cli.PlaywrightAvailabilitySource") as playwright_cls:
            with patch("greatwalkbot.cli.HttpAvailabilitySource") as http_cls:
                exit_code = main(["notify-test", str(config_file)])

    assert exit_code == 0
    send_test.assert_called_once()
    playwright_cls.assert_not_called()
    http_cls.assert_not_called()


def test_notify_test_returns_nonzero_on_telegram_failure(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GREATWALKBOT_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("GREATWALKBOT_TELEGRAM_CHAT_ID", "12345")

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
polling_interval: 60
trip:
  name: Test Trip
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

    from greatwalkbot.notifications.errors import TelegramDeliveryError

    with patch(
        "greatwalkbot.cli.send_test_notifications",
        side_effect=TelegramDeliveryError("delivery failed"),
    ):
        exit_code = main(["notify-test", str(config_file)])

    assert exit_code == 1
