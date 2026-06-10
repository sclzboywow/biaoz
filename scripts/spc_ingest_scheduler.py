from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATS_FILE = ROOT / "logs" / "spc-category-stats.json"

DEFAULT_CATEGORIES = ["CN", "QT", "DFBZ", "TC", "QYBZ", "JJ"]


def _empty_stats() -> dict[str, dict[str, int | str]]:
    return {category: {"ok": 0, "skipped": 0, "errors": 0, "unavailable": 0, "attempts": 0} for category in DEFAULT_CATEGORIES}


def load_stats() -> dict[str, dict[str, int | str]]:
    if not STATS_FILE.exists():
        return _empty_stats()
    try:
        payload = json.loads(STATS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_stats()
    stats = _empty_stats()
    for category, values in payload.items():
        if category not in stats or not isinstance(values, dict):
            continue
        stats[category].update({key: int(values.get(key, 0) or 0) for key in ("ok", "skipped", "errors", "unavailable", "attempts")})
    return stats


def save_stats(stats: dict[str, dict[str, int | str]]) -> None:
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {category: {**values, "updated_at": datetime.now(UTC).isoformat()} for category, values in stats.items()}
    STATS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def record_batch(category: str, *, ok: int, skipped: int, errors: int, unavailable: int, total: int) -> None:
    stats = load_stats()
    bucket = stats.setdefault(
        category,
        {"ok": 0, "skipped": 0, "errors": 0, "unavailable": 0, "attempts": 0},
    )
    bucket["ok"] = int(bucket.get("ok", 0)) + ok
    bucket["skipped"] = int(bucket.get("skipped", 0)) + skipped
    bucket["errors"] = int(bucket.get("errors", 0)) + errors
    bucket["unavailable"] = int(bucket.get("unavailable", 0)) + unavailable
    bucket["attempts"] = int(bucket.get("attempts", 0)) + total
    save_stats(stats)


def category_score(category: str, stats: dict[str, dict[str, int | str]] | None = None) -> float:
    bucket = (stats or load_stats()).get(category) or {}
    attempts = int(bucket.get("attempts", 0) or 0)
    if attempts <= 0:
        return 0.5
    ok = int(bucket.get("ok", 0) or 0)
    skipped = int(bucket.get("skipped", 0) or 0)
    unavailable = int(bucket.get("unavailable", 0) or 0)
    productive = ok + skipped
    success_rate = productive / attempts
    unavailable_rate = unavailable / attempts
    return max(0.05, success_rate - unavailable_rate * 0.75)


def rank_categories(categories: list[str] | None = None) -> list[str]:
    categories = categories or DEFAULT_CATEGORIES
    stats = load_stats()
    return sorted(categories, key=lambda item: category_score(item, stats), reverse=True)


def suggest_limit(category: str, base_limit: int) -> int:
    if category in {"CN", "JJ"}:
        floor = 200 if category == "CN" else 150
        return max(base_limit * (3 if category == "CN" else 2), floor)
    score = category_score(category)
    if score >= 0.7:
        return max(base_limit, int(base_limit * 1.5))
    if score <= 0.2:
        return max(5, int(base_limit * 0.5))
    return base_limit


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Rank SPC ingest categories by recent success rate.")
    parser.add_argument("--rank", action="store_true", help="Print comma-separated categories best-first.")
    parser.add_argument("--suggest-limit", metavar="CATEGORY")
    parser.add_argument("--base-limit", type=int, default=50)
    args = parser.parse_args()
    if args.suggest_limit:
        print(suggest_limit(args.suggest_limit, args.base_limit))
    else:
        print(",".join(rank_categories()))
