from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.ttbz_browser_session import check_ttbz_browser_login, resolve_ttbz_cdp_url


def main() -> int:
    status = check_ttbz_browser_login(cdp_url=resolve_ttbz_cdp_url())
    print(json.dumps(status, ensure_ascii=False, indent=2))
    if not status.get("enabled"):
        print("hint: set TTBZ_CDP_URL or run scripts/start-ttbz-member-chrome.ps1")
        return 0
    if not status.get("reachable"):
        print("hint: run .\\scripts\\start-ttbz-member-chrome.ps1 (starts jump SOCKS + Chrome on 9223)")
        return 1
    if status.get("logged_in_hint") == "blocked_403_need_proxy":
        print("hint: TTBZ still 403 — close TTBZ Chrome and rerun start-ttbz-member-chrome.ps1 (must use SOCKS proxy)")
        return 1
    if status.get("logged_in_hint") in {
        "likely_logged_out",
        "likely_logged_out_missing_token",
        "likely_logged_in_bus_rejected",
    }:
        print("hint: open http://127.0.0.1:9223 and log in to ttbz.org.cn (bus API needs fresh member session + accessToken)")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
