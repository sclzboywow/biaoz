"""
统计 WPS 多维表可拉取真实文件、且未入百度网盘的候选量。

用法:
  backend/.venv/Scripts/python.exe scripts/report_wps_fetch_candidates.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.standard_number import normalize_standard_no  # noqa: E402

# 链接可用性：夸克默认可用；直连 PDF / 国标电子书 PDF 可用；其余多为网页入口不可用
QUARK_HOSTS = ("pan.quark.cn",)
DIRECT_FILE_HINTS = (
    ".pdf",
    "/pdf/",
    "/upload/resources/pdf/",
)
WEB_PORTAL_HOSTS = (
    "openstd.samr.gov.cn",
    "std.samr.gov.cn",
    "www.spc.org.cn",
    "spc.org.cn",
    "hbba.sacinfo.org.cn",
    "dbba.sacinfo.org.cn",
    "sacinfo.org.cn",
    "wenku",
    "docin.com",
    "book118",
    "max.book118",
    "原创力",
)
BAIDU_PAN_SQL = """
    dv.file_path LIKE 'baidupan:%'
    OR dv.remark LIKE '%remote_uri%baidupan:%'
"""


def classify_link(link_url: str | None) -> str:
    if not link_url or not str(link_url).strip():
        return "no_link"

    url = str(link_url).strip()
    lower = url.lower()
    host = (urlparse(url).netloc or "").lower()

    if "ebook.chinabuilding.com.cn" in lower:
        return "ebook_pdf" if "/pdf/" in lower else "ebook_page"
    if any(h in host for h in QUARK_HOSTS) or "pan.quark.cn" in lower:
        return "quark_pan"
    if lower.endswith(".pdf") or "/upload/resources/pdf/" in lower:
        return "direct_pdf"
    if any(h in lower for h in WEB_PORTAL_HOSTS):
        return "web_portal"
    if "openstd.samr.gov.cn" in lower or "std.samr.gov.cn" in lower:
        return "web_portal"
    if host.endswith(".gov.cn") and ".pdf" not in lower:
        return "web_portal"
    return "other_http"


def link_fetchable(link_type: str) -> bool:
    # 夸克网盘默认可拉真实文件；直连 PDF 可用；电子书 PDF 可用；其余网页入口不可用
    return link_type in {"ebook_pdf", "quark_pan", "direct_pdf"}


def extract_candidate_standard_no(file_no: str | None, file_name: str | None) -> str | None:
    for value in (file_no, file_name):
        if not value:
            continue
        text_value = str(value).strip()
        if not text_value:
            continue
        # 公告类标题通常不是标准号
        if "公告" in text_value and not re.search(r"GB|JGJ|CJJ|CECS|DB|T/", text_value, re.I):
            continue
        parts = normalize_standard_no(text_value)
        if parts.normalized:
            return parts.normalized
        # 从名称里抠标准号
        match = re.search(
            r"(GB/T\s?\d{4,5}-\d{4}|GB\s?\d{4,5}-\d{4}|JGJ/?T?\s?\d+-?\d{4}|CJJ/?T?\s?\d+-?\d{4}|"
            r"[A-Z]{2,8}/T?\s?\d[\w.-]*-\d{4})",
            text_value,
            re.I,
        )
        if match:
            return normalize_standard_no(match.group(0)).normalized
    return None


def main() -> None:
    with SessionLocal() as db:
        total = db.execute(text("SELECT COUNT(*) FROM wps_standard_query_records")).scalar() or 0

        rows = db.execute(
            text(
                """
                SELECT id, wps_record_id, serial_no, file_no, file_name, impl_status, link_url
                FROM wps_standard_query_records
                """
            )
        ).mappings().all()

        # 预载多维排除集合
        url_on_pan = {
            r[0]
            for r in db.execute(
                text(
                    f"""
                    SELECT DISTINCT us.url
                    FROM url_sources us
                    JOIN document_versions dv ON dv.url_source_id = us.id
                    WHERE ({BAIDU_PAN_SQL})
                    """
                )
            ).all()
            if r[0]
        }
        pdf_trial_on_pan = {
            r[0]
            for r in db.execute(
                text(
                    f"""
                    SELECT DISTINCT sr.pdf_trial_url
                    FROM standard_resources sr
                    JOIN standard_file_matches sfm ON sfm.standard_resource_id = sr.id
                    JOIN document_versions dv ON dv.id = sfm.document_version_id
                    WHERE sr.pdf_trial_url IS NOT NULL
                      AND ({BAIDU_PAN_SQL})
                    """
                )
            ).all()
            if r[0]
        }
        stdno_on_pan = {
            r[0]
            for r in db.execute(
                text(
                    f"""
                    SELECT DISTINCT COALESCE(d.normalized_standard_no, d.standard_no)
                    FROM documents d
                    JOIN document_versions dv ON dv.document_id = d.id AND dv.is_current IS TRUE
                    WHERE COALESCE(d.normalized_standard_no, d.standard_no) IS NOT NULL
                      AND ({BAIDU_PAN_SQL})
                    """
                )
            ).all()
            if r[0]
        }

        link_type_counter: Counter[str] = Counter()
        fetchable_counter = 0
        unavailable_counter = 0
        on_pan_by_dim = Counter()
        candidate_rows = 0
        candidate_by_type: Counter[str] = Counter()

        for row in rows:
            link_type = classify_link(row["link_url"])
            link_type_counter[link_type] += 1
            fetchable = link_fetchable(link_type)
            if fetchable:
                fetchable_counter += 1
            else:
                unavailable_counter += 1

            if not fetchable:
                continue

            link = (row["link_url"] or "").strip()
            std_no = extract_candidate_standard_no(row["file_no"], row["file_name"])

            hit_dims: list[str] = []
            if link and link in url_on_pan:
                hit_dims.append("url_sources")
            if link and link in pdf_trial_on_pan:
                hit_dims.append("pdf_trial_url")
            if std_no and std_no in stdno_on_pan:
                hit_dims.append("standard_no")

            if hit_dims:
                for dim in hit_dims:
                    on_pan_by_dim[dim] += 1
                continue

            candidate_rows += 1
            candidate_by_type[link_type] += 1

        # 链接类型分布（全表）
        print("=== WPS 全表链接类型 ===")
        print(f"总记录: {total:,}")
        for k, v in link_type_counter.most_common():
            flag = "可用" if link_fetchable(k) else "不可用"
            print(f"  {k}: {v:,} ({flag})")

        print("\n=== 真实文件可用性（按链接类型） ===")
        print(f"标记可用(夸克/直连PDF/电子书PDF): {fetchable_counter:,}")
        print(f"标记不可用(网页入口/无链接等): {unavailable_counter:,}")

        print("\n=== 已入百度网盘（多维命中，仅统计可用链接子集） ===")
        print(f"url_sources 链接命中: {on_pan_by_dim['url_sources']:,}")
        print(f"pdf_trial_url 命中: {on_pan_by_dim['pdf_trial_url']:,}")
        print(f"standard_no 命中: {on_pan_by_dim['standard_no']:,}")
        dedup_on_pan = sum(1 for row in rows if link_fetchable(classify_link(row["link_url"])) and (
            ((row["link_url"] or "").strip() in url_on_pan)
            or ((row["link_url"] or "").strip() in pdf_trial_on_pan)
            or (extract_candidate_standard_no(row["file_no"], row["file_name"]) in stdno_on_pan)
        ))
        print(f"多维合并去重后已入网盘: {dedup_on_pan:,}")

        print("\n=== 待拉取候选（可用链接 且 未命中网盘） ===")
        print(f"候选总数: {candidate_rows:,}")
        for k, v in candidate_by_type.most_common():
            print(f"  {k}: {v:,}")

        # 实施状态分布
        status_rows = db.execute(
            text(
                """
                WITH classified AS (
                  SELECT
                    impl_status,
                    link_url,
                    file_no,
                    file_name
                  FROM wps_standard_query_records
                )
                SELECT impl_status, COUNT(*) FROM classified GROUP BY 1 ORDER BY 2 DESC
                """
            )
        ).all()
        print("\n=== 实施状态分布（全表） ===")
        for s, c in status_rows:
            print(f"  {s or '(空)'}: {c:,}")

        summary = {
            "total": total,
            "fetchable": fetchable_counter,
            "unavailable": unavailable_counter,
            "already_on_baidu_pan_dedup": dedup_on_pan,
            "candidates": candidate_rows,
            "candidates_by_type": dict(candidate_by_type),
            "link_types": dict(link_type_counter),
        }
        print("\n=== JSON ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
