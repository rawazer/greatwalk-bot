"""Retry helpers with exponential backoff and jitter."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from greatwalkbot.infra.errors import RetryableError

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds <= 0:
            raise ValueError("base_delay_seconds must be positive")


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, RetryableError):
        return True
    module = type(exc).__module__
    if module.startswith("playwright"):
        return True
    return isinstance(exc, (TimeoutError, ConnectionError, OSError))


def _delay_seconds(policy: RetryPolicy, attempt: int) -> float:
    exponential = policy.base_delay_seconds * (2 ** (attempt - 1))
    capped = min(exponential, policy.max_delay_seconds)
    return random.uniform(0, capped)


def retry_call(
    fn: Callable[[], T],
    policy: RetryPolicy,
    *,
    on_retry: Callable[[BaseException, int], None] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> T:
    """Call fn with retries for transient failures."""
    sleeper = sleep_fn or time.sleep
    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if not is_retryable(exc):
                raise
            last_exc = exc
            if attempt >= policy.max_attempts:
                break
            if on_retry is not None:
                on_retry(exc, attempt)
            delay = _delay_seconds(policy, attempt)
            logger.warning(
                "Retryable error on attempt %s/%s: %s; sleeping %.1fs",
                attempt,
                policy.max_attempts,
                exc,
                delay,
            )
            sleeper(delay)
    assert last_exc is not None
    raise last_exc
