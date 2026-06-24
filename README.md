# GreatWalkBot

Open-source assistant for planning and monitoring New Zealand DOC Great Walk trips.

**Status:** Milestone 7 — confirmed booking state.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13+.

```bash
uv sync
uv run playwright install chromium

# One-shot availability check
uv run gwbot check --track milford --from 2026-12-07 --to 2026-12-14

# Monitor a whole trip
cp config.example.yaml config.yaml
uv run gwbot watch config.yaml

# Check runtime metrics (while watcher is running)
uv run gwbot status

# Test Telegram/console notifications (no DOC contact)
uv run gwbot notify-test config.yaml

# Inspect trip-fit feasibility (no DOC contact)
uv run gwbot plan-check config.yaml

# List confirmed bookings (no DOC contact)
uv run gwbot bookings config.yaml
```

Use `--headed` if AWS WAF blocks headless traffic. Use `gwbot watch config.yaml --once` for a single poll cycle.

## Trip configuration

The configuration describes a **complete trip** — who is travelling, when you are in New Zealand, and which Great Walks matter to you — rather than isolated polling rules per track.

```yaml
polling_interval: 300

trip:
  name: New Zealand Honeymoon

party:
  adults: 2

travel_window:
  start: 2026-11-29
  end: 2026-12-31

tracks:
  - track: milford
    priority: 100
    complete_itinerary_only: true
    preferred_start_dates:
      - 2026-12-07
      - 2026-12-08
    acceptable_start_range:
      start: 2026-12-03
      end: 2026-12-23

retry:
  max_attempts: 3
  base_delay_seconds: 1.0
  max_delay_seconds: 60.0
```

Each track defines:

- **priority** — relative importance (for future scoring; not used yet)
- **preferred_start_dates** or **preferred_start_range** — ideal start dates
- **acceptable_start_range** — wider window still worth considering
- **complete_itinerary_only** — require a full-itinerary booking (enforced for fixed-night tracks)
- **direction** — forward, reverse, or either (modelled now; matching uses it in a later milestone)

The overall **travel_window** bounds when you are in the country. Track date ranges must fall within it.

The legacy `party_size` / `preferred` / `acceptable` format is still supported and is normalised into the trip model at load time.

## Production features

Watch mode is designed for unattended long-running use:

| Feature | Details |
|---------|---------|
| **Session manager** | Reuses a single Playwright browser across poll cycles; restarts on failure |
| **Retry policy** | Exponential backoff with jitter for transient errors; fail-fast for config errors |
| **Structured logging** | Console output plus rotating log file at `logs/greatwalkbot.log` |
| **Persistent dedupe** | SQLite store at `data/seen.db` survives restarts |
| **Metrics** | Runtime stats written to `logs/status.json`; inspect with `gwbot status` |
| **Graceful shutdown** | Ctrl+C finishes the current poll, closes the browser, and flushes state |
| **Telegram alerts** | Optional notifications via env vars; see [Telegram setup](docs/telegram.md) |
| **Trip-fit filtering** | Optional multi-walk feasibility check; see [trip-fit](docs/trip-fit.md) |
| **Confirmed bookings** | Record manual DOC bookings in config; see [bookings](docs/bookings.md) |

## Run unattended

For a home server or VPS, see **[Deployment guide](docs/deployment.md)** — install as a `systemd --user` service, verify with `gwbot status`, and inspect [runtime state files](docs/runtime-state.md).

```bash
cp deploy/greatwalkbot.service ~/.config/systemd/user/
systemctl --user enable --now greatwalkbot.service
gwbot status
```

The host must stay powered on and connected for the full monitoring period.

## Project layout

```
greatwalkbot/
├── config.example.yaml
├── deploy/                # systemd unit example
├── logs/                  # runtime logs and status.json (created at watch time)
├── data/                  # persistent dedupe database (created at watch time)
├── src/greatwalkbot/
│   ├── domain/            # Trip, Party, TrackPreference, TravelWindow, ...
│   ├── infra/             # Retry, shutdown, error types
│   ├── config/            # YAML loading
│   ├── monitoring/        # Matcher, dedupe, metrics, watch loop
│   ├── notifications/     # Notifier interface
│   └── sources/           # SessionManager, Playwright, HTTP
└── tests/
```

## Documentation

- [Deployment guide](docs/deployment.md)
- [Runtime state contract](docs/runtime-state.md)
- [Telegram notifications](docs/telegram.md)
- [Trip-fit evaluation](docs/trip-fit.md)
- [Confirmed bookings](docs/bookings.md)
- [Reverse engineering notes](docs/reverse_engineering.md)
- [API reference](docs/api.md)

## License

TBD
