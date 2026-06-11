#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path("/home/ubuntu/payment-api")
sys.path.insert(0, str(ROOT))

from library.baidu_client import create_share_link, get_access_token, health, parse_account_file  # noqa: E402
import urllib.parse
import urllib.request
import json as jsonlib


def raw_share(fs_id: str) -> dict:
    account = parse_account_file()
    appid = account.get("appid") or account.get("client_id")
    token = get_access_token()
    url = "https://pan.baidu.com/apaas/1.0/share/set?" + urllib.parse.urlencode(
        {"product": "netdisk", "appid": appid, "access_token": token}
    )
    body = urllib.parse.urlencode(
        {
            "fsid_list": jsonlib.dumps([fs_id], separators=(",", ":")),
            "period": "7",
            "pwd": "a1b2",
            "remark": "debug",
        }
    ).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return jsonlib.loads(resp.read().decode())


def main() -> int:
    fs_id = sys.argv[1] if len(sys.argv) > 1 else "269472321203081"
    print("health", json.dumps(health(), ensure_ascii=False))
    print("raw", json.dumps(raw_share(fs_id), ensure_ascii=False))
    share = create_share_link(fs_id)
    print("share", json.dumps(share, ensure_ascii=False))
    return 0 if share else 1


if __name__ == "__main__":
    raise SystemExit(main())
