# Changelog

All notable changes to GreatWalkBot are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-06-20

First release for manual Great Walk booking assistance.

### Added

- **Trip configuration** — YAML trip plans with party size, travel window, per-track preferences, priorities, and direction settings.
- **Availability monitoring** — Long-running `gwbot watch` with Playwright (default) or HTTP source, session reuse, retry policy, and graceful shutdown.
- **Complete-itinerary validation** — Alerts only when every required hut night has capacity for the configured party (Milford, Routeburn both directions, Kepler).
- **Trip-fit evaluation** — Optional filtering so alerts leave plausible room for other configured walks within the travel window.
- **Confirmed bookings** — Record manual DOC bookings in config; skip monitoring booked tracks and plan around confirmed dates.
- **Telegram notifications** — Optional alerts via environment-variable credentials; console fallback.
- **Persistent dedupe** — SQLite store so restarts do not re-alert for known itineraries.
- **Runtime metrics** — `logs/status.json` and `gwbot status` for poll health and notification delivery.
- **CLI tools** — `check`, `plan-check`, `bookings`, `explain-availability`, `notify-test`, and `preflight`.
- **Deployment** — systemd user unit example and deployment documentation.
- **Honeymoon template** — `examples/nz-honeymoon-2026.yaml` for a two-adult New Zealand trip (Nov–Dec 2026).

### Security

- Secrets are read from environment variables only; no tokens in configuration files.

### Known limitations

- Does not log in, add to cart, pay, or book on DOC.
- AWS WAF may block headless HTTP; Playwright is the supported production fetch path.
- “Available” means verified from read-only DOC data at poll time — not a reservation.

[0.1.0]: https://github.com/YOUR_ORG/greatwalk-bot/releases/tag/v0.1.0
