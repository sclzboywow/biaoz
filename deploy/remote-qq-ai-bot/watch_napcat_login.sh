#!/bin/bash
for i in 1 2 3 4 5 6; do
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') check $i ==="
  curl -s http://127.0.0.1:8765/health | python3 -c 'import sys,json; d=json.load(sys.stdin); print("napcat_connected=", d.get("napcat_connected"))'
  docker logs napcat --since 35s 2>&1 | grep -iE '快速登录|登录态|Kick|二维码|5625523|2529213858|WebSocket|crash|Login Error' | tail -8
  echo "---"
  sleep 30
done
