"""Bounded timeout defaults for DOC SPA navigation."""

from __future__ import annotations

# Shell navigation uses commit — not domcontentloaded or networkidle.
GOTO_WAIT_UNTIL = "commit"

# Stage 1: DOC shell transport (page.goto).
DEFAULT_SHELL_NAVIGATION_TIMEOUT_MS = 60_000
# Backwards-compatible alias used by existing call sites for shell navigation.
DEFAULT_NAVIGATION_TIMEOUT_MS = DEFAULT_SHELL_NAVIGATION_TIMEOUT_MS

# Stage 2: Great Walk route hash + UI readiness evidence.
DEFAULT_SPA_READINESS_TIMEOUT_MS = 45_000
# Backwards-compatible alias for SPA/UI readiness waits.
DEFAULT_APP_READY_TIMEOUT_MS = DEFAULT_SPA_READINESS_TIMEOUT_MS

DEFAULT_TRACK_WAIT_TIMEOUT_MS = 10_000
DEFAULT_CAPTURE_TIMEOUT_MS = 20_000
DEFAULT_SELECTION_COMMIT_TIMEOUT_MS = 8_000
DEFAULT_FORM_READY_TIMEOUT_MS = 15_000
DEFAULT_CONTROL_CLICKABLE_TIMEOUT_MS = 10_000

# Per track: initial attempt + one retry after browser restart.
MAX_FETCH_ATTEMPTS_PER_TRACK = 2

# Worst-case per track (initial + restart + retry), excluding poll sleep:
#   shell nav (60s) + spa-ready (45s) + track wait (10s) + capture (20s) ≈ 135s
#   × 2 attempts ≈ 270s — still below a typical 300s poll interval.
