"""Tests for runtime state files and status.json contract."""

import json
from pathlib import Path

import pytest

from greatwalkbot.monitoring.metrics import RuntimeMetrics
from greatwalkbot.monitoring.status import (
    STATUS_SCHEMA_VERSION,
    RuntimeState,
    atomic_write_json,
    load_status_snapshot,
)


def test_status_json_schema_fields(tmp_path: Path):
    status_path = tmp_path / "status.json"
    metrics = RuntimeMetrics(status_path=status_path, trip_name="Honeymoon")
    metrics.set_state(RuntimeState.STARTING)

    started = metrics.record_poll_start()
    metrics.record_fetch_error("milford", "timeout")
    metrics.record_poll_failure(started)

    raw = json.loads(status_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == STATUS_SCHEMA_VERSION
    assert raw["state"] == RuntimeState.ERROR.value
    assert raw["trip_name"] == "Honeymoon"
    assert raw["failed_polls"] == 1
    assert raw["last_error"]["track_slug"] == "milford"
    assert raw["last_error"]["message"] == "timeout"
    assert "at" in raw["last_error"]


def test_atomic_write_never_leaves_tmp_file(tmp_path: Path):
    status_path = tmp_path / "status.json"
    payload = {"schema_version": 1, "started_at": "2026-01-01T00:00:00Z", "state": "polling"}

    atomic_write_json(status_path, payload)

    assert status_path.is_file()
    assert not status_path.with_suffix(".json.tmp").exists()
    assert load_status_snapshot(status_path) is not None


def test_load_status_snapshot_rejects_invalid_json(tmp_path: Path):
    status_path = tmp_path / "status.json"
    status_path.write_text("{not valid", encoding="utf-8")
    assert load_status_snapshot(status_path) is None


def test_runtime_metrics_records_notification_health(tmp_path: Path):
    status_path = tmp_path / "status.json"
    metrics = RuntimeMetrics(status_path=status_path)
    metrics.record_notification_attempt()
    metrics.record_notification_error("delivery failed")

    loaded = RuntimeMetrics.load(status_path)
    assert loaded is not None
    assert loaded.last_notification_attempt_at is not None
    assert loaded.last_notification_error is not None
    assert loaded.last_notification_error.message == "delivery failed"


def test_runtime_metrics_state_transitions(tmp_path: Path):
    status_path = tmp_path / "status.json"
    metrics = RuntimeMetrics(status_path=status_path)

    metrics.set_state(RuntimeState.POLLING)
    assert RuntimeMetrics.load(status_path).state == RuntimeState.POLLING.value

    metrics.set_state(RuntimeState.SLEEPING)
    assert RuntimeMetrics.load(status_path).state == RuntimeState.SLEEPING.value

    metrics.set_state(RuntimeState.STOPPED)
    assert RuntimeMetrics.load(status_path).state == RuntimeState.STOPPED.value
