#!/usr/bin/env python3
"""Run 5 local-file-intake recognition scenario checks."""

from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from app import models
from app.config import get_settings
from app.database import SessionLocal
from app.local_file_intake_service import analyze_local_file, create_intake_task, delete_intake_task
from app.storage import check_storage_root


async def upload_bytes(db: Session, filename: str, content: bytes) -> models.LocalFileIntakeTask:
    upload = UploadFile(
        filename=filename,
        file=io.BytesIO(content),
        headers=Headers({"content-type": "application/pdf"}),
    )
    return await create_intake_task(db, upload)


def summarize_task(task: models.LocalFileIntakeTask) -> dict:
    return {
        "task_id": task.id,
        "file_name": task.original_file_name,
        "extracted_standard_no": task.extracted_standard_no,
        "normalized_standard_no": task.normalized_standard_no,
        "extracted_title": task.extracted_title,
        "decision": task.decision,
        "confidence_score": task.confidence_score,
        "risk_level": task.risk_level,
        "decision_reason": task.decision_reason,
        "candidates": [
            {
                "type": c.candidate_type,
                "id": c.candidate_id,
                "standard_no": c.standard_no,
                "standard_name": c.standard_name,
                "score": c.match_score,
                "advice": c.decision_advice,
                "reason": c.match_reason,
            }
            for c in sorted(task.candidates, key=lambda x: x.match_score, reverse=True)
        ],
    }


async def run_case(db: Session, name: str, filename: str, content: bytes) -> dict:
    task = await upload_bytes(db, filename, content)
    try:
        task = analyze_local_file(db, task.id)
        result = summarize_task(task)
        result["case"] = name
        return result
    finally:
        try:
            delete_intake_task(db, task.id)
        except Exception:
            pass


async def main() -> int:
    db = SessionLocal()
    settings = get_settings()
    storage = check_storage_root(db, settings.storage_root)
    cases: list[dict] = []

    try:
        row = db.execute(
            text(
                """
                SELECT dv.file_path, dv.file_hash, d.standard_no, d.normalized_standard_no, d.title
                FROM document_versions dv
                JOIN documents d ON d.id = dv.document_id
                WHERE dv.file_path IS NOT NULL AND dv.file_path <> ''
                ORDER BY dv.id DESC LIMIT 1
                """
            )
        ).fetchone()
        if row is None:
            print("No document version found for scenario 1/2")
            return 1

        src_path = storage.root / row.file_path
        if not src_path.exists():
            print(f"Missing archived file: {src_path}")
            return 1

        original_bytes = src_path.read_bytes()
        cases.append(
            await run_case(
                db,
                "1. 已存在完全相同 PDF",
                Path(row.file_path).name,
                original_bytes,
            )
        )

        mutated = original_bytes + b"\n% intake-test-marker\n"
        cases.append(
            await run_case(
                db,
                "2. 标准号相同但 hash 不同 PDF",
                f"{row.standard_no or 'same-std'}-scan-copy.pdf",
                mutated,
            )
        )

        resource = db.execute(
            text(
                """
                SELECT sr.standard_no, sr.normalized_standard_no, sr.standard_name
                FROM standard_resources sr
                WHERE sr.normalized_standard_no IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM documents d
                    WHERE d.normalized_standard_no = sr.normalized_standard_no
                       OR d.standard_no = sr.standard_no
                  )
                ORDER BY sr.id DESC LIMIT 1
                """
            )
        ).fetchone()
        if resource:
            std_no = resource.standard_no or resource.normalized_standard_no
            title = resource.standard_name[:40]
            content = f"fake pdf for {std_no}".encode() * 100
            cases.append(
                await run_case(
                    db,
                    "3. 本地没有但可信源索引里有",
                    f"{std_no} {title}.pdf",
                    content,
                )
            )

            messy_name = f"扫描件_归档_{std_no.replace('/', '-').replace(' ', '')}_v2(水印).pdf"
            cases.append(
                await run_case(
                    db,
                    "4. 文件名不规范但含标准号",
                    messy_name,
                    content + b"-messy",
                )
            )
        else:
            cases.extend(
                [
                    {"case": "3. 本地没有但可信源索引里有", "error": "no suitable standard_resource"},
                    {"case": "4. 文件名不规范但含标准号", "error": "skipped"},
                ]
            )

        cases.append(
            await run_case(
                db,
                "5. 完全无法识别标准号的文件",
                "会议纪要_2024年内部讨论稿.pdf",
                b"%PDF-1.4\n% no standard number\n" + b"x" * 200,
            )
        )

        print(json.dumps(cases, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
