"""治理流水线阶段：画像 → 自动决策 → OCR 任务。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.governance_service import ALL_GOVERNANCE_STATUSES
from app.settings_store import get_setting


def _upsert_setting(db: Session, key: str, value: str) -> None:
    item = db.get(models.SystemSetting, key)
    if item is None:
        db.add(models.SystemSetting(key=key, value=value, value_type="string", label=key))
    else:
        item.value = value


def count_unprofiled_urls(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(models.UrlSource)
            .where(
                models.UrlSource.governance_status.in_(("pending", "profiled", "error"))
                | models.UrlSource.governance_status.notin_(tuple(ALL_GOVERNANCE_STATUSES))
            )
        )
        or 0
    )


def count_undecided_resources(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(models.StandardResource)
            .where(models.StandardResource.auto_decision.is_(None))
        )
        or 0
    )


def read_pipeline_phase(db: Session) -> str:
    phase = (get_setting(db, "governance_pipeline_phase", "profiling") or "profiling").strip().lower()
    if phase not in {"profiling", "post_profile"}:
        return "profiling"
    return phase


def sync_pipeline_phase(db: Session) -> dict[str, int | str | bool]:
    """根据库内进度更新流水线阶段。"""
    unprofiled = count_unprofiled_urls(db)
    undecided = count_undecided_resources(db)
    previous = read_pipeline_phase(db)

    if unprofiled == 0:
        phase = "post_profile"
        profile_complete = True
    elif previous == "post_profile" and unprofiled > 0:
        phase = "profiling"
        profile_complete = False
    else:
        phase = previous
        profile_complete = phase == "post_profile"

    if phase != previous:
        _upsert_setting(db, "governance_pipeline_phase", phase)
    _upsert_setting(db, "governance_profile_complete", "true" if profile_complete else "false")

    return {
        "phase": phase,
        "profile_complete": profile_complete,
        "unprofiled_urls": unprofiled,
        "undecided_resources": undecided,
        "phase_changed": phase != previous,
    }


def should_skip_url_profiling(db: Session) -> bool:
    state = sync_pipeline_phase(db)
    return bool(state["profile_complete"])
