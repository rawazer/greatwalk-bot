"""Tests for status CLI command."""

from greatwalkbot.cli import main
from greatwalkbot.monitoring.metrics import RuntimeMetrics


def test_status_command_prints_metrics(tmp_path, capsys):
    status_path = tmp_path / "status.json"
    metrics = RuntimeMetrics(status_path=status_path, trip_name="Test Trip")
    started = metrics.record_poll_start()
    metrics.record_poll_success(started)

    exit_code = main(["status", "--status-file", str(status_path)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Test Trip" in output
    assert "Polls completed: 1" in output


def test_status_command_missing_file(capsys):
    exit_code = main(["status", "--status-file", "nonexistent/status.json"])
    assert exit_code == 1
    assert "No status file found" in capsys.readouterr().err
