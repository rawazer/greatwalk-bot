# Operations

## Deploy an update
git pull
uv sync
sudo systemctl restart greatwalk-bot
sudo systemctl status greatwalk-bot --no-pager

## View live logs
journalctl -u greatwalk-bot -f

## Run one manual poll
uv run gwbot watch config.yaml --once

## Stop / start
sudo systemctl stop greatwalk-bot
sudo systemctl start greatwalk-bot