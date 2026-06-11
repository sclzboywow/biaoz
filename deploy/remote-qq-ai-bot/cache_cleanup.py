#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Remove local cached files older than LOCAL_CACHE_MAX_AGE_DAYS (default 7)."""

from __future__ import annotations

import os
import time
from pathlib import Path


def cache_max_age_days() -> int:
    raw = os.getenv("LOCAL_CACHE_MAX_AGE_DAYS", "7").strip()
    try:
        days = int(raw)
    except ValueError:
        days = 7
    return max(1, min(days, 365))


def default_cache_dirs() -> list[Path]:
    roots = os.getenv("LOCAL_CACHE_DIRS", "").strip()
    if roots:
        return [Path(p.strip()).expanduser() for p in roots.split(";") if p.strip()]
    return [
        Path(os.getenv("QQ_FILE_DOWNLOAD_DIR", "/home/ubuntu/qq-ai-bot/downloads")).expanduser(),
        Path(os.getenv("LIBRARY_DOWNLOAD_DIR", "/home/ubuntu/qq-ai-bot/downloads/delivery")).expanduser(),
        Path(os.getenv("NAPCAT_FILE_STAGING_DIR", "/home/ubuntu/napcat/config/outbound")).expanduser(),
    ]


def cleanup_local_cache(*, max_age_days: int | None = None, dirs: list[Path] | None = None) -> dict:
    days = cache_max_age_days() if max_age_days is None else max(1, int(max_age_days))
    cutoff = time.time() - days * 86400
    targets = dirs or default_cache_dirs()
    removed_files = 0
    freed_bytes = 0
    scanned_dirs: list[str] = []

    for root in targets:
        if not root.exists():
            continue
        scanned_dirs.append(str(root))
        if root.is_file():
            if root.stat().st_mtime < cutoff:
                freed_bytes += root.stat().st_size
                root.unlink(missing_ok=True)
                removed_files += 1
            continue
        for path in sorted(root.rglob("*"), reverse=True):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    freed_bytes += path.stat().st_size
                    path.unlink(missing_ok=True)
                    removed_files += 1
                elif path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
            except OSError:
                continue

    return {
        "max_age_days": days,
        "removed_files": removed_files,
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / 1024 / 1024, 2),
        "dirs": scanned_dirs,
    }


def main() -> int:
    result = cleanup_local_cache()
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
