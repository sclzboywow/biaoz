"""
排查 WPS 国标电子书直连 PDF 中，本地库尚未归档的数量。

夸克链接本脚本不统计（后续另处理）。

用法:
  backend/.venv/Scripts/python.exe scripts/report_wps_ebook_gap.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.standard_number import normalize_standard_no  # noqa: E402

BAIDU_PAN_COND = """
    dv.file_path LIKE 'baidupan:%'
    OR dv.remark LIKE '%remote_uri%baidupan:%'
"""


def extract_standard_no(file_no: str | None, file_name: str | None) -> str | None:
    for value in (file_no, file_name):
        if not value:
            continue
        text_value = str(value).strip()
        if not text_value:
            continue
        if "公告" in text_value and not re.search(r"GB|JGJ|CJJ|CECS|DB|T/", text_value, re.I):
            continue
        parts = normalize_standard_no(text_value)
        if parts.normalized:
            return parts.normalized
        match = re.search(
            r"(GB/T\s?\d{4,5}-\d{4}|GB\s?\d{4,5}-\d{4}|JGJ/?T?\s?\d+-?\d{4}|"
            r"CJJ/?T?\s?\d+-?\d{4}|[A-Z]{2,8}/T?\s?\d[\w.-]*-\d{4})",
            text_value,
            re.I,
        )
        if match:
            return normalize_standard_no(match.group(0)).normalized
    return None


def pdf_basename(url: str | None) -> str | None:
    if not url:
        return None
    path = url.split("?", 1)[0].rstrip("/")
    if not path:
        return None
    name = path.rsplit("/", 1)[-1]
    return name.lower() if name else None


def main() -> None:
    with SessionLocal() as db:
        ebook_pdf_total = db.execute(
            text(
                """
                SELECT count(1) FROM wps_standard_query_records
                WHERE link_url LIKE '%ebook.chinabuilding.com.cn%'
                  AND link_url LIKE '%/pdf/%'
                """
            )
        ).scalar() or 0

        ebook_page_total = db.execute(
            text(
                """
                SELECT count(1) FROM wps_standard_query_records
                WHERE link_url LIKE '%ebook.chinabuilding.com.cn%'
                  AND link_url NOT LIKE '%/pdf/%'
                """
            )
        ).scalar() or 0

        # 严格「库里有 PDF 归档」：必须有 document_version，而非仅有元数据 pdf_trial_url
        urls_in_lib = {
            row[0]
            for row in db.execute(
                text(
                    """
                    SELECT DISTINCT us.url
                    FROM url_sources us
                    JOIN document_versions dv ON dv.url_source_id = us.id
                    WHERE us.url IS NOT NULL
                      AND btrim(us.url) <> ''
                    """
                )
            ).all()
            if row[0]
        }

        pdf_trial_in_lib = {
            row[0]
            for row in db.execute(
                text(
                    """
                    SELECT DISTINCT sr.pdf_trial_url
                    FROM standard_resources sr
                    JOIN standard_file_matches sfm ON sfm.standard_resource_id = sr.id
                    JOIN document_versions dv ON dv.id = sfm.document_version_id
                    WHERE sr.pdf_trial_url IS NOT NULL
                      AND btrim(sr.pdf_trial_url) <> ''
                    """
                )
            ).all()
            if row[0]
        }

        std_in_lib = {
            row[0]
            for row in db.execute(
                text(
                    """
                    SELECT DISTINCT COALESCE(d.normalized_standard_no, d.standard_no)
                    FROM documents d
                    JOIN document_versions dv ON dv.document_id = d.id
                    WHERE COALESCE(d.normalized_standard_no, d.standard_no) IS NOT NULL
                    """
                )
            ).all()
            if row[0]
        }

        guobiao_pdf_trial_meta = {
            row[0]
            for row in db.execute(
                text(
                    """
                    SELECT DISTINCT sr.pdf_trial_url
                    FROM standard_resources sr
                    JOIN trusted_sources ts ON ts.id = sr.source_id
                    WHERE ts.adapter_key = 'guobiao_ebook'
                      AND sr.pdf_trial_url IS NOT NULL
                      AND btrim(sr.pdf_trial_url) <> ''
                    """
                )
            ).all()
            if row[0]
        }

        rows = db.execute(
            text(
                """
                SELECT wps_record_id, file_no, file_name, link_url, impl_status
                FROM wps_standard_query_records
                WHERE link_url LIKE '%ebook.chinabuilding.com.cn%'
                  AND link_url LIKE '%/pdf/%'
                """
            )
        ).mappings().all()

        in_lib = 0
        not_in_lib = 0
        hit_counter: Counter[str] = Counter()
        not_in_lib_by_status: Counter[str | None] = Counter()
        not_in_lib_has_stdno = 0
        not_in_lib_no_stdno = 0
        samples: list[dict] = []

        for row in rows:
            link = (row["link_url"] or "").strip()
            std_no = extract_standard_no(row["file_no"], row["file_name"])
            hits: list[str] = []

            if link and link in urls_in_lib:
                hits.append("url_sources")
            if link and link in pdf_trial_in_lib:
                hits.append("pdf_trial_match")
            if std_no and std_no in std_in_lib:
                hits.append("standard_no")

            has_file = bool(hits)
            has_meta_only = bool(link and link in guobiao_pdf_trial_meta and not has_file)

            if has_file:
                in_lib += 1
                for h in hits:
                    hit_counter[h] += 1
            else:
                not_in_lib += 1
                not_in_lib_by_status[row["impl_status"]] += 1
                if std_no:
                    not_in_lib_has_stdno += 1
                else:
                    not_in_lib_no_stdno += 1
                if len(samples) < 8:
                    samples.append(
                        {
                            "wps_record_id": row["wps_record_id"],
                            "file_no": row["file_no"],
                            "file_name": (row["file_name"] or "")[:60],
                            "impl_status": row["impl_status"],
                            "standard_no": std_no,
                            "link": link[:100],
                        }
                    )

        print("=== 国标电子书 PDF（WPS）===")
        print(f"直连 PDF 总数: {ebook_pdf_total:,}")
        print(f"详情页(非PDF，本次不采集): {ebook_page_total:,}")
        print()
        meta_only_count = sum(
            1
            for row in rows
            if (row["link_url"] or "").strip() in guobiao_pdf_trial_meta
            and not (
                ((row["link_url"] or "").strip() in urls_in_lib)
                or ((row["link_url"] or "").strip() in pdf_trial_in_lib)
                or (
                    extract_standard_no(row["file_no"], row["file_name"])
                    and extract_standard_no(row["file_no"], row["file_name"]) in std_in_lib
                )
            )
        )

        print("=== 库内命中（严格：须有 PDF 归档，多维去重） ===")
        print(f"已有 PDF 归档: {in_lib:,}")
        for key, count in hit_counter.most_common():
            print(f"  维度 {key}: {count:,}")
        print(f"仅有元数据 pdf_trial_url、无 PDF 文件: {meta_only_count:,}")
        print()
        print("=== 库内缺口（可尝试归档） ===")
        print(f"库中没有 PDF: {not_in_lib:,}")
        print(f"  其中能解析出标准号: {not_in_lib_has_stdno:,}")
        print(f"  无法解析标准号(多为公告类): {not_in_lib_no_stdno:,}")
        print("  实施状态分布:")
        for status, count in not_in_lib_by_status.most_common():
            print(f"    {status or '(空)'}: {count:,}")
        print()
        print("缺口样例:")
        print(json.dumps(samples, ensure_ascii=False, indent=2))

        summary = {
            "ebook_pdf_total": ebook_pdf_total,
            "ebook_page_skipped": ebook_page_total,
            "in_library_with_pdf": in_lib,
            "metadata_only_no_pdf": meta_only_count,
            "not_in_library": not_in_lib,
            "not_in_library_has_standard_no": not_in_lib_has_stdno,
            "not_in_library_no_standard_no": not_in_lib_no_stdno,
            "hit_dimensions": dict(hit_counter),
            "not_in_library_by_status": {str(k): v for k, v in not_in_lib_by_status.items()},
        }
        print("\n=== JSON ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
