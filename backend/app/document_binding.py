"""Project document binding eligibility rules."""

from __future__ import annotations

from app import models
from app.settings_store import get_bool_setting


def is_document_project_bindable(
    document: models.Document,
    *,
    exclude_quarantine: bool | None = None,
    exclude_conflict: bool | None = None,
    db=None,
) -> bool:
    if exclude_quarantine is None and db is not None:
        exclude_quarantine = get_bool_setting(db, "project_binding_exclude_quarantine", default=True)
    if exclude_conflict is None and db is not None:
        exclude_conflict = get_bool_setting(db, "project_binding_exclude_conflict", default=True)
    if exclude_quarantine is None:
        exclude_quarantine = True
    if exclude_conflict is None:
        exclude_conflict = True

    review = document.review_status or ""
    valid = document.valid_status or ""
    metadata = document.metadata_status or ""

    if exclude_quarantine and (
        review == "风险隔离"
        or valid == "隔离留存"
        or metadata == "系统隔离"
        or document.classification_decision == "quarantine"
    ):
        return False

    if exclude_conflict and (
        review == "冲突拦截"
        or valid == "冲突拦截"
        or metadata == "系统冲突拦截"
        or document.classification_decision == "conflict_block"
    ):
        return False

    if valid in {"来源确认废止", "疑似被替代"}:
        return False

    if review in {"自动确认", "自动分类"} and valid in {
        "来源确认现行",
        "系统推定现行",
        "待生效",
        "系统推定未知",
    }:
        return True

    if review in {"已确认"} and valid == "现行":
        return True

    return False
