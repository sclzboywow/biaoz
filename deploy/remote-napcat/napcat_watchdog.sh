#!/bin/bash
# NapCat 守护：仅在确认掉线/进程崩溃时重启，避免误判二维码页导致反复重启

set -u

CONTAINER="${NAPCAT_CONTAINER:-napcat}"
NAPCAT_DIR="${NAPCAT_DIR:-/home/ubuntu/napcat}"
LOG_FILE="${NAPCAT_WATCHDOG_LOG:-$NAPCAT_DIR/watchdog.log}"
STATE_FILE="${NAPCAT_WATCHDOG_STATE:-$NAPCAT_DIR/.watchdog_state}"
RUNTIME_ENV="${NAPCAT_RUNTIME_ENV:-$NAPCAT_DIR/.env.runtime}"
COOLDOWN_SEC="${NAPCAT_RESTART_COOLDOWN:-600}"
CHECK_INTERVAL="${NAPCAT_CHECK_INTERVAL:-120}"

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG_FILE"
}

can_restart() {
  local now last
  now=$(date +%s)
  last=0
  if [[ -f "$STATE_FILE" ]]; then
    last=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
  fi
  if (( now - last < COOLDOWN_SEC )); then
    return 1
  fi
  echo "$now" > "$STATE_FILE"
  return 0
}

is_logged_in() {
  local recent="$1"
  if grep -qiE '请扫描下面的二维码|用户身份已失效|快速登录错误' <<< "$recent"; then
    return 1
  fi
  grep -qE '接收 <-|发送 ->' <<< "$recent"
}

record_last_login() {
  local recent="$1"
  local qq=""
  # 仅认 NapCat 明确登录行，避免从群消息里的 QQ 号误写入 ACCOUNT
  qq=$(grep -oE '正在快速登录[[:space:]]+[0-9]+' <<< "$recent" | tail -1 | awk '{print $2}')
  if [[ -z "$qq" ]]; then
    qq=$(grep -oE '发送 -> .* \[[^]]+\(([0-9]+)\)\]' <<< "$recent" | head -1 | grep -oE '[0-9]+' | tail -1)
  fi
  if [[ -z "$qq" ]] && grep -qE '协议适配器初始化完成' <<< "$recent"; then
    qq=$(find "$NAPCAT_DIR/config" -maxdepth 1 -name 'onebot11_[0-9]*.json' -printf '%T@ %f\n' 2>/dev/null \
      | sort -rn | head -1 | sed -n 's/.*onebot11_\([0-9]*\)\.json/\1/p')
  fi
  if [[ -z "$qq" ]]; then
    return
  fi
  if [[ ! -f "$RUNTIME_ENV" ]] || ! grep -q "^ACCOUNT=${qq}$" "$RUNTIME_ENV" 2>/dev/null; then
    echo "ACCOUNT=${qq}" > "$RUNTIME_ENV"
    log "recorded last login ACCOUNT=${qq} -> ${RUNTIME_ENV}"
  fi
}

restart_napcat() {
  local reason="$1"
  if ! can_restart; then
    log "skip restart ($reason): cooldown ${COOLDOWN_SEC}s"
    return
  fi
  log "restart napcat: $reason"
  docker restart "$CONTAINER" >> "$LOG_FILE" 2>&1 || true
}

check_once() {
  if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    log "container not running, starting via compose"
    (cd "$NAPCAT_DIR" && docker compose up -d) >> "$LOG_FILE" 2>&1 || true
    return
  fi

  local recent
  recent=$(docker logs --since 3m "$CONTAINER" 2>&1 || true)

  if is_logged_in "$recent"; then
    record_last_login "$recent"
    return
  fi

  if grep -qiE 'KickedOffLine|登录已失效' <<< "$recent"; then
    restart_napcat "qq session kicked offline"
    return
  fi

  if grep -q '无法重复登录' <<< "$recent"; then
    restart_napcat "zombie session (already logged in error)"
    return
  fi

  if grep -qiE 'Network service crashed|SIGSEGV|segmentation fault' <<< "$recent"; then
    restart_napcat "qq core process crash"
    return
  fi

  # 会话僵尸：反复离线且无收发消息时重启，便于重新扫码
  if grep -q '账号状态变更为离线' <<< "$recent" && ! grep -qE '接收 <-|发送 ->' <<< "$recent"; then
    local offline_n
    offline_n=$(grep -c '账号状态变更为离线' <<< "$recent" || true)
    if (( offline_n >= 2 )); then
      restart_napcat "qq session offline without traffic"
    fi
  fi
}

mkdir -p "$(dirname "$LOG_FILE")"
log "watchdog started (interval=${CHECK_INTERVAL}s cooldown=${COOLDOWN_SEC}s, qr-stuck check disabled)"

while true; do
  check_once
  sleep "$CHECK_INTERVAL"
done
