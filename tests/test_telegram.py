"""Tests for Telegram notification delivery."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from greatwalkbot.domain.notifications import NotificationConfig, TelegramNotificationConfig
from greatwalkbot.monitoring.models import AvailableItinerary
from greatwalkbot.notifications.errors import TelegramDeliveryError
from greatwalkbot.notifications.message import DOC_BOOKING_URL, format_itinerary_message
from greatwalkbot.notifications.telegram import TelegramNotifier
from greatwalkbot.notifications.telegram_client import TelegramClient


from support import make_itinerary


def _itinerary() -> AvailableItinerary:
    return make_itinerary(
        facilities=("Clinton Hut", "Mintaro Hut"),
    )


def test_itinerary_message_content():
    text = format_itinerary_message(_itinerary(), party_size=2)
    assert "NEW preferred" in text
    assert "Milford Track starting 2026-12-07" in text
    assert "Complete itinerary verified for 2 adults" in text
    assert "Available spaces: 5" in text
    assert "Clinton Hut" in text
    assert DOC_BOOKING_URL in text
    assert "confirm and book" in text


def test_telegram_client_request_format():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"ok": True}

    client = MagicMock()
    client.post = MagicMock(return_value=response)

    telegram = TelegramClient("test-token", http_client=client, sleep_fn=lambda _s: None)
    telegram.send_message("12345", "hello")

    client.post.assert_called_once()
    args, kwargs = client.post.call_args
    assert args[0] == "/bottest-token/sendMessage"
    assert kwargs["json"]["chat_id"] == "12345"
    assert kwargs["json"]["text"] == "hello"
    assert kwargs["json"]["disable_web_page_preview"] is True


def test_telegram_client_retries_transient_failure():
    transient = MagicMock()
    transient.status_code = 503
    transient.json.return_value = {"ok": False, "description": "retry"}

    success = MagicMock()
    success.status_code = 200
    success.json.return_value = {"ok": True}

    http_client = MagicMock()
    http_client.post = MagicMock(side_effect=[transient, success])

    telegram = TelegramClient(
        "test-token",
        http_client=http_client,
        sleep_fn=lambda _s: None,
    )
    telegram.send_message("12345", "hello")
    assert http_client.post.call_count == 2


def test_telegram_client_raises_on_permanent_api_error():
    response = MagicMock()
    response.status_code = 400
    response.json.return_value = {"ok": False, "description": "chat not found"}

    http_client = MagicMock()
    http_client.post = MagicMock(return_value=response)

    telegram = TelegramClient(
        "test-token",
        http_client=http_client,
        sleep_fn=lambda _s: None,
    )
    with pytest.raises(TelegramDeliveryError, match="chat not found"):
        telegram.send_message("bad-chat", "hello")


def test_telegram_notifier_sends_formatted_message():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"ok": True}

    http_client = MagicMock()
    http_client.post = MagicMock(return_value=response)

    client = TelegramClient("token", http_client=http_client, sleep_fn=lambda _s: None)
    notifier = TelegramNotifier(client, "999", party_size=2)
    notifier.notify_new_availability(_itinerary())

    payload = http_client.post.call_args.kwargs["json"]
    assert "NEW preferred" in payload["text"]
    assert payload["chat_id"] == "999"
