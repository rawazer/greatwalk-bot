# Runtime state contract

GreatWalkBot writes three runtime artifacts when `gwbot watch` is running. These files let you inspect health, avoid duplicate notifications across restarts, and audit failures.

## Files

| Path | Purpose |
|------|---------|
| `data/seen.db` | SQLite database of itineraries already notified |
| `logs/greatwalkbot.log` | Rotating structured application log |
| `logs/status.json` | Machine-readable watcher health snapshot |
| `logs/diagnostics/` | Bounded SPA failure artifacts (screenshot + sanitized summary); gitignored under `logs/` |

All paths are relative to the process working directory (typically the repository root).

---

## `data/seen.db`

SQLite database (WAL mode) with a single table:

```sql
CREATE TABLE seen_itineraries (
    track_slug TEXT NOT NULL,
    start_date TEXT NOT NULL,   -- ISO date (YYYY-MM-DD)
    facilities TEXT NOT NULL,   -- JSON array of hut names
    seen_at TEXT NOT NULL,      -- ISO-8601 UTC timestamp
    PRIMARY KEY (track_slug, start_date, facilities)
);
```

**Semantics:** An itinerary is considered "seen" when `(track_slug, start_date, facilities)` has been notified. Restarting the watcher reloads this store so previously reported availability is not re-notified.

---

## `logs/greatwalkbot.log`

Rotating log file (5 MB × 3 backups). Each line includes:

- UTC timestamp
- Log level (`INFO`, `WARNING`, `ERROR`)
- Message

Exceptions logged via `logger.exception()` include stack traces in the file handler output.

---

## `logs/status.json`

Atomic JSON snapshot of watcher health. Written via a temporary file + `os.replace()` so `gwbot status` never reads partial JSON.

### Schema version 3 (current)

Adds optional poll timing fields:

| Field | Type | Description |
|-------|------|-------------|
| `last_poll_track_timings` | array or null | Per-track fetch timings from the most recent poll (`track_slug`, `navigation_seconds`, `app_ready_seconds`, `capture_seconds`, `total_seconds`) |
| `last_poll_duration_seconds` | number or null | Wall-clock duration of the most recent poll cycle |

### Schema version 2

```json
{
  "schema_version": 2,
  "started_at": "2026-06-20T12:00:00Z",
  "state": "sleeping",
  "trip_name": "New Zealand Honeymoon",
  "polls_completed": 42,
  "successful_polls": 40,
  "failed_polls": 2,
  "browser_restarts": 1,
  "average_poll_duration_seconds": 18.4,
  "last_poll_at": "2026-06-20T14:30:00Z",
  "last_successful_poll_at": "2026-06-20T14:30:00Z",
  "last_error": {
    "at": "2026-06-20T13:00:00Z",
    "message": "No availability data captured",
    "track_slug": "milford"
  },
  "last_notification_attempt_at": "2026-06-20T14:30:01Z",
  "last_successful_notification_at": "2026-06-20T14:30:01Z",
  "last_notification_error": null
}
```

Schema version 1 files (without notification fields) still load; missing notification fields default to `null`.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | integer | Status schema version (currently `2`) |
| `started_at` | string | UTC ISO-8601 timestamp when this watcher process started |
| `state` | string | Current lifecycle state (see below) |
| `trip_name` | string \| null | Trip name from config |
| `polls_completed` | integer | Total poll cycles completed |
| `successful_polls` | integer | Poll cycles with at least one successful track check |
| `failed_polls` | integer | Poll cycles where every track check failed |
| `browser_restarts` | integer | Playwright session restarts after retry exhaustion |
| `average_poll_duration_seconds` | number | Mean wall-clock duration per poll cycle |
| `last_poll_at` | string \| null | UTC timestamp of most recent poll cycle end |
| `last_successful_poll_at` | string \| null | UTC timestamp of most recent successful poll |
| `last_error` | object \| null | Most recent per-track fetch error |
| `last_notification_attempt_at` | string \| null | UTC timestamp of most recent notification attempt |
| `last_successful_notification_at` | string \| null | UTC timestamp of most recent successful notification |
| `last_notification_error` | object \| null | Most recent notification delivery error (no secrets) |

### `state` values

| Value | Meaning |
|-------|---------|
| `starting` | Watcher initialising |
| `polling` | Poll cycle in progress |
| `sleeping` | Waiting between poll cycles |
| `stopping` | Shutdown requested, finishing current work |
| `stopped` | Process exiting cleanly |
| `error` | Most recent poll cycle failed entirely |

### `last_error` object

| Field | Type | Description |
|-------|------|-------------|
| `at` | string | UTC ISO-8601 timestamp |
| `message` | string | Error summary |
| `track_slug` | string \| null | Track that failed, if known |

### `last_notification_error` object

| Field | Type | Description |
|-------|------|-------------|
| `at` | string | UTC ISO-8601 timestamp |
| `message` | string | Error summary (never includes tokens or chat IDs) |

---

## Inspecting status

```bash
gwbot status
gwbot status --status-file /path/to/logs/status.json
```

---

## Notes

- Delete `data/seen.db` only if you want previously notified itineraries to trigger alerts again.
- `status.json` reflects the **current process**. After a crash, `state` may remain at its last written value until a new watcher starts.
- Log and database files are listed in `.gitignore` and must not be committed.
