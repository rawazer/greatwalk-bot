# Deployment guide (Ubuntu / Debian)

This guide runs GreatWalkBot as a **user-level systemd service** on a Linux machine that stays powered on and connected to the internet. The watcher polls DOC availability in the background; it does not book huts for you.

> **Important:** The machine running this service must remain on and network-connected for the full period you want to monitor availability. A laptop that sleeps, or a VM that is stopped, will miss polls.

## Prerequisites

- Ubuntu 22.04+ or Debian 12+ (other systemd distros should work with minor adjustments)
- Python 3.13+ (installed via `uv`)
- Outbound HTTPS access to `bookings.doc.govt.nz`

## 1. Install system dependencies

Playwright Chromium requires OS libraries on Linux:

```bash
sudo apt update
sudo apt install -y curl ca-certificates git \
  libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
  libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
  libgbm1 libasound2 libpango-1.0-0 libcairo2
```

Install [uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
```

## 2. Clone and install

```bash
cd ~
git clone https://github.com/YOUR_ORG/greatwalk-bot.git
cd greatwalk-bot
uv sync
uv run playwright install chromium
```

Replace the clone URL with your fork or mirror if needed.

## 3. Configure

```bash
cp config.example.yaml config.yaml
# Edit config.yaml for your trip dates, tracks, and party size
```

`config.yaml` is gitignored and must not be committed.

### Optional: Telegram notifications

See [telegram.md](telegram.md) for full setup. Enable in `config.yaml`:

```yaml
notifications:
  console: true
  telegram:
    enabled: true
    bot_token_env: GREATWALKBOT_TELEGRAM_BOT_TOKEN
    chat_id_env: GREATWALKBOT_TELEGRAM_CHAT_ID
```

Store secrets outside the repo:

```bash
mkdir -p ~/.config/greatwalkbot
chmod 700 ~/.config/greatwalkbot
cat > ~/.config/greatwalkbot/env <<'EOF'
GREATWALKBOT_TELEGRAM_BOT_TOKEN=your-bot-token
GREATWALKBOT_TELEGRAM_CHAT_ID=your-chat-id
EOF
chmod 600 ~/.config/greatwalkbot/env
```

Test before starting the watcher:

```bash
set -a && source ~/.config/greatwalkbot/env && set +a
uv run gwbot notify-test config.yaml
```

## 4. One-shot health check

Verify Playwright can reach DOC before starting the long-running watcher:

```bash
uv run gwbot check --track milford --from 2026-12-07 --to 2026-12-14
```

If headless mode is blocked by WAF, retry with `--headed` (requires a display; not typical on a headless VPS):

```bash
uv run gwbot check --track milford --from 2026-12-07 --to 2026-12-14 --headed
```

Run a single watch cycle to confirm config parsing and runtime state:

```bash
uv run gwbot watch config.yaml --once
ls -la logs/ data/
uv run gwbot status
```

You should see `logs/greatwalkbot.log`, `logs/status.json`, and `data/seen.db`.

## 5. Run manually (foreground)

```bash
uv run gwbot watch config.yaml
```

Press `Ctrl+C` to stop. The watcher finishes the current poll, closes the browser, and flushes state.

## 6. Install as a user systemd service

Edit the example unit to match your paths:

```bash
# Default assumes repo at ~/greatwalk-bot and uv at ~/.local/bin/uv
nano deploy/greatwalkbot.service
```

Copy to your user systemd directory:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/greatwalkbot.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now greatwalkbot.service
```

Enable lingering so the service survives logout (required on most servers):

```bash
sudo loginctl enable-linger "$USER"
```

### Custom paths and Telegram secrets

Edit `WorkingDirectory` and `ExecStart` in the unit file:

```ini
WorkingDirectory=/home/youruser/greatwalk-bot
ExecStart=/home/youruser/.local/bin/uv run gwbot watch /home/youruser/greatwalk-bot/config.yaml
EnvironmentFile=/home/youruser/.config/greatwalkbot/env
```

Create the environment file outside the repository (`chmod 600`). systemd loads variables before starting `gwbot`; never put tokens in the unit file itself if it lives in a shared or version-controlled location.

## 7. View logs and status

```bash
# Follow service logs (stdout from gwbot)
journalctl --user -u greatwalkbot.service -f

# Application log file
tail -f ~/greatwalk-bot/logs/greatwalkbot.log

# Health snapshot
uv run gwbot status
```

## 8. Restart after config changes

```bash
systemctl --user restart greatwalkbot.service
```

## 9. Runtime state locations

All paths are relative to `WorkingDirectory` in the service unit:

| Path | Purpose |
|------|---------|
| `config.yaml` | Your trip configuration (not in git) |
| `data/seen.db` | Persistent notification deduplication |
| `logs/greatwalkbot.log` | Rotating application log |
| `logs/status.json` | Health metrics for `gwbot status` |

See [runtime-state.md](runtime-state.md) for the full JSON schema.

## Troubleshooting

| Symptom | Action |
|---------|--------|
| Service fails immediately | `journalctl --user -u greatwalkbot.service -n 50` |
| No availability captured | Try `gwbot check` with `--headed`; check WAF/network |
| Duplicate notifications after edit | Normal if you deleted `data/seen.db` |
| Status file stale | Watcher not running, or crashed before flush |

## Security notes

- Do not commit `config.yaml`, `logs/`, `data/`, or secret files.
- Run as an unprivileged user; no root required for `--user` services.
- The watcher only reads public DOC availability; it does not store credentials.
