#!/usr/bin/env python3
import json
from pathlib import Path

cfg_path = Path("/home/ubuntu/napcat/config/onebot11_2529213858.json")
cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
servers = cfg.setdefault("network", {}).setdefault("httpServers", [])
if not any(s.get("port") == 3001 and s.get("enable") for s in servers):
    servers.append(
        {
            "name": "qq-file-api",
            "enable": True,
            "host": "127.0.0.1",
            "port": 3001,
            "accessToken": "",
            "messagePostFormat": "array",
            "debug": False,
        }
    )
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("patched napcat httpServers")
else:
    print("napcat httpServers already enabled")
