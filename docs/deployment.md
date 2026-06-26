# Deploying greatwalk-bot on a new VM

This guide takes a **fresh Linux VM** from blank disk to a **persistent systemd service** that polls DOC Great Walk availability in the background. It does not book huts for you.

> **Important:** The machine must stay powered on and network-connected for the full monitoring period. A stopped VM or sleeping laptop will miss polls.

For updates, logs, and restarts after deployment, see **[Operations](operations.md)**.

---

## Production layout

The official production target is:

| Item | Path |
|------|------|
| Service user | `greatwalk` |
| Service account home | `/opt/greatwalk` |
| Application | `/opt/greatwalk-bot` |
| Secrets | `/etc/greatwalk-bot/greatwalk-bot.env` |
| systemd unit | `/etc/systemd/system/greatwalk-bot.service` |

### Production filesystem layout

```
/opt/greatwalk-bot/
    config.yaml          # trip configuration (gitignored)
    .venv/               # Python environment (uv sync)
    logs/
        greatwalkbot.log
        status.json
    data/
        seen.db          # notification dedupe (default path)
    src/
    ...

/opt/greatwalk/          # service account home (uv, shell profile)
    .local/bin/uv

/etc/greatwalk-bot/
    greatwalk-bot.env    # Telegram tokens and optional overrides

/etc/systemd/system/
    greatwalk-bot.service
```

**Why `/opt` instead of a developer home directory?**

- **SELinux** — On Oracle Linux and RHEL, systemd services running executables from `/home` often fail with *Permission denied* even when Unix permissions are correct. `/opt` is the conventional location for third-party application trees.
- **Linux conventions** — Dedicated service accounts with application code under `/opt` match standard server packaging practice.
- **Secrets separation** — Tokens live in `/etc/greatwalk-bot/`, not inside the git tree.
- **Backup and migration** — Back up `/opt/greatwalk-bot` (code + state) and `/etc/greatwalk-bot/` (secrets) independently; reinstall on a new VM by restoring those paths and re-enabling the unit.

---

## 1. Prerequisites and assumptions

