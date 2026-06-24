"""Tests for runtime metrics."""

from pathlib import Path

from greatwalkbot.monitoring.metrics import RuntimeMetrics


def test_metrics_flush_and_load(tmp_path: Path):
    status_path = tmp_path / "status.json"
    metrics = RuntimeMetrics(status_path=status_path, trip_name="Test Trip")

    started = metrics.record_poll_start()
    metrics.record_poll_success(started)
    metrics.record_browser_restart()

    loaded = RuntimeMetrics.load(status_path)
    assert loaded is not None
    assert loaded.schema_version == 2
    assert loaded.polls_completed == 1
    assert loaded.successful_polls == 1
    assert loaded.browser_restarts == 1
    assert loaded.trip_name == "Test Trip"
    assert loaded.average_poll_duration_seconds >= 0


def test_metrics_record_failure(tmp_path: Path):
    status_path = tmp_path / "status.json"
    metrics = RuntimeMetrics(status_path=status_path)

    started = metrics.record_poll_start()
    metrics.record_poll_failure(started)

    loaded = RuntimeMetrics.load(status_path)
    assert loaded is not None
    assert loaded.failed_polls == 1
    assert loaded.successful_polls == 0
