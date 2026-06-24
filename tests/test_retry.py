"""Tests for retry policy."""

import pytest

from greatwalkbot.infra.errors import FetchError, RetryableError
from greatwalkbot.infra.retry import RetryPolicy, is_retryable, retry_call


class CustomRetryable(RetryableError):
    pass


def test_is_retryable_classifies_errors():
    assert is_retryable(FetchError("transient"))
    assert is_retryable(TimeoutError())
    assert is_retryable(ConnectionError())
    assert not is_retryable(ValueError("bad config"))
    assert not is_retryable(RuntimeError("permanent"))


def test_retry_call_succeeds_after_transient_failure():
    attempts = {"count": 0}

    def fn():
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise CustomRetryable("try again")
        return "ok"

    result = retry_call(fn, RetryPolicy(max_attempts=3, base_delay_seconds=0.01))
    assert result == "ok"
    assert attempts["count"] == 2


def test_retry_call_fails_fast_for_non_retryable():
    attempts = {"count": 0}

    def fn():
        attempts["count"] += 1
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        retry_call(fn, RetryPolicy(max_attempts=3, base_delay_seconds=0.01))
    assert attempts["count"] == 1


def test_retry_call_exhausts_attempts():
    attempts = {"count": 0}

    def fn():
        attempts["count"] += 1
        raise CustomRetryable("still failing")

    with pytest.raises(CustomRetryable):
        retry_call(fn, RetryPolicy(max_attempts=2, base_delay_seconds=0.01))
    assert attempts["count"] == 2
