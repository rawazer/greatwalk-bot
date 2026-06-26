# Operations

Day-to-day use of an **already deployed** GreatWalkBot instance on **`/opt/greatwalk-bot`**: logs, restarts, updates, and quick manual checks.

For first-time VM setup, see **[Deployment guide](deployment.md)**.

Production paths:

| Item | Path |
|------|------|
| Application | `/opt/greatwalk-bot` |
| Secrets | `/etc/greatwalk-bot/greatwalk-bot.env` |
| systemd unit | `/etc/systemd/system/greatwalk-bot.service` |

## Deploy an update

Pull the latest code, refresh dependencies, and restart the service:

```bash
cd /opt/greatwalk-bot
sudo -u greatwalk git pull
sudo -u greatwalk /opt/greatwalk/.local/bin/uv sync
sudo systemctl restart greatwalk-bot
sudo systemctl status greatwalk-bot --no-pager
```

If you changed `config.yaml`, restart is enough — no `uv sync` required unless dependencies changed.

## View live logs

```bash
# systemd journal (stdout/stderr from gwbot)
sudo journalctl -u greatwalk-bot -f

# Application log file
tail -f /opt/greatwalk-bot/logs/greatwalkbot.log
```

## Runtime health

```bash
cd /opt/greatwalk-bot
sudo -u greatwalk /opt/greatwalk/.local/bin/uv run gwbot status
```

See [runtime-state.md](runtime-state.md) for the `logs/status.json` schema.

## Run one manual poll

Stop the service first if you want to avoid two concurrent browser sessions on the same machine:

```bash
sudo systemctl stop greatwalk-bot
cd /opt/greatwalk-bot
sudo -u greatwalk /opt/greatwalk/.local/bin/uv run gwbot watch config.yaml --once
sudo systemctl start greatwalk-bot
```

For a quick read-only DOC check without the full watcher:

```bash
cd /opt/greatwalk-bot
sudo -u greatwalk /opt/greatwalk/.local/bin/uv run gwbot check --track milford --from 2026-12-07 --to 2026-12-14
```

## Stop / start / disable

```bash
sudo systemctl stop greatwalk-bot
sudo systemctl start greatwalk-bot
sudo systemctl restart greatwalk-bot
sudo systemctl disable greatwalk-bot   # stop starting at boot; does not remove the unit
```

## Telegram test (no DOC contact)

```bash
cd /opt/greatwalk-bot
set -a && source /etc/greatwalk-bot/greatwalk-bot.env && set +a
sudo -u greatwalk /opt/greatwalk/.local/bin/uv run gwbot notify-test config.yaml
```

## Troubleshooting

| Symptom | Action |
|---------|--------|
| Service not running | `sudo systemctl status greatwalk-bot` and `sudo journalctl -u greatwalk-bot -n 50 --no-pager` |
| Stale `status.json` | Watcher crashed or was stopped; check journal and app log |
| No availability captured | Try `gwbot check` with `--headed` if WAF blocks headless traffic |
| Duplicate Telegram alerts | Expected if `data/seen.db` was deleted; otherwise investigate dedupe path |
| More detail in logs | Set `GREATWALKBOT_LOG_LEVEL=DEBUG` in `/etc/greatwalk-bot/greatwalk-bot.env` and restart |

### Service fails with "Permission denied"

On Oracle Linux and other SELinux-enforcing systems, running the unit from a home directory (`/home/opc`, `/home/greatwalk`, etc.) often fails even when file permissions are correct. Deploy under **`/opt/greatwalk-bot`** with the **`greatwalk`** service account — see [deployment.md](deployment.md#service-fails-with-permission-denied).

## Config and secrets

- Trip settings: `/opt/greatwalk-bot/config.yaml` (gitignored — never commit).
- Telegram tokens: `/etc/greatwalk-bot/greatwalk-bot.env` only (see [telegram.md](telegram.md)).
- Optional dedupe override: `GREATWALKBOT_SEEN_DB=/opt/greatwalk-bot/data/seen.db` in the env file (omit to use the default `data/seen.db` under WorkingDirectory).
- After editing either file: `sudo systemctl restart greatwalk-bot`.
