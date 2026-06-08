from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text

from app.database import SessionLocal

LOG = ROOT / "logs" / "openstd-file-loop.out.log"


def parse_log() -> dict:
    results: list[dict] = []
    summaries: list[dict] = []
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("openstd_batch_result "):
            results.append(json.loads(line.split(" ", 1)[1]))
        elif line.startswith("openstd_batch_summary "):
            summaries.append(json.loads(line.split(" ", 1)[1]))

    ok = [r for r in results if r.get("ok") is True]
    fail = [r for r in results if r.get("ok") is False]
    captcha_fail = [r for r in fail if r.get("captcha_error") or "Captcha" in str(r.get("error", "")) or "验证码" in str(r.get("error", ""))]
    source_fail = [r for r in fail if r not in captcha_fail]

    def pct(n: int, d: int) -> float:
        return round(n / d * 100, 1) if d else 0.0

    return {
        "batch_cycles": len(summaries),
        "total_attempts": len(results),
        "success_attempts": len(ok),
        "failed_attempts": len(fail),
        "overall_success_rate_pct": pct(len(ok), len(results)),
        "captcha_failures": len(captcha_fail),
        "captcha_success_rate_pct": pct(len(ok), len(ok) + len(captcha_fail)),
        "source_unavailable_failures": len(source_fail),
        "when_source_has_pdf_success_rate_pct": pct(len(ok), len(ok) + len(source_fail)),
    }


def parse_db() -> dict:
    with SessionLocal() as db:
        archived = db.execute(
            text(
                """
                SELECT COUNT(*) FROM document_versions dv
                JOIN url_sources us ON us.id = dv.url_source_id
                WHERE dv.is_current = true
                  AND us.url LIKE 'https://openstd.samr.gov.cn/bzgk/std/showGb?type=download%'
                """
            )
        ).scalar() or 0
        temp_fail = db.execute(
            text(
                """
                SELECT COUNT(*) FROM standard_resources sr
                JOIN trusted_sources ts ON ts.id = sr.source_id
                WHERE ts.adapter_key = 'samr_gb_all_public'
                  AND sr.sync_status = '文件采集失败'
                """
            )
        ).scalar() or 0
        return {"db_archived_pdfs": archived, "db_temp_fail_marked": temp_fail}


def main() -> None:
    print(json.dumps({**parse_log(), **parse_db()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
