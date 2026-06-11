#!/usr/bin/env bash
# Copy local openxpanapi SDK + account file to payment server.
set -euo pipefail

HOST="${PAYMENT_API_HOST:-ubuntu@111.231.22.77}"
KEY="${PAYMENT_API_SSH_KEY:-$HOME/.ssh/id_ed25519}"
REMOTE_ROOT="${PAYMENT_API_REMOTE:-/home/ubuntu}"
SDK_LOCAL="${SDK_LOCAL:-$(cd "$(dirname "$0")/../.." && pwd)/openxpanapi}"
REMOTE_SDK="$REMOTE_ROOT/openxpanapi"

if [[ ! -d "$SDK_LOCAL" ]]; then
  echo "missing local SDK: $SDK_LOCAL" >&2
  exit 1
fi

echo "==> pack $SDK_LOCAL"
TMP_TAR="$(mktemp /tmp/openxpanapi.XXXXXX.tgz 2>/dev/null || mktemp)"
tar -czf "$TMP_TAR" -C "$(dirname "$SDK_LOCAL")" "$(basename "$SDK_LOCAL")"

echo "==> upload to $HOST:$REMOTE_SDK"
ssh -i "$KEY" "$HOST" "rm -rf '$REMOTE_SDK' && mkdir -p '$REMOTE_ROOT'"
scp -i "$KEY" "$TMP_TAR" "$HOST:/tmp/openxpanapi.tgz"
ssh -i "$KEY" "$HOST" "tar -xzf /tmp/openxpanapi.tgz -C '$REMOTE_ROOT' && rm /tmp/openxpanapi.tgz && chmod 700 '$REMOTE_SDK' && chmod 600 '$REMOTE_SDK/'*.txt 2>/dev/null || true"

echo "==> link payment-api -> openxpanapi"
ssh -i "$KEY" "$HOST" "ln -sfn '$REMOTE_SDK' '$REMOTE_ROOT/payment-api/openxpanapi'"

echo "==> verify"
ssh -i "$KEY" "$HOST" "ls -la '$REMOTE_SDK' | head -8; test -f '$REMOTE_SDK/vendor/autoload.php' && echo 'vendor ok'"

rm -f "$TMP_TAR"
echo "done: $REMOTE_SDK"
