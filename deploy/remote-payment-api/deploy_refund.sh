#!/usr/bin/env bash
# Deploy Alipay refund API to payment-api server (use scp, avoid pipe encoding issues).
set -euo pipefail

HOST="${PAYMENT_API_HOST:-ubuntu@111.231.22.77}"
KEY="${PAYMENT_API_SSH_KEY:-$HOME/.ssh/id_ed25519}"
REMOTE="/home/ubuntu/payment-api"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> upload refund package"
scp -i "$KEY" -r "$DIR/files" "$DIR/install_refund.py" "$HOST:/tmp/refund-deploy/"

echo "==> install"
ssh -i "$KEY" "$HOST" "mkdir -p /tmp/refund-deploy && cp -r /tmp/refund-deploy/files /tmp/refund-deploy/install_refund.py /tmp/refund-deploy/ 2>/dev/null || true; cd /tmp/refund-deploy && $REMOTE/.venv/bin/python install_refund.py"

echo "==> restart payment-api"
ssh -i "$KEY" "$HOST" "sudo systemctl restart payment-api.service && sleep 2 && systemctl is-active payment-api.service"

echo "==> done"
