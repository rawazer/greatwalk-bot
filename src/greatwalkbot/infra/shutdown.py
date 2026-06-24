"""Graceful shutdown signalling."""

from __future__ import annotations

import logging
import signal
import threading

logger = logging.getLogger(__name__)


class ShutdownController:
    """Thread-safe shutdown flag set by Ctrl+C or SIGTERM."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._handlers_installed = False

    @property
    def shutdown_requested(self) -> bool:
        return self._event.is_set()

    def request_shutdown(self) -> None:
        if not self._event.is_set():
            logger.info("Shutdown requested; finishing current work")
            self._event.set()

    def install_handlers(self) -> None:
        if self._handlers_installed:
            return

        def _handle_signal(signum, _frame) -> None:
            logger.info("Received signal %s", signum)
            self.request_shutdown()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handle_signal)
            except (ValueError, OSError):
                # SIGTERM unavailable on some platforms (e.g. Windows).
                pass
        self._handlers_installed = True
