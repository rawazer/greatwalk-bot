# GreatWalkBot

Open-source assistant for monitoring availability on the New Zealand DOC booking website.

**Status:** Milestone 1 — read-only availability checker.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13+.

```bash
uv sync
uv run playwright install chromium
uv run gwbot check --track milford --from 2026-12-07 --to 2026-12-14
```

If headless runs are blocked by AWS WAF, retry with a visible browser:

```bash
uv run gwbot check --track milford --from 2026-12-07 --to 2026-12-14 --headed
```

## Project layout

```
greatwalkbot/
├── docs/                  # Reverse-engineering notes
├── scripts/               # Investigation scripts (Milestone 0)
├── src/greatwalkbot/
│   ├── models.py          # Track, AvailabilityDay, AvailabilitySnapshot
│   ├── parsing.py         # Tyler RDR response parsing
│   ├── sources/           # Playwright and HTTP backends
│   └── cli.py             # gwbot CLI
└── tests/
```

## Architecture

Availability is fetched from the Tyler RDR endpoint `POST search/greatwalkplacefacility`. The default **Playwright** source loads the public DOC booking SPA (establishing an AWS WAF session), selects the track, and intercepts the grid request with your date range. An **HTTP** source implements the same interface for direct API calls (usually blocked by WAF).

## Documentation

- [Reverse engineering notes](docs/reverse_engineering.md)
- [API reference](docs/api.md)

## License

TBD
