"""HTTP client for the Telegram Bot API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from greatwalkbot.infra.errors import FetchError
from greatwalkbot.infra.retry import RetryPolicy, retry_call
from greatwalkbot.notifications.errors import TelegramDeliveryError

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_RETRY_POLICY = RetryPolicy(max_attempts=3, base_delay_seconds=1.0, max_delay_seconds=15.0)


class TelegramClient:
    """Send messages via the Telegram Bot API with timeout and bounded retries."""

    def __init__(
        self,
        bot_token: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        retry_policy: RetryPolicy | None = None,
        http_client: httpx.Client | None = None,
        sleep_fn=None,
    ) -> None:
        self._bot_token = bot_token
        self._timeout_seconds = timeout_seconds
        self._retry_policy = retry_policy or DEFAULT_RETRY_POLICY
        self._http_client = http_client
        self._owns_client = http_client is None
        self._sleep_fn = sleep_fn

    def send_message(self, chat_id: str, text: str) -> None:
        def _send() -> None:
            client = self._client()
            try:
                response = client.post(
                    f"/bot{self._bot_token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "disable_web_page_preview": True,
                    },
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise FetchError(f"Telegram request failed: {exc}") from exc

            if response.status_code >= 500:
                raise FetchError(f"Telegram server error: HTTP {response.status_code}")
            if response.status_code != 200:
                summary = _safe_error_summary(response)
                raise TelegramDeliveryError(
                    f"Telegram API returned HTTP {response.status_code}: {summary}"
                )

            payload = response.json()
            if not payload.get("ok"):
                description = str(payload.get("description", "unknown error"))
                raise TelegramDeliveryError(f"Telegram API error: {description}")

        retry_call(_send, self._retry_policy, sleep_fn=self._sleep_fn)

    def close(self) -> None:
        if self._owns_client and self._http_client is not None:
            self._http_client.close()
            self._http_client = None

    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(
                base_url=TELEGRAM_API_BASE,
                timeout=self._timeout_seconds,
            )
        return self._http_client


def _safe_error_summary(response: httpx.Response) -> str:
    try:
        payload: dict[str, Any] = response.json()
        return str(payload.get("description", "unknown error"))
    except Exception:
        return "unknown error"
