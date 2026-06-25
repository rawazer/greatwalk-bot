# Deploying greatwalk-bot on a new VM

This guide takes a **fresh Linux VM** from blank disk to a **persistent systemd service** that polls DOC Great Walk availability in the background. It does not book huts for you.

> **Important:** The machine must stay powered on and network-connected for the full monitoring period. A stopped VM or sleeping laptop will miss polls.

For updates, logs, and restarts after deployment, see **[Operations](operations.md)**.

---

## 1. Prerequisites and assumptions

| Requirement | Details |
|-------------|---------|
| **Distributions** | **Ubuntu 22.04+** or **Debian 12+** (primary; commands below use `apt`). **Oracle Linux 8/9** and **RHEL 8/9** are supported with `dnf` equivalents noted where they differ. The application is not Oracle-specific — Oracle Cloud VMs are a common host, not a code dependency. |
| **User** | A normal **non-root** Linux account for cloning and running the app (examples use `greatwalk`). systemd runs the service as that user. |
| **Network** | Outbound HTTPS to `bookings.doc.govt.nz` and the Telegram API if notifications are enabled. |
| **Git** | To clone the repository. |
| **Python** | **3.13+** (installed automatically by [uv](https://docs.astral.sh/uv/) during `uv sync`). |
| **uv** | Package manager used by this repo (`uv sync`, `uv run gwbot …`). |
| **Playwright** | Chromium browser + OS libraries required for the default `playwright` availability source. |

Assumed paths in examples (adjust to your VM):

| Placeholder | Example value |
|-------------|---------------|
| Service user | `greatwalk` |
| Repo directory | `/home/greatwalk/greatwalk-bot` |
| Environment file | `/etc/greatwalk-bot/greatwalk-bot.env` |

---

## 2. Initial machine setup

Run these steps as your service user unless noted.

### 2.1 Update packages and install base tools

**Ubuntu / Debian:**

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git curl ca-certificates
```

**Oracle Linux / RHEL:**

```bash
sudo dnf update -y
sudo dnf install -y git curl ca-certificates
```

### 2.2 Create the service user (optional but recommended)

Skip if you already have the account you want to use.

```bash
sudo useradd -m -s /bin/bash greatwalk
sudo su - greatwalk
```

### 2.3 Install uv (durable, non-interactive path)

Install uv into the service user's home so the path is stable for manual commands and documentation:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Confirm the absolute path (used in examples below):

```bash
/home/greatwalk/.local/bin/uv --version
```

systemd in this guide invokes **`/home/greatwalk/greatwalk-bot/.venv/bin/gwbot`** directly (created by `uv sync`), so the service does **not** depend on shell `PATH` initialization. Use the absolute `uv` path for install/sync commands in scripts and cron.

### 2.4 Clone the repository

```bash
cd ~
git clone https://github.com/YOUR_ORG/greatwalk-bot.git
cd greatwalk-bot
```

Replace the URL with your fork or mirror.

### 2.5 Install Python dependencies

```bash
/home/greatwalk/.local/bin/uv sync
```

This creates `.venv/` in the repo with the `gwbot` CLI at `.venv/bin/gwbot`.

### 2.6 Install Playwright Chromium and OS dependencies

Install the browser binary into the project environment:

```bash
/home/greatwalk/.local/bin/uv run playwright install chromium
```

Install required system libraries. **Preferred:** use Playwright's helper (requires sudo):

```bash
/home/greatwalk/.local/bin/uv run playwright install-deps chromium
```

**Ubuntu / Debian manual alternative** (if `install-deps` is unavailable):

```bash
sudo apt install -y \
  libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
  libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
  libgbm1 libasound2 libpango-1.0-0 libcairo2
```

**Oracle Linux / RHEL:** run `playwright install-deps chromium` first; if packages are missing, install the closest equivalents from your distribution's repositories or enable **EPEL** / **CodeReady Builder** as needed. Package names differ from Debian — do not blindly translate the `apt` list.

Verify dependencies without modifying the system:

```bash
/home/greatwalk/.local/bin/uv run playwright install-deps --dry-run chromium
```

Non-zero exit means required packages are still missing.

---

## 3. Configuration

### 3.1 Create `config.yaml`

```bash
cd ~/greatwalk-bot
cp examples/nz-honeymoon-2026.yaml config.yaml
# Or: cp config.example.yaml config.yaml
```

`config.yaml` is gitignored. **Never commit it** — it describes your trip but must not contain Telegram tokens.

### 3.2 Edit trip settings

Adjust at minimum:

- **`polling_interval`** — seconds between poll cycles (e.g. `300`).
- **`party.adults`** — party size sent to DOC search forms.
- **`travel_window`** — when you are in New Zealand.
- **`tracks`** — which walks to monitor, date preferences, `complete_itinerary_only`, direction (Routeburn), etc.

Minimal safe example (placeholder dates only):

```yaml
polling_interval: 300

trip:
  name: Example trip

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
    acceptable_start_range:
      start: 2026-12-03
      end: 2026-12-23

notifications:
  console: true
  telegram:
    enabled: true
    bot_token_env: GREATWALKBOT_TELEGRAM_BOT_TOKEN
    chat_id_env: GREATWALKBOT_TELEGRAM_CHAT_ID
```

See [first-run.md](first-run.md) and [itinerary-availability.md](itinerary-availability.md) for field details.

### 3.3 Validate before starting the service

Offline feasibility (no DOC contact):

```bash
/home/greatwalk/.local/bin/uv run gwbot plan-check config.yaml
```

Pre-deploy readiness (read-only DOC fetch per track, validates notifiers):

```bash
/home/greatwalk/.local/bin/uv run gwbot preflight config.yaml
```

Optional Telegram test during preflight:

```bash
/home/greatwalk/.local/bin/uv run gwbot preflight config.yaml --send-test-notification
```

Exit code `0` means ready; `1` means fix reported errors first.

If AWS WAF blocks headless Chromium, add `--headed` to preflight (requires a display — uncommon on headless VPS).

---

## 4. Environment file / Telegram secrets

Secrets are read from **environment variables only**, never from YAML. See [telegram.md](telegram.md) for bot setup.

### 4.1 Create the environment file

As root:

```bash
sudo mkdir -p /etc/greatwalk-bot
sudo nano /etc/greatwalk-bot/greatwalk-bot.env
```

Example contents (**placeholder values only**):

```bash
# Required when notifications.telegram.enabled is true in config.yaml
GREATWALKBOT_TELEGRAM_BOT_TOKEN=000000000:REPLACE_WITH_BOTFATHER_TOKEN
GREATWALKBOT_TELEGRAM_CHAT_ID=000000000

# Optional
# GREATWALKBOT_LOG_LEVEL=INFO
# GREATWALKBOT_SEEN_DB=/home/greatwalk/greatwalk-bot/data/seen.db
# GREATWALKBOT_DIAGNOSTICS_RETENTION=7
```

| Variable | Required | Purpose |
|----------|----------|---------|
| `GREATWALKBOT_TELEGRAM_BOT_TOKEN` | When Telegram enabled | Bot token from [@BotFather](https://t.me/BotFather) |
| `GREATWALKBOT_TELEGRAM_CHAT_ID` | When Telegram enabled | Target chat ID |
| `GREATWALKBOT_LOG_LEVEL` | No | `INFO` (default) or `DEBUG` for per-date rejection detail |
| `GREATWALKBOT_SEEN_DB` | No | Override dedupe SQLite path (default: `data/seen.db` under WorkingDirectory) |
| `GREATWALKBOT_DIAGNOSTICS_RETENTION` | No | Days to retain diagnostic artifacts |

Config keys `bot_token_env` and `chat_id_env` in YAML are **names** of these variables, not the secrets themselves.

### 4.2 Permissions

```bash
sudo chown root:root /etc/greatwalk-bot/greatwalk-bot.env
sudo chmod 600 /etc/greatwalk-bot/greatwalk-bot.env
```

systemd reads `EnvironmentFile` as root before dropping privileges — `root:root` mode `600` is correct. **Never commit this file to Git.**

If Telegram is disabled (`notifications.telegram.enabled: false`), the file may be omitted or left empty; the unit uses `EnvironmentFile=-…` so a missing file does not prevent startup.

### 4.3 Test Telegram delivery (manual)

```bash
set -a && source /etc/greatwalk-bot/greatwalk-bot.env && set +a
cd ~/greatwalk-bot
/home/greatwalk/.local/bin/uv run gwbot notify-test config.yaml
```

This does not contact DOC or launch Playwright.

---

## 5. systemd service

The repository ships a **system** unit template at `deploy/greatwalk-bot.service`. It runs as your dedicated user, loads `/etc/greatwalk-bot/greatwalk-bot.env`, and invokes the project venv directly (no shell, no `PATH`).

### 5.1 Render the unit file

Ensure the service user owns the repo (needed for `logs/` and `data/`):

```bash
sudo chown -R greatwalk:greatwalk /home/greatwalk/greatwalk-bot
```

Edit placeholders in the template, or use `sed` after copying:

```bash
cd ~/greatwalk-bot

GREATWALKBOT_USER=greatwalk
GREATWALKBOT_HOME=/home/greatwalk
GREATWALKBOT_REPO=/home/greatwalk/greatwalk-bot

sed \
  -e "s|__GREATWALKBOT_USER__|${GREATWALKBOT_USER}|g" \
  -e "s|__GREATWALKBOT_HOME__|${GREATWALKBOT_HOME}|g" \
  -e "s|__GREATWALKBOT_REPO__|${GREATWALKBOT_REPO}|g" \
  deploy/greatwalk-bot.service > /tmp/greatwalk-bot.service

sudo cp /tmp/greatwalk-bot.service /etc/systemd/system/greatwalk-bot.service
rm /tmp/greatwalk-bot.service
```

Ensure `.venv/bin/gwbot` exists (`uv sync` must have completed successfully).

### 5.2 Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now greatwalk-bot
```

### 5.3 Status and logs

```bash
sudo systemctl status greatwalk-bot --no-pager
sudo journalctl -u greatwalk-bot -f
```

### 5.4 Stop / restart / disable

```bash
sudo systemctl stop greatwalk-bot
sudo systemctl restart greatwalk-bot
sudo systemctl disable greatwalk-bot
```

### 5.5 User-level alternative (home server)

For a personal machine without sudo, you can use a **user** systemd unit instead:

```bash
mkdir -p ~/.config/systemd/user
# Edit deploy/greatwalk-bot.service paths manually, change WantedBy=default.target,
# remove User=/Group= lines, set EnvironmentFile=%h/.config/greatwalkbot/env
cp deploy/greatwalk-bot.service ~/.config/systemd/user/greatwalk-bot.service
systemctl --user daemon-reload
systemctl --user enable --now greatwalk-bot
sudo loginctl enable-linger "$USER"
```

See [telegram.md](telegram.md) for a user-level environment file at `~/.config/greatwalkbot/env`.

---

## 6. Verification checklist

Run these after the service is installed (or before enable, for manual validation).

| Step | Command | Expected outcome |
|------|---------|------------------|
| CLI available | `/home/greatwalk/greatwalk-bot/.venv/bin/gwbot --help` | Help text; exit 0 |
| Config offline | `uv run gwbot plan-check config.yaml` | `Feasibility: YES` (or fix config) |
| One poll cycle | `uv run gwbot watch config.yaml --once` | Completes without error; writes `logs/` and `data/seen.db` |
| Optional debug fetch | `uv run gwbot debug-search config.yaml --track milford --date 2026-12-07` | Single-track search diagnostics (contacts DOC) |
| Telegram | `uv run gwbot notify-test config.yaml` | Test message in Telegram (with env file sourced) |
| Service active | `sudo systemctl status greatwalk-bot` | `active (running)` |
| Journal | `sudo journalctl -u greatwalk-bot -n 20 --no-pager` | Poll cycle log lines, no crash loop |
| Runtime metrics | `uv run gwbot status` | Recent timestamps in `logs/status.json` |

If headless fetches fail with WAF errors, retry with `--headed` on manual commands only.

---

## 7. Updating the deployment

When pulling new releases:

```bash
cd /home/greatwalk/greatwalk-bot
git pull
/home/greatwalk/.local/bin/uv sync
sudo systemctl restart greatwalk-bot
```

If Playwright or browser requirements changed upstream, re-run:

```bash
/home/greatwalk/.local/bin/uv run playwright install chromium
/home/greatwalk/.local/bin/uv run playwright install-deps chromium
```

See **[Operations](operations.md)** for day-to-day commands.

---

## Runtime state locations

All paths are relative to `WorkingDirectory` (`__GREATWALKBOT_REPO__`):

| Path | Purpose |
|------|---------|
| `config.yaml` | Trip configuration (not in git) |
| `data/seen.db` | Persistent notification deduplication |
| `logs/greatwalkbot.log` | Rotating application log |
| `logs/status.json` | Health metrics for `gwbot status` |

See [runtime-state.md](runtime-state.md) for the status JSON schema.

---

## Security notes

- Do not commit `config.yaml`, `logs/`, `data/`, or `/etc/greatwalk-bot/greatwalk-bot.env`.
- Run as an unprivileged user; the watcher only reads public DOC availability.
- Restrict environment file permissions (`chmod 600`).
- Revoke leaked bot tokens via [@BotFather](https://t.me/BotFather).

---

## Oracle Cloud notes

Oracle Cloud Infrastructure free-tier VMs often run **Oracle Linux**. This project does not depend on OCI APIs or shapes — any Linux VPS with outbound HTTPS works the same way. Typical caveats:

- Ensure **ingress** firewall rules allow **outbound** HTTPS (default on most images).
- Arm-based Ampere instances work if Python 3.13+ wheels are available for your architecture (`uv sync` will report errors otherwise).
- Use `dnf` and `playwright install-deps` rather than copying Ubuntu `apt` package names verbatim.
