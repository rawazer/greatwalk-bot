# Operations

Day-to-day use of an **already deployed** GreatWalkBot instance: logs, restarts, updates, and quick manual checks.

For first-time VM setup (clone, `uv sync`, systemd install), see **[Deployment guide](deployment.md)**.

## Deploy an update

Pull the latest code, refresh dependencies, and restart the service:

```bash
cd /path/to/greatwalk-bot
git pull
uv sync
sudo systemctl restart greatwalk-bot
sudo systemctl status greatwalk-bot --no-pager
```

If you changed `config.yaml`, restart is enough — no `uv sync` required unless dependencies changed.

## View live logs

```bash
# systemd journal (stdout/stderr from gwbot)
sudo journalctl -u greatwalk-bot -f

# Application log file (under the repo WorkingDirectory)
tail -f /path/to/greatwalk-bot/logs/greatwalkbot.log
```

## Runtime health

```bash
cd /path/to/greatwalk-bot
uv run gwbot status
```

See [runtime-state.md](runtime-state.md) for the `logs/status.json` schema.

## Run one manual poll

Stop the service first if you want to avoid two concurrent browser sessions on the same machine:

```bash
sudo systemctl stop greatwalk-bot
cd /path/to/greatwalk-bot
uv run gwbot watch config.yaml --once
sudo systemctl start greatwalk-bot
```

For a quick read-only DOC check without the full watcher:

```bash
uv run gwbot check --track milford --from 2026-12-07 --to 2026-12-14
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
cd /path/to/greatwalk-bot
# Ensure /etc/greatwalk-bot/greatwalk-bot.env is loaded, or export vars manually:
set -a && source /etc/greatwalk-bot/greatwalk-bot.env && set +a
uv run gwbot notify-test config.yaml
```

## Troubleshooting

| Symptom | Action |
|---------|--------|
| Service not running | `sudo systemctl status greatwalk-bot` and `sudo journalctl -u greatwalk-bot -n 50 --no-pager` |
| Stale `status.json` | Watcher crashed or was stopped; check journal and app log |
| No availability captured | Try `gwbot check` with `--headed` if WAF blocks headless traffic |
| Duplicate Telegram alerts | Expected if `data/seen.db` was deleted; otherwise investigate dedupe path |
| More detail in logs | Set `GREATWALKBOT_LOG_LEVEL=DEBUG` in the environment file and restart |

## Config and secrets

- Trip settings: `config.yaml` in the repo (gitignored — never commit).
- Telegram tokens: `/etc/greatwalk-bot/greatwalk-bot.env` only (see [telegram.md](telegram.md)).
- After editing either file: `sudo systemctl restart greatwalk-bot`.
