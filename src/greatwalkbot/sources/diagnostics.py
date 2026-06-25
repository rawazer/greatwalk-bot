"""Bounded diagnostic artifacts for SPA/session failures."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DIAGNOSTICS_DIR = Path("logs") / "diagnostics"
DEFAULT_RETENTION_COUNT = 10
RETENTION_ENV_VAR = "GREATWALKBOT_DIAGNOSTICS_RETENTION"

# Strip script bodies and common token-like patterns from HTML snippets.
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_TOKEN_RE = re.compile(
    r"(?i)(token|session|cookie|authorization|password|bearer)\s*[:=]\s*\S+"
)


@dataclass(frozen=True)
class DiagnosticArtifacts:
    directory: Path
    summary_path: Path
    screenshot_path: Path | None


def diagnostics_retention_count() -> int:
    raw = os.environ.get(RETENTION_ENV_VAR)
    if raw is None:
        return DEFAULT_RETENTION_COUNT
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_RETENTION_COUNT
    return max(1, value)


def _sanitize_html_snippet(html: str, *, max_chars: int = 8_000) -> str:
    without_scripts = _SCRIPT_RE.sub("", html)
    redacted = _TOKEN_RE.sub(r"\1=***", without_scripts)
    return redacted[:max_chars]


def _collect_page_messages(page: Any) -> tuple[str, ...]:
    messages: list[str] = []

    console = getattr(page, "_gwbot_console_messages", None)
    if isinstance(console, list):
        messages.extend(str(item)[:500] for item in console[-20:])

    errors = getattr(page, "_gwbot_page_errors", None)
    if isinstance(errors, list):
        messages.extend(f"pageerror: {str(item)[:500]}" for item in errors[-10:])

    return tuple(messages)


def save_session_failure_diagnostics(
    *,
    page: Any | None,
    track_name: str,
    track_slug: str,
    error: BaseException,
    diagnostics_dir: Path | None = None,
    network_timeline: list[dict[str, Any]] | None = None,
    form_state: dict[str, Any] | None = None,
) -> DiagnosticArtifacts | None:
    """Save screenshot and sanitized summary. Never stores cookies, tokens, or payloads."""
    base_dir = diagnostics_dir or DEFAULT_DIAGNOSTICS_DIR
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = base_dir / f"{timestamp}_{track_slug}"
    run_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "timestamp": timestamp,
        "track_name": track_name,
        "track_slug": track_slug,
        "error_type": type(error).__name__,
        "error_message": str(error)[:2000],
    }

    if network_timeline:
        summary["network_timeline"] = network_timeline[:80]

    if form_state:
        summary["search_form_state"] = form_state
    elif hasattr(error, "form_state") and getattr(error, "form_state", None):
        summary["search_form_state"] = getattr(error, "form_state")

    screenshot_path: Path | None = None
    if page is not None:
        try:
            summary["url"] = str(page.url)[:500]
        except Exception:
            summary["url"] = None
        try:
            summary["title"] = str(page.title())[:500]
        except Exception:
            summary["title"] = None

        messages = _collect_page_messages(page)
        if messages:
            summary["page_messages"] = list(messages)

        try:
            html = page.content()
            summary["html_snippet"] = _sanitize_html_snippet(html)
        except Exception:
            pass

        try:
            screenshot_path = run_dir / "screenshot.png"
            page.screenshot(path=str(screenshot_path), full_page=False, timeout=5_000)
        except Exception as exc:
            summary["screenshot_error"] = str(exc)[:500]
            screenshot_path = None

    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    enforce_retention(base_dir, diagnostics_retention_count())

    artifacts = DiagnosticArtifacts(
        directory=run_dir,
        summary_path=summary_path,
        screenshot_path=screenshot_path,
    )
    logger.warning(
        "Saved session diagnostics for %s under %s (summary=%s%s)",
        track_slug,
        run_dir,
        summary_path,
        f", screenshot={screenshot_path}" if screenshot_path else "",
    )
    return artifacts


def enforce_retention(diagnostics_dir: Path, max_sets: int) -> None:
    if not diagnostics_dir.is_dir():
        return
    entries = sorted(
        (p for p in diagnostics_dir.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in entries[max_sets:]:
        for child in stale.iterdir():
            child.unlink(missing_ok=True)
        stale.rmdir()
