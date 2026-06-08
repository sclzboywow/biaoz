from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text

from app.database import SessionLocal

python = BACKEND / ".venv" / "Scripts" / "python.exe"
verify_script = ROOT / "scripts" / "verify_baidu_pan_versions.py"


def recent_version_ids(url_like: str, limit: int = 15) -> list[int]:
    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT dv.id
                FROM document_versions dv
                JOIN url_sources us ON us.id = dv.url_source_id
                WHERE dv.is_current = true
                  AND dv.file_path LIKE 'baidupan:%'
                  AND us.url LIKE :pattern
                ORDER BY dv.id DESC
                LIMIT :limit
                """
            ),
            {"pattern": url_like, "limit": limit},
        ).all()
    return [row[0] for row in rows]


def run_verify(label: str, version_ids: list[int]) -> dict:
    if not version_ids:
        return {"label": label, "selected": 0, "ok": 0, "failed": 0}
    cmd = [
        str(python),
        str(verify_script),
        "--mode",
        "metadata",
        "--workers",
        "4",
        "--retries",
        "2",
    ]
    for version_id in version_ids:
        cmd.extend(["--version-id", str(version_id)])
    proc = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = failed = 0
    for line in proc.stdout.splitlines():
        if line.startswith("baidu_pan_verify_summary "):
            payload = json.loads(line.split(" ", 1)[1])
            ok = payload.get("ok", 0)
            failed = payload.get("failed", 0)
    return {
        "label": label,
        "selected": len(version_ids),
        "ok": ok,
        "failed": failed,
        "exit_code": proc.returncode,
        "version_ids": version_ids,
    }


def main() -> None:
    groups = {
        "openstd_recent": recent_version_ids("https://openstd.samr.gov.cn/bzgk/std/showGb?type=download%", 15),
        "spc_recent": recent_version_ids("spc-online-reading://%", 15),
        "all_recent": recent_version_ids("%", 20),
    }
    results = [run_verify(name, ids) for name, ids in groups.items()]
    print(json.dumps({"verify": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
