# GreatWalkBot

Open-source assistant for planning and monitoring New Zealand DOC Great Walk trips.

**Status:** Milestone 3 — trip planning domain model.

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
```

Each track defines:

- **priority** — relative importance (for future scoring; not used yet)
- **preferred_start_dates** or **preferred_start_range** — ideal start dates
- **acceptable_start_range** — wider window still worth considering
- **complete_itinerary_only** — require a full-itinerary booking (enforced for fixed-night tracks)
- **direction** — forward, reverse, or either (modelled now; matching uses it in a later milestone)

The overall **travel_window** bounds when you are in the country. Track date ranges must fall within it.

The legacy `party_size` / `preferred` / `acceptable` format is still supported and is normalised into the trip model at load time.

## Project layout

```
greatwalkbot/
├── config.example.yaml
├── src/greatwalkbot/
│   ├── domain/            # Trip, Party, TrackPreference, TravelWindow, ...
│   ├── config/            # YAML loading
│   ├── monitoring/        # Matcher, dedupe, watch loop
│   ├── notifications/     # Notifier interface
│   └── sources/           # Playwright and HTTP backends
└── tests/
```

## Documentation

- [Reverse engineering notes](docs/reverse_engineering.md)
- [API reference](docs/api.md)

## License

TBD
