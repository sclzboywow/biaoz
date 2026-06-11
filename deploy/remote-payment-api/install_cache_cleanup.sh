#!/usr/bin/env bash
# Install 7-day local cache cleanup cron + deploy cache_cleanup.py
set -euo pipefail

HOST="${PAYMENT_API_HOST:-ubuntu@111.231.22.77}"
KEY="${PAYMENT_API_SSH_KEY:-$HOME/.ssh/id_ed25519}"
DIR="$(cd "$(dirname "$0")" && pwd)"

scp -i "$KEY" "$DIR/../remote-qq-ai-bot/cache_cleanup.py" "$HOST:/home/ubuntu/qq-ai-bot/cache_cleanup.py"
scp -i "$KEY" "$DIR/library/cache_cleanup.py" "$HOST:/home/ubuntu/payment-api/library/cache_cleanup.py"
scp -i "$KEY" "$DIR/library/group_deliver.py" "$HOST:/home/ubuntu/payment-api/library/group_deliver.py"
scp -i "$KEY" "$DIR/library/download_file.py" "$HOST:/home/ubuntu/payment-api/library/download_file.py"
scp -i "$KEY" "$DIR/../remote-qq-ai-bot/app.py" "$HOST:/home/ubuntu/qq-ai-bot/app.py"

ssh -i "$KEY" "$HOST" bash -s <<'EOF'
set -euo pipefail
ENV_BOT=/home/ubuntu/qq-ai-bot/.env
ENV_PAY=/home/ubuntu/payment-api/.env
add_env() {
  local file="$1" key="$2" val="$3"
  if grep -q "^${key}=" "$file" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$file"
  else
    printf '\n%s=%s\n' "$key" "$val" >> "$file"
  fi
}
add_env "$ENV_BOT" LOCAL_CACHE_MAX_AGE_DAYS 7
add_env "$ENV_PAY" LOCAL_CACHE_MAX_AGE_DAYS 7
add_env "$ENV_PAY" LIBRARY_DOWNLOAD_DIR /home/ubuntu/qq-ai-bot/downloads/delivery

CRON_LINE='17 3 * * * LOCAL_CACHE_MAX_AGE_DAYS=7 /home/ubuntu/qq-ai-bot/.venv/bin/python /home/ubuntu/qq-ai-bot/cache_cleanup.py >> /home/ubuntu/qq-ai-bot/cache_cleanup.log 2>&1'
( crontab -l 2>/dev/null | grep -v cache_cleanup.py || true; echo "$CRON_LINE" ) | crontab -

/home/ubuntu/qq-ai-bot/.venv/bin/python /home/ubuntu/qq-ai-bot/cache_cleanup.py
sudo systemctl restart qq-ai-bot.service
sleep 2
systemctl is-active qq-ai-bot.service
EOF

echo "done"
