#!/usr/bin/env bash
set -euo pipefail
CRON_LINE='17 3 * * * LOCAL_CACHE_MAX_AGE_DAYS=7 /home/ubuntu/qq-ai-bot/.venv/bin/python /home/ubuntu/qq-ai-bot/cache_cleanup.py >> /home/ubuntu/qq-ai-bot/cache_cleanup.log 2>&1'
( crontab -l 2>/dev/null | grep -v cache_cleanup.py || true; echo "$CRON_LINE" ) | crontab -
crontab -l | grep cache_cleanup
/home/ubuntu/qq-ai-bot/.venv/bin/python /home/ubuntu/qq-ai-bot/cache_cleanup.py
sudo systemctl restart qq-ai-bot.service
sleep 2
systemctl is-active qq-ai-bot.service
