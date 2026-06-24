# Roadmap

GreatWalkBot helps you **monitor** New Zealand DOC Great Walk availability and decide when to book manually. It is not a booking agent.

## Completed (v0.1.0)

- Trip and track preference configuration (YAML)
- Read-only DOC availability via Tyler RDR (`greatwalkplacefacility`)
- Playwright session manager with retry and browser recovery
- Complete-itinerary validation for Milford, Routeburn (both directions), and Kepler
- Trip-fit feasibility filtering across multiple desired walks
- Confirmed booking state in configuration (manual entry after you book)
- Telegram and console notifications with persistent dedupe
- Runtime metrics, structured logging, graceful shutdown
- CLI: `watch`, `check`, `plan-check`, `bookings`, `explain-availability`, `notify-test`, `preflight`, `status`
- systemd deployment guide and honeymoon configuration template
- GitHub Actions CI (tests)

## Explicitly deferred

These are **out of scope** for the current release and require separate design, review, and likely explicit user consent before any implementation:

| Capability | Notes |
|------------|-------|
| **Automatic booking** | Login, cart, payment, CAPTCHA, and occupancy locks are not implemented. Automatic booking would need a dedicated threat model, ToS review, and human-in-the-loop defaults. **Not part of v0.1.0.** |
| **Weighted scoring / ranking** | Priority is configured but not used to rank alerts beyond preference labels. |
| **Route optimisation** | No travel-between-trailheads or flight/accommodation planning. |
| **Additional notification channels** | Email, SMS, Pushover, etc. |
| **Official DOC API integration** | Continues to use reverse-engineered read-only endpoints. |
| **WAF bypass beyond browser context** | No CAPTCHA-solving or credential stuffing. |

## Automatic booking statement

**Automatic booking is not part of this release.** Any future work on login, cart actions, payment, or unattended reservation would be a separate project phase with its own design review, security assessment, and documentation. v0.1.0 is intentionally limited to read-only monitoring and manual booking assistance.

## Possible future work (not committed)

- Additional Great Walk itinerary metadata as DOC products change
- Preferred-date scoring for alert ordering (still without auto-booking)
- Health-check endpoint or external uptime integration
- Packaging as a container image

See [CHANGELOG.md](CHANGELOG.md) for release history.