| Requirement | Details |
|-------------|---------|
| **Distributions** | **Oracle Linux 9** (primary production target; commands below use `dnf`). **Ubuntu 22.04+** / **Debian 12+** are supported with `apt` alternatives noted. |
| **User** | Dedicated system account **`greatwalk`** — not root, not a personal login. |
| **Network** | Outbound HTTPS to `bookings.doc.govt.nz` and the Telegram API if notifications are enabled. |
| **Git** | To clone the repository. |
| **Python** | **3.13+** (installed automatically by [uv](https://docs.astral.sh/uv/) during `uv sync`). |
| **uv** | Package manager used by this repo (`uv sync`, `uv run gwbot …`). |
| **Playwright** | Chromium browser + OS libraries for the default `playwright` availability source. |

---

## 2. Initial machine setup

Run privileged steps as **root** (or with `sudo`). Application steps as **`greatwalk`**.

### 2.1 Update packages and install base tools

**Oracle Linux 9:**

```bash
sudo dnf update -y
sudo dnf install -y git curl ca-certificates
```

**Ubuntu / Debian:**

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git curl ca-certificates
```

### 2.2 Create the service account and application directory

```bash
sudo useradd --system --create-home --home-dir /opt/greatwalk --shell /bin/bash greatwalk
sudo mkdir -p /opt/greatwalk-bot
sudo chown greatwalk:greatwalk /opt/greatwalk-bot
```

### 2.3 Install uv (durable absolute path)

```bash
sudo -iu greatwalk
curl -LsSf https://astral.sh/uv/install.sh | sh
/opt/greatwalk/.local/bin/uv --version
```

systemd invokes **`/opt/greatwalk-bot/.venv/bin/gwbot`** directly (created by `uv sync`), so the service does **not** depend on shell `PATH` initialization. Use **`/opt/greatwalk/.local/bin/uv`** for install and sync commands in scripts and cron.

### 2.4 Clone the repository

Still as `greatwalk`:

```bash
git clone https://github.com/YOUR_ORG/greatwalk-bot.git /opt/greatwalk-bot
cd /opt/greatwalk-bot
```

Replace the URL with your fork or mirror.

### 2.5 Install Python dependencies

```bash
/opt/greatwalk/.local/bin/uv sync
```

This creates `/opt/greatwalk-bot/.venv/` with the `gwbot` CLI at `.venv/bin/gwbot`.

### 2.6 Install Playwright OS dependencies and Chromium

Playwright does **not** support `playwright install-deps` on Oracle Linux (including ARM Ampere). Install system libraries with your package manager, then install the browser into the project venv.

**Oracle Linux 9** (tested approach for production):

```bash
sudo dnf install -y \
  alsa-lib \
  atk \
  at-spi2-atk \
  at-spi2-core \
  cairo \
  cups-libs \
  dbus-libs \
  libX11 \
  libXcomposite \
  libXdamage \
  libXext \
  libXfixes \
  libXi \
  libXrandr \
  libXrender \
  libXtst \
  libdrm \
  libxkbcommon \
  mesa-libgbm \
  nspr \
  nss \
  pango
```

Then as `greatwalk`:

```bash
cd /opt/greatwalk-bot
/opt/greatwalk/.local/bin/uv run playwright install chromium
```

If Chromium fails to start with a missing shared library, use `dnf provides '*/libfoo.so.*'` to find the owning package and install it.

**Ubuntu / Debian** (development or non-Oracle hosts):

```bash
sudo apt install -y \
  libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
  libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
  libgbm1 libasound2 libpango-1.0-0 libcairo2

cd /opt/greatwalk-bot
/opt/greatwalk/.local/bin/uv run playwright install chromium
```

Do **not** use `playwright install-deps` on Oracle Linux — it falls back to `apt-get` and fails.

---

## 3. Configuration

### 3.1 Create `config.yaml`

```bash
cd /opt/greatwalk-bot
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
cd /opt/greatwalk-bot
/opt/greatwalk/.local/bin/uv run gwbot plan-check config.yaml
```

Pre-deploy readiness (read-only DOC fetch per track, validates notifiers):

```bash
/opt/greatwalk/.local/bin/uv run gwbot preflight config.yaml
```

Optional Telegram test during preflight:

```bash
/opt/greatwalk/.local/bin/uv run gwbot preflight config.yaml --send-test-notification
```

Exit code `0` means ready; `1` means fix reported errors first.

If AWS WAF blocks headless Chromium, add `--headed` to preflight (requires a display — uncommon on a headless VPS).

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
# GREATWALKBOT_SEEN_DB=/opt/greatwalk-bot/data/seen.db
# GREATWALKBOT_DIAGNOSTICS_RETENTION=7
```

| Variable | Required | Purpose |
|----------|----------|---------|
| `GREATWALKBOT_TELEGRAM_BOT_TOKEN` | When Telegram enabled | Bot token from [@BotFather](https://t.me/BotFather) |
| `GREATWALKBOT_TELEGRAM_CHAT_ID` | When Telegram enabled | Target chat ID |
| `GREATWALKBOT_LOG_LEVEL` | No | `INFO` (default) or `DEBUG` for per-date rejection detail |
| `GREATWALKBOT_SEEN_DB` | No | Override dedupe SQLite path. Default: `data/seen.db` relative to `WorkingDirectory` (`/opt/greatwalk-bot/data/seen.db`). Set explicitly only if you relocate state. |
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
cd /opt/greatwalk-bot
/opt/greatwalk/.local/bin/uv run gwbot notify-test config.yaml
```

This does not contact DOC or launch Playwright.

---

## 5. systemd service

The repository ships a **system** unit template at `deploy/greatwalk-bot.service`. It runs as `greatwalk`, loads `/etc/greatwalk-bot/greatwalk-bot.env`, and invokes the project venv directly (no shell, no `PATH`).

### 5.1 Render and install the unit file

Ensure `greatwalk` owns the application tree (needed for `logs/` and `data/`):

```bash
sudo chown -R greatwalk:greatwalk /opt/greatwalk-bot
```

Edit placeholders in the template, or use `sed`:

```bash
cd /opt/greatwalk-bot

GREATWALKBOT_USER=greatwalk
GREATWALKBOT_HOME=/opt/greatwalk
GREATWALKBOT_REPO=/opt/greatwalk-bot

sed \
  -e "s|__GREATWALKBOT_USER__|${GREATWALKBOT_USER}|g" \
  -e "s|__GREATWALKBOT_HOME__|${GREATWALKBOT_HOME}|g" \
  -e "s|__GREATWALKBOT_REPO__|${GREATWALKBOT_REPO}|g" \
  deploy/greatwalk-bot.service > /tmp/greatwalk-bot.service

sudo cp /tmp/greatwalk-bot.service /etc/systemd/system/greatwalk-bot.service
rm /tmp/greatwalk-bot.service
```

Ensure `/opt/greatwalk-bot/.venv/bin/gwbot` exists (`uv sync` must have completed successfully).

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

---

## 6. Verification checklist

Run these after the service is installed (or before enable, for manual validation). Commands assume you are logged in as `greatwalk` with `cd /opt/greatwalk-bot`, or use the absolute paths shown.

| Step | Command | Expected outcome |
|------|---------|------------------|
| CLI available | `/opt/greatwalk-bot/.venv/bin/gwbot --help` | Help text; exit 0 |
| Config offline | `/opt/greatwalk/.local/bin/uv run gwbot plan-check config.yaml` | `Feasibility: YES` (or fix config) |
| One poll cycle | `/opt/greatwalk/.local/bin/uv run gwbot watch config.yaml --once` | Completes without error; writes `logs/` and `data/seen.db` |
| Optional debug fetch | `/opt/greatwalk/.local/bin/uv run gwbot debug-search config.yaml --track milford --date 2026-12-07` | Single-track search diagnostics (contacts DOC) |
| Telegram | `/opt/greatwalk/.local/bin/uv run gwbot notify-test config.yaml` | Test message in Telegram (with env file sourced) |
| Service active | `sudo systemctl status greatwalk-bot` | `active (running)` |
| Journal | `sudo journalctl -u greatwalk-bot -n 20 --no-pager` | Poll cycle log lines, no crash loop |
| Runtime metrics | `/opt/greatwalk/.local/bin/uv run gwbot status` | Recent timestamps in `logs/status.json` |

If headless fetches fail with WAF errors, retry with `--headed` on manual commands only.

---

## 7. Updating the deployment

When pulling new releases:

```bash
cd /opt/greatwalk-bot
sudo -u greatwalk git pull
sudo -u greatwalk /opt/greatwalk/.local/bin/uv sync
sudo systemctl restart greatwalk-bot
```

If Playwright browser requirements changed upstream, re-run:

```bash
cd /opt/greatwalk-bot
sudo -u greatwalk /opt/greatwalk/.local/bin/uv run playwright install chromium
```

Reinstall OS libraries with `dnf` only if Chromium reports a missing `.so` after the upgrade.

See **[Operations](operations.md)** for day-to-day commands.

---

## Troubleshooting

| Symptom | Action |
|---------|--------|
| Service fails immediately | `sudo journalctl -u greatwalk-bot -n 50 --no-pager` |
| No availability captured | Try `gwbot check` with `--headed` if WAF blocks headless traffic |
| Duplicate notifications after edit | Normal if you deleted `data/seen.db` |
| Status file stale | Watcher not running, or crashed before flush |

### Service fails with "Permission denied"

On **Oracle Linux**, **RHEL**, and other SELinux-enforcing systems, systemd may refuse to execute binaries under a user's home directory (`/home/...`) even when `chmod` and ownership look correct. journald often shows:

```
greatwalk-bot.service: Failed to execute ... Permission denied
```

or AVC denials in `/var/log/audit/audit.log`.

**Fix:** Deploy under **`/opt/greatwalk-bot`** with a dedicated **`greatwalk`** service account, as this guide describes. Avoid running the production unit from `/home/opc`, `/home/greatwalk`, or any personal home directory.

If you must diagnose SELinux:

```bash
sudo ausearch -m avc -ts recent
sudo setsebool -P domain_can_mmap_files 1   # rarely needed; prefer correct paths first
```

Relocating the repo to `/opt/greatwalk-bot` and restoring `greatwalk:greatwalk` ownership is the supported production layout.

---

## Security notes

- Do not commit `config.yaml`, `logs/`, `data/`, or `/etc/greatwalk-bot/greatwalk-bot.env`.
- Run as the unprivileged `greatwalk` user; the watcher only reads public DOC availability.
- Restrict environment file permissions (`chmod 600`).
- Revoke leaked bot tokens via [@BotFather](https://t.me/BotFather).

---

## Oracle Cloud notes

Oracle Cloud Infrastructure free-tier VMs often run **Oracle Linux 9** on **ARM (Ampere)**. This project does not depend on OCI APIs — any Linux VPS with outbound HTTPS works the same way.

- Use **`dnf`** for Playwright system libraries; do **not** use `playwright install-deps` (unsupported on Oracle Linux ARM).
- Ensure security lists / NSGs allow **outbound** HTTPS.
- Python 3.13+ wheels must exist for your CPU architecture (`uv sync` will report errors otherwise).

---

## Development machines

For a personal workstation without root, you may clone the repo elsewhere and use a user-level systemd unit. Production VPS deployments should use `/opt/greatwalk-bot` and the system unit described above. See [telegram.md](telegram.md) for optional `~/.config/greatwalkbot/env` on non-production hosts.
