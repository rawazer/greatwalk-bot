# First run guide

This guide walks through deploying GreatWalkBot for the **New Zealand Honeymoon 2026** template. The same steps apply to any trip configuration.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) and Python 3.13+
- Outbound HTTPS to `bookings.doc.govt.nz`
- A machine that stays on for the monitoring period (see [deployment.md](deployment.md))

```bash
uv sync
uv run playwright install chromium
```

## 1. Copy the honeymoon template

```bash
cp examples/nz-honeymoon-2026.yaml config.yaml
```

Edit `config.yaml` if your dates or tracks differ. **Do not put secrets in this file.**

## 2. Verify the trip plan offline

```bash
uv run gwbot plan-check config.yaml
```

Expect `Feasibility: YES`. This checks that Milford, Routeburn, and Kepler can fit in your travel window in principle — it does not contact DOC.

## 3. Configure Telegram (optional)

1. Create a bot via [@BotFather](https://t.me/BotFather) and copy the token.
2. Obtain your chat ID (see [telegram.md](telegram.md)).
3. Export environment variables — never commit them:

```bash
export GREATWALKBOT_TELEGRAM_BOT_TOKEN="your-token"
export GREATWALKBOT_TELEGRAM_CHAT_ID="your-chat-id"
```

4. Enable Telegram in `config.yaml`:

```yaml
notifications:
  console: true
  telegram:
    enabled: true
```

## 4. Send a test notification

```bash
uv run gwbot notify-test config.yaml
```

Confirms console and/or Telegram delivery without contacting DOC.

## 5. Run preflight

```bash
uv run gwbot preflight config.yaml
```

This validates configuration, trip feasibility, notifier setup, and performs one **read-only** availability fetch per unconfirmed track.

Add `--send-test-notification` to include a test message in the same run:

```bash
uv run gwbot preflight config.yaml --send-test-notification
```

Preflight does **not** send ordinary availability alerts or update dedupe state. Finding no matching availability is normal and reported as a warning only.

Use `--headed` if AWS WAF blocks headless fetches.

Exit code `0` means ready; `1` means fix the reported errors before deploying.

## 6. Deploy with systemd

See [deployment.md](deployment.md) for the full VM setup (environment file, unit placeholders, enable commands).

```bash
# Edit deploy/greatwalk-bot.service placeholders, then:
sudo cp deploy/greatwalk-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now greatwalk-bot
```

For ongoing use after deploy, see [operations.md](operations.md).

## 7. Inspect status and logs

```bash
uv run gwbot status
tail -f logs/greatwalkbot.log
```

Runtime files are described in [runtime-state.md](runtime-state.md).

## 8. When an alert arrives

1. Read the message — it means a **complete itinerary** was verified for your party size at poll time, not that DOC holds a reservation for you.
2. Open [bookings.doc.govt.nz](https://bookings.doc.govt.nz/Web/) promptly and book manually.
3. Availability can disappear quickly; treat alerts as “worth acting on now.”

## 9. Record a manual booking

After you book on DOC, add a `confirmed_booking` block to that track in `config.yaml`:

```yaml
  - track: routeburn
    # ... existing preferences ...
    confirmed_booking:
      start_date: 2026-12-10
      nights: 2
      direction: routeburn-shelter-to-divide
      notes: "Booked manually on DOC"
```

Restart the watcher:

```bash
sudo systemctl restart greatwalk-bot
```

The bot stops monitoring that track and plans around the confirmed dates. Details: [bookings.md](bookings.md).

## Quick reference

| Command | Contacts DOC? | Purpose |
|---------|---------------|---------|
| `plan-check` | No | Offline feasibility |
| `notify-test` | No | Test notifications |
| `preflight` | Yes (read-only fetch) | Pre-deploy readiness |
| `watch` | Yes (ongoing) | Production monitoring |
| `bookings` | No | List confirmed bookings |

## What this release does not do

GreatWalkBot v0.1.0 does not log in, add to cart, pay, or book automatically. See [ROADMAP.md](../ROADMAP.md).
