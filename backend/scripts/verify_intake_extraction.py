#!/usr/bin/env python3
from pathlib import Path

from app.local_file_intake_service import extract_local_file_metadata
from app.standard_number import extract_standard_no_from_text, normalize_standard_no
from app.storage import filesystem_safe_filename, safe_stem, safe_upload_filename

CASES = [
    "GB/T 1568-2008-scan-copy.pdf",
    "GB/T 43556.1-2023 光纤光缆.pdf",
    "扫描件_归档_GBT43556.1-2023_v2(水印).pdf",
    "GB-T43556.1-2023_v2.pdf",
    "GB T 1568-2008 扫描版.pdf",
    "GB50016-2014 建筑设计防火规范.pdf",
    "04S520 埋地塑料排水管道施工.pdf",
    "会议纪要_2024年内部讨论稿.pdf",
    "folder/sub/file.pdf",
]

print("=== safe_upload_filename ===")
for name in CASES:
    print(name, "->", safe_upload_filename(name))

print("\n=== filesystem_safe_filename ===")
for name in CASES:
    print(name, "->", filesystem_safe_filename(name))

print("\n=== extraction ===")
for name in CASES:
    safe = safe_upload_filename(name)
    raw = extract_standard_no_from_text(safe_stem(safe)) or extract_standard_no_from_text(safe)
    norm = normalize_standard_no(raw).normalized
    meta = extract_local_file_metadata(Path(safe), original_name=safe)
    print(f"{name}\n  safe={safe}\n  raw={raw} norm={norm} title={meta.title}\n")
