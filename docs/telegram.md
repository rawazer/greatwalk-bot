# Telegram notifications

GreatWalkBot can send Telegram alerts when newly matching Great Walk itineraries are detected.

Secrets are **never** stored in YAML, logs, status files, or Git. Configure only the **names** of environment variables in `config.yaml`; set the actual values in your shell or a protected environment file.

## 1. Create a Telegram bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts.
3. BotFather returns a **bot token** (looks like `123456789:ABCdefGHI...`). Keep this secret.
4. Do not commit the token or paste it into `config.yaml`.

## 2. Obtain your chat ID

The bot must know where to send messages.

**Personal chat:**

1. Send any message to your new bot in Telegram.
2. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser (replace `<YOUR_TOKEN>` locally; do not share the URL).
3. Find `"chat":{"id":123456789}` in the JSON response. That number is your chat ID.

**Group chat:** Add the bot to the group, send a message, then read `chat.id` from `getUpdates` (group IDs are usually negative).

## 3. Configure GreatWalkBot

Add to `config.yaml`:

```yaml
notifications:
  console: true
  telegram:
    enabled: true
    bot_token_env: GREATWALKBOT_TELEGRAM_BOT_TOKEN
    chat_id_env: GREATWALKBOT_TELEGRAM_CHAT_ID
```

- `bot_token_env` / `chat_id_env` are **environment variable names**, not the secret values.
- At least one of `console` or `telegram.enabled` must be true.

## 4. Set environment variables (manual runs)

```bash
export GREATWALKBOT_TELEGRAM_BOT_TOKEN='your-bot-token'
export GREATWALKBOT_TELEGRAM_CHAT_ID='your-chat-id'

uv run gwbot notify-test config.yaml
uv run gwbot watch config.yaml
```

## 5. systemd environment file

Store secrets **outside the repository**. For a **system** service (recommended on VPS):

```bash
sudo mkdir -p /etc/greatwalk-bot
sudo nano /etc/greatwalk-bot/greatwalk-bot.env
```

Contents (mode `600` recommended):

```bash
GREATWALKBOT_TELEGRAM_BOT_TOKEN=your-bot-token
GREATWALKBOT_TELEGRAM_CHAT_ID=your-chat-id

# Optional — default dedupe path is data/seen.db under /opt/greatwalk-bot
# GREATWALKBOT_SEEN_DB=/opt/greatwalk-bot/data/seen.db
```

```bash
sudo chown root:root /etc/greatwalk-bot/greatwalk-bot.env
sudo chmod 600 /etc/greatwalk-bot/greatwalk-bot.env
```

The unit template `deploy/greatwalk-bot.service` includes (leading `-` makes the file optional when Telegram is off):

```ini
EnvironmentFile=-/etc/greatwalk-bot/greatwalk-bot.env
```

Reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart greatwalk-bot
```

For a **user** service on a **development machine** (not production), use `~/.config/greatwalkbot/env` instead:

```bash
mkdir -p ~/.config/greatwalkbot
chmod 700 ~/.config/greatwalkbot
nano ~/.config/greatwalkbot/env
chmod 600 ~/.config/greatwalkbot/env
```

```ini
EnvironmentFile=%h/.config/greatwalkbot/env
```

See [deployment.md](deployment.md) for the full service setup.

## 6. Test delivery

```bash
cd /opt/greatwalk-bot
set -a && source /etc/greatwalk-bot/greatwalk-bot.env && set +a
uv run gwbot notify-test config.yaml
```

This command:

- Loads and validates your config (including required env vars when Telegram is enabled)
- Sends a clearly labeled **test** message
- Does **not** contact DOC or launch Playwright
- Exits with a nonzero code if Telegram delivery fails

## 7. What you receive

When real availability is detected:

```
NEW preferred
Milford Track starting 2026-12-07
Party: 2 | Available spaces: 5
Facilities: Clinton Hut, Mintaro Hut

Open DOC booking site to confirm and book: https://bookings.doc.govt.nz/Web/
```

Messages are plain text. GreatWalkBot does not claim a hut is reserved for you.

## 8. Notification health in status

`gwbot status` and `logs/status.json` include (schema v2):

- `last_notification_attempt_at`
- `last_successful_notification_at`
- `last_notification_error` (message only — never secrets)

A Telegram failure is logged and recorded in status but **does not** stop the watcher.

## 9. Troubleshooting

| Problem | Likely cause |
|---------|----------------|
| `environment variable GREATWALKBOT_TELEGRAM_BOT_TOKEN is not set` | Export the variable or add `EnvironmentFile` to systemd |
| `chat not found` | Wrong chat ID; message the bot first |
| `Unauthorized` | Invalid bot token |
| Test works but no alerts on availability | Check watcher logs; verify trip date preferences match availability |
| Repeat Telegram alerts after restart | Should not happen if `data/seen.db` persists; do not delete it unless intentional |

## Security

- Never commit `config.yaml`, `~/.config/greatwalkbot/env`, or bot tokens.
- Restrict permissions on the environment file (`chmod 600`).
- Use a dedicated bot token per deployment; revoke via BotFather if leaked.
