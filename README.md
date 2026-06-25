# GreatWalkBot

Open-source assistant for planning and monitoring New Zealand DOC Great Walk trips.

**Status:** v0.1.0 — release-ready; SPA reliability hardened (bounded navigation waits).

**New here?** Start with the **[First run guide](docs/first-run.md)** — copy the honeymoon template, run `plan-check` and `preflight`, configure Telegram, and deploy.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13+.

```bash
uv sync
uv run playwright install chromium

# Copy the honeymoon template
cp examples/nz-honeymoon-2026.yaml config.yaml

# Offline feasibility check
uv run gwbot plan-check config.yaml

# Pre-deploy readiness (read-only DOC fetch per track)
uv run gwbot preflight config.yaml

# Monitor a whole trip
uv run gwbot watch config.yaml

# Check runtime metrics (while watcher is running)
uv run gwbot status
```

Use `--headed` if AWS WAF blocks headless traffic. Use `gwbot watch config.yaml --once` for a single poll cycle.

At INFO level, each track logs one evaluation summary after the checked line (candidate/complete/incomplete counts and grouped rejection reasons). Individual rejected start dates and directions are logged at DEBUG — set `GREATWALKBOT_LOG_LEVEL=DEBUG` to see them in the console and log file.

### One-off Telegram alert test (Lake Waikaremoana)

For a temporary end-to-end Telegram validation without touching the honeymoon `config.yaml`, use `config.test-lake-waikaremoana.yaml` with an isolated dedupe database:

```bash
export GREATWALKBOT_TELEGRAM_BOT_TOKEN="..."
export GREATWALKBOT_TELEGRAM_CHAT_ID="..."
uv run gwbot watch config.test-lake-waikaremoana.yaml --once --seen-db data/seen-waikaremoana-test.db
```

Restore normal monitoring with `uv run gwbot watch config.yaml` (or your systemd unit). See comments in the test config for expected output and dedupe reset.

## Trip configuration

The configuration describes a **complete trip** — who is travelling, when you are in New Zealand, and which Great Walks matter to you — rather than isolated polling rules per track.

Use `examples/nz-honeymoon-2026.yaml` or `config.example.yaml` as a starting point.

Each track defines:

- **priority** — relative importance (for future scoring; not used yet)
- **preferred_start_dates** or **preferred_start_range** — ideal start dates
- **acceptable_start_range** — wider window still worth considering
- **complete_itinerary_only** — require a full-itinerary booking (validated against DOC facility data)
- **direction** — forward, reverse, or either (Routeburn)
- **confirmed_booking** — optional, after you book manually on DOC

The overall **travel_window** bounds when you are in the country. Track date ranges must fall within it.

## Production features

Watch mode is designed for unattended long-running use:

| Feature | Details |
|---------|---------|
| **Session manager** | Reuses a single Playwright browser across poll cycles; restarts on failure |
| **Retry policy** | Exponential backoff with jitter for transient errors; fail-fast for config errors |
| **Structured logging** | Concise INFO summaries per track; set `GREATWALKBOT_LOG_LEVEL=DEBUG` for per-date rejection detail. Rotating log file at `logs/greatwalkbot.log` |
| **Persistent dedupe** | SQLite store at `data/seen.db` survives restarts |
| **Runtime metrics** | `logs/status.json`; inspect with `gwbot status` |
| **Graceful shutdown** | Ctrl+C finishes the current poll, closes the browser, and flushes state |
| **Telegram alerts** | Optional notifications via env vars; see [Telegram setup](docs/telegram.md) |
| **Trip-fit filtering** | Multi-walk feasibility; see [trip-fit](docs/trip-fit.md) |
| **Confirmed bookings** | Manual DOC bookings in config; see [bookings](docs/bookings.md) |
| **Complete-itinerary validation** | Every required hut night verified; see [itinerary-availability](docs/itinerary-availability.md) |
| **Preflight** | One-command readiness check before deploy |

## Run unattended

For a home server or VPS, see **[Deployment guide](docs/deployment.md)** and **[First run guide](docs/first-run.md)**.

```bash
cp deploy/greatwalkbot.service ~/.config/systemd/user/
systemctl --user enable --now greatwalkbot.service
gwbot status
```

The host must stay powered on and connected for the full monitoring period.

## CLI reference

| Command | DOC contact | Purpose |
|---------|-------------|---------|
| `watch` | Yes (ongoing) | Production monitoring |
| `preflight` | Yes (one read-only fetch per track) | Pre-deploy readiness |
| `plan-check` | No | Offline trip feasibility |
| `notify-test` | No | Test notifications |
| `bookings` | No | List confirmed bookings |
| `explain-availability` | Yes (one date) | Diagnose itinerary validation |
| `check` | Yes | Ad-hoc date range check |
| `status` | No | Runtime metrics |

## Project layout

```
greatwalkbot/
├── examples/nz-honeymoon-2026.yaml
├── config.example.yaml
├── CHANGELOG.md
├── ROADMAP.md
├── deploy/                # systemd unit example
├── logs/                  # runtime logs and status.json
├── data/                  # persistent dedupe database
├── src/greatwalkbot/
└── tests/
```

## Documentation

- **[First run guide](docs/first-run.md)** — recommended starting point
- [Deployment guide](docs/deployment.md)
- [Runtime state contract](docs/runtime-state.md)
- [Telegram notifications](docs/telegram.md)
- [Trip-fit evaluation](docs/trip-fit.md)
- [Confirmed bookings](docs/bookings.md)
- [Complete-itinerary availability](docs/itinerary-availability.md)
- [Reverse engineering notes](docs/reverse_engineering.md)
- [API reference](docs/api.md)
- [Roadmap](ROADMAP.md) · [Changelog](CHANGELOG.md)

## License

TBD
