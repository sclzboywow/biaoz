from __future__ import annotations

import argparse
import csv
import html
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.database import SessionLocal  # noqa: E402
from app.models import SourceStatus, UrlSource  # noqa: E402


def clean_text(value: str | None) -> str:
    return html.unescape((value or "").strip())


def import_csv(path: Path, encoding: str = "gb18030", batch_size: int = 1000) -> dict[str, int]:
    seen_in_file: set[str] = set()
    stats = {
        "rows": 0,
        "with_url": 0,
        "inserted": 0,
        "existing": 0,
        "duplicate_in_file": 0,
        "missing_url": 0,
    }

    with SessionLocal() as db:
        existing_urls = set(url for (url,) in db.query(UrlSource.url).all())

        with path.open("r", encoding=encoding, newline="") as file_obj:
            reader = csv.DictReader(file_obj)
            if not reader.fieldnames or len(reader.fieldnames) < 4:
                raise ValueError("CSV 表头不完整，至少需要状态、编号、名称、下载地址。")

            status_key, code_key, name_key, url_key = reader.fieldnames[:4]
            id_key = reader.fieldnames[4] if len(reader.fieldnames) > 4 else None

            for row in reader:
                stats["rows"] += 1
                url = clean_text(row.get(url_key))
                if not url:
                    stats["missing_url"] += 1
                    continue

                stats["with_url"] += 1
                if url in seen_in_file:
                    stats["duplicate_in_file"] += 1
                    continue
                seen_in_file.add(url)

                if url in existing_urls:
                    stats["existing"] += 1
                    continue

                status = clean_text(row.get(status_key))
                code = clean_text(row.get(code_key))
                name = clean_text(row.get(name_key))
                source_id = clean_text(row.get(id_key)) if id_key else ""
                remark_parts = []
                if status:
                    remark_parts.append(f"原始状态：{status}")
                if code:
                    remark_parts.append(f"编号：{code}")
                if source_id:
                    remark_parts.append(f"识别码：{source_id}")

                db.add(
                    UrlSource(
                        url=url,
                        source_name=name or code or url,
                        source_type="附件直链",
                        category="标准规范",
                        check_frequency="manual",
                        status=SourceStatus.normal.value,
                        remark="；".join(remark_parts) if remark_parts else None,
                    )
                )
                existing_urls.add(url)
                stats["inserted"] += 1

                if stats["inserted"] % batch_size == 0:
                    db.commit()

        db.commit()

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Import URL sources from CSV.")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--encoding", default="gb18030")
    args = parser.parse_args()

    csv_path = args.csv_path if args.csv_path.is_absolute() else ROOT / args.csv_path
    stats = import_csv(csv_path, args.encoding)
    for key, value in stats.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
