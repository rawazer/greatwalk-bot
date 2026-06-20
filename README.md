# GreatWalkBot

Open-source assistant for monitoring availability on the New Zealand DOC booking website.

**Status:** Milestone 2 — configuration-driven watch mode.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13+.

```bash
uv sync
uv run playwright install chromium

# One-shot check
uv run gwbot check --track milford --from 2026-12-07 --to 2026-12-14

# Long-running watch (copy and edit config first)
cp config.example.yaml config.yaml
uv run gwbot watch config.yaml
```

Use `--headed` if AWS WAF blocks headless traffic. Use `gwbot watch config.yaml --once` for a single poll cycle.

## Project layout

```
greatwalkbot/
├── config.example.yaml    # Sample watch configuration
├── docs/
├── src/greatwalkbot/
│   ├── config/            # YAML config loading
│   ├── monitoring/        # Matcher, dedupe, watch loop
│   ├── notifications/     # Notifier interface (console today)
│   ├── sources/           # Playwright and HTTP backends
│   └── cli.py
└── tests/
```

## Watch configuration

```yaml
party_size: 2
polling_interval: 300  # seconds

tracks:
  - track: milford
    preferred:
      - from: 2026-12-07
        to: 2026-12-14
    acceptable:
      - from: 2026-12-01
        to: 2026-12-31
```

The watcher polls each track over its acceptable date ranges, matches availability against preferred/acceptable windows and party size, logs timestamped check results, and notifies only when **new** itineraries appear.

## Documentation

- [Reverse engineering notes](docs/reverse_engineering.md)
- [API reference](docs/api.md)

## License

TBD
