"""Structured logging configuration."""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


class _UtcFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):  # noqa: N802
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def configure_logging(log_dir: Path | None = None, *, level: int | None = None) -> Path | None:
    """Configure console and optional file logging for greatwalkbot."""
    if level is None:
        level_name = os.environ.get("GREATWALKBOT_LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger("greatwalkbot")
    root.setLevel(level)
    root.handlers.clear()
    root.propagate = False

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(
        _UtcFormatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    root.addHandler(console)

    log_file: Path | None = None
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "greatwalkbot.log"
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(
            _UtcFormatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            )
        )
        root.addHandler(file_handler)

    return log_file
