#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path("/home/ubuntu/payment-api")
sys.path.insert(0, str(ROOT))

from library.baidu_client import create_share_link, health  # noqa: E402
from library.metadata_db import metadata_connection  # noqa: E402
from library.baidu_remark import resolve_baidu_fs_id  # noqa: E402


def sample_fs_id() -> str | None:
    sql = """
        SELECT dv.file_path, dv.remark
        FROM document_versions dv
        WHERE dv.is_current IS TRUE
          AND dv.file_path LIKE 'baidupan:%%'
        ORDER BY dv.id DESC
        LIMIT 1
    """
    with metadata_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
    if not row:
        return None
    return resolve_baidu_fs_id(file_path=row[0], remark=row[1])


def main() -> int:
    print("health", json.dumps(health(), ensure_ascii=False))
    fs_id = sample_fs_id()
    if not fs_id:
        print(json.dumps({"status": "error", "message": "no sample fs_id from metadata db"}))
        return 1
    share = create_share_link(fs_id)
    print(
        json.dumps(
            {
                "status": "success" if share else "error",
                "fs_id": fs_id,
                "share": share,
            },
            ensure_ascii=False,
        )
    )
    return 0 if share else 1


if __name__ == "__main__":
    raise SystemExit(main())
