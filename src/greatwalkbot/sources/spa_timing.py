"""Bounded timeout defaults for DOC SPA navigation."""

from __future__ import annotations

# Navigation uses domcontentloaded — not networkidle.
GOTO_WAIT_UNTIL = "domcontentloaded"

DEFAULT_NAVIGATION_TIMEOUT_MS = 30_000
DEFAULT_APP_READY_TIMEOUT_MS = 15_000
DEFAULT_TRACK_WAIT_TIMEOUT_MS = 10_000
DEFAULT_CAPTURE_TIMEOUT_MS = 20_000
DEFAULT_SELECTION_COMMIT_TIMEOUT_MS = 8_000
DEFAULT_FORM_READY_TIMEOUT_MS = 15_000

# Per track: initial attempt + one retry after browser restart.
MAX_FETCH_ATTEMPTS_PER_TRACK = 2

# Worst-case per track (initial + restart + retry), excluding poll sleep:
#   navigation (30s) + app-ready (15s) + track wait (10s) + capture (20s) ≈ 75s
#   × 2 attempts ≈ 150s — still below a typical 300s poll interval.
