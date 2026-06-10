"""数据治理任务：URL 来源画像、审计、样本试跑与看板统计。"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.source_governance import (
    ALL_GOVERNANCE_STATUSES,
    GOV_BLACKLIST,
    GOV_CLUE_ONLY,
    GOV_DUPLICATE,
    GOV_HIGH_PRIORITY,
    GOV_INVALID,
    GOV_NEED_OCR,
    GOV_PAUSED,
    GOV_PROFILED,
    SAMPLE_FILTERS,
    extract_url_profile,
    profile_url_source_row,
)
from app.url_source_profiler import profile_url as legacy_profile_url


def log_process_audit(
    db: Session,
    *,
    process_name: str,
    action: str,
    status: str = "ok",
    target_type: str | None = None,
    target_id: int | None = None,
    message: str | None = None,
    detail: dict | None = None,
) -> models.ProcessAuditLog:
    row = models.ProcessAuditLog(
        process_name=process_name,
        action=action,
        target_type=target_type,
        target_id=target_id,
        status=status,
        message=message,
        detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
    )
    db.add(row)
    return row


def _official_domains(db: Session) -> set[str]:
    domains = {
        legacy_profile_url(item.base_url).host
        for item in db.scalars(select(models.TrustedSource)).all()
        if item.base_url
    }
    domains.discard(None)
    return domains


def derive_trusted_source_governance(source: models.TrustedSource) -> None:
    host = legacy_profile_url(source.base_url).host
    source.domain = host or source.domain
    if not source.source_role:
        if source.is_status_authority:
            source.source_role = "official"
        elif "补充" in (source.source_type or ""):
            source.source_role = "supplement"
        else:
            source.source_role = "catalog"
    source.status_authority_weight = source.status_authority_weight or (100 if source.is_status_authority else 30)
    source.metadata_weight = source.metadata_weight or min(100, max(40, source.trust_score))
    source.fulltext_weight = source.fulltext_weight or (70 if "online" in (source.capabilities or "") else 20)
    source.source_health_score = source.source_health_score or source.trust_score
    if source.governance_status in {"pending", "profiled", ""}:
        source.governance_status = GOV_PROFILED


def profile_trusted_sources(db: Session) -> int:
    updated = 0
    for source in db.scalars(select(models.TrustedSource)).all():
        derive_trusted_source_governance(source)
        updated += 1
    log_process_audit(
        db,
        process_name="source_governance",
        action="profile_trusted_sources",
        message=f"profiled trusted sources: {updated}",
        detail={"updated": updated},
    )
    return updated


def _apply_row_to_source(source: models.UrlSource, row: dict) -> None:
    source.host = row["host"]
    source.url_type = row["url_type"]
    source.file_ext = row["file_ext"]
    source.is_official_domain = row["is_official_domain"]
    source.is_cloud_drive = row["is_cloud_drive"]
    source.is_probable_pdf = row["is_probable_pdf"]
    source.is_probable_detail_page = row["is_probable_detail_page"]
    source.source_quality_score = row["source_quality_score"]
    source.governance_status = row["governance_status"]
    source.duplicate_group_key = row["duplicate_group_key"]


def _empty_batch_stats() -> dict:
    return {
        "profiled": 0,
        "official_count": 0,
        "pdf_count": 0,
        "cloud_drive_count": 0,
        "duplicate_count": 0,
        "invalid_count": 0,
        "need_ocr_count": 0,
        "high_priority_count": 0,
        "clue_only_count": 0,
        "blacklist_candidate_count": 0,
    }


def _accumulate_stats(stats: dict, row: dict) -> None:
    stats["profiled"] += 1
    if row["is_official_domain"]:
        stats["official_count"] += 1
    if row["is_probable_pdf"]:
        stats["pdf_count"] += 1
    if row["is_cloud_drive"]:
        stats["cloud_drive_count"] += 1
    if row["governance_status"] == GOV_DUPLICATE:
        stats["duplicate_count"] += 1
    if row["governance_status"] == GOV_INVALID:
        stats["invalid_count"] += 1
    if row["governance_status"] == GOV_NEED_OCR:
        stats["need_ocr_count"] += 1
    if row["governance_status"] == GOV_HIGH_PRIORITY:
        stats["high_priority_count"] += 1
    if row["governance_status"] == GOV_CLUE_ONLY:
        stats["clue_only_count"] += 1
    if row["governance_status"] in {GOV_BLACKLIST, GOV_PAUSED}:
        stats["blacklist_candidate_count"] += 1


def _is_duplicate_key(db: Session, key: str | None, source_id: int, batch_counts: Counter[str]) -> bool:
    if not key:
        return False
    if batch_counts.get(key, 0) > 1:
        return True
    existing = db.scalar(
        select(func.count())
        .select_from(models.UrlSource)
        .where(models.UrlSource.duplicate_group_key == key, models.UrlSource.id != source_id)
    )
    return bool(existing and existing > 0)


def _profile_source_list(
    db: Session,
    sources: list[models.UrlSource],
    *,
    official_domains: set[str],
    run: models.SourceGovernanceRun,
    dry_run: bool,
    create_candidates: bool = True,
) -> tuple[int, int, dict]:
    success = 0
    failed = 0
    stats = _empty_batch_stats()

    previews: list[tuple[models.UrlSource, dict]] = []
    for source in sources:
        previews.append(
            (
                source,
                profile_url_source_row(source.url, extra_official_domains=official_domains),
            )
        )

    batch_key_counts = Counter(
        preview["duplicate_group_key"] for _, preview in previews if preview["duplicate_group_key"]
    )

    for source, preview in previews:
        run.processed += 1
        try:
            dup_key = preview["duplicate_group_key"]
            is_dup = _is_duplicate_key(db, dup_key, source.id, batch_key_counts)
            row = (
                profile_url_source_row(
                    source.url,
                    extra_official_domains=official_domains,
                    is_duplicate=is_dup,
                    source_link_status=source.status,
                )
                if is_dup
                else preview
            )
            profile = row["profile"]

            if not dry_run:
                _apply_row_to_source(source, row)
                if create_candidates:
                    db.add(
                        models.SourceRecordCandidate(
                            run_id=run.id,
                            url_source_id=source.id,
                            candidate_type=row["url_type"],
                            source_url=source.url,
                            host=row["host"],
                            url_type=row["url_type"],
                            quality_score=row["source_quality_score"],
                            duplicate_group_key=row["duplicate_group_key"],
                            governance_status=row["governance_status"],
                            evidence_json=json.dumps(
                                {"url": source.url, "profile": profile.to_dict(), "score": row["score"]},
                                ensure_ascii=False,
                            ),
                        )
                    )

            log_process_audit(
                db,
                process_name="source_governance",
                action="profile_url_source",
                target_type="url_source",
                target_id=source.id,
                message=row["governance_status"],
                detail={
                    "run_id": run.id,
                    "url_type": row["url_type"],
                    "score": row["score"],
                    "governance_status": row["governance_status"],
                    "duplicate_group_key": row["duplicate_group_key"],
                    "dry_run": dry_run,
                },
            )

            success += 1
            _accumulate_stats(stats, row)
        except Exception as exc:
            failed += 1
            if not dry_run:
                source.governance_status = "error"
            log_process_audit(
                db,
                process_name="source_governance",
                action="profile_url_source",
                status="failed",
                target_type="url_source",
                target_id=source.id,
                message=str(exc),
                detail={"run_id": run.id},
            )

    return success, failed, stats


def _build_url_source_query(
    db: Session,
    *,
    source_id: int | None,
    host: str | None,
    only_ungoverned: bool,
    after_id: int = 0,
):
    query = select(models.UrlSource).order_by(models.UrlSource.id.asc())
    if after_id > 0:
        query = query.where(models.UrlSource.id > after_id)
    if source_id is not None:
        query = query.where(models.UrlSource.id == source_id)
    if host:
        needle = host.strip().lower()
        query = query.where(func.lower(models.UrlSource.host).like(f"%{needle}%"))
    if only_ungoverned:
        query = query.where(
            models.UrlSource.governance_status.in_(("pending", "profiled", "error"))
            | models.UrlSource.governance_status.notin_(tuple(ALL_GOVERNANCE_STATUSES))
        )
    return query


def profile_url_sources_batch(
    db: Session,
    *,
    limit: int = 1000,
    source_id: int | None = None,
    host: str | None = None,
    only_ungoverned: bool = True,
    dry_run: bool = False,
    after_id: int = 0,
    run_type: str = "profile_url_sources",
    config_extra: dict | None = None,
) -> tuple[models.SourceGovernanceRun | None, dict]:
    limit = max(1, min(limit, 10000))
    official_domains = _official_domains(db)
    rows = list(
        db.scalars(
            _build_url_source_query(
                db,
                source_id=source_id,
                host=host,
                only_ungoverned=only_ungoverned,
                after_id=after_id,
            ).limit(limit)
        ).all()
    )

    config = {
        "limit": limit,
        "source_id": source_id,
        "host": host,
        "only_ungoverned": only_ungoverned,
        "dry_run": dry_run,
        "after_id": after_id,
        **(config_extra or {}),
    }

    run = models.SourceGovernanceRun(
        run_type=run_type,
        status="running",
        total=len(rows),
        config_json=json.dumps(config, ensure_ascii=False),
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()

    success, failed, stats = _profile_source_list(
        db,
        rows,
        official_domains=official_domains,
        run=run,
        dry_run=dry_run,
    )

    run.success = success
    run.failed = failed
    run.status = "finished"
    run.finished_at = datetime.now(UTC)
    run.message = json.dumps({"dry_run": dry_run, **stats}, ensure_ascii=False)
    log_process_audit(
        db,
        process_name="source_governance",
        action="profile_url_sources_batch",
        message=f"processed={run.processed} success={success} failed={failed} dry_run={dry_run}",
        detail={"run_id": run.id, **stats},
    )

    result = {"total": len(rows), **stats, "dry_run": dry_run, "run_id": run.id, "failed": failed}
    if dry_run:
        db.rollback()
        result["run_id"] = None
        return None, result

    db.commit()
    db.refresh(run)
    return run, result


def run_sample_profiling(
    db: Session,
    *,
    sample_type: str,
    limit: int = 1000,
    dry_run: bool = False,
) -> dict:
    if sample_type not in SAMPLE_FILTERS:
        raise ValueError(f"unsupported sample_type: {sample_type}")

    limit = max(1, min(limit, 5000))
    official_domains = _official_domains(db)
    predicate = SAMPLE_FILTERS[sample_type]

    scanned = 0
    matched: list[models.UrlSource] = []
    cursor = 0
    while len(matched) < limit:
        chunk = db.scalars(
            select(models.UrlSource)
            .where(models.UrlSource.id > cursor)
            .order_by(models.UrlSource.id.asc())
            .limit(min(2000, limit * 3))
        ).all()
        if not chunk:
            break
        cursor = chunk[-1].id
        for source in chunk:
            scanned += 1
            profile = extract_url_profile(source.url, extra_official_domains=official_domains)
            if predicate(profile):
                matched.append(source)
                if len(matched) >= limit:
                    break

    run = models.SourceGovernanceRun(
        run_type="run_sample",
        status="running",
        total=len(matched),
        config_json=json.dumps(
            {"sample_type": sample_type, "limit": limit, "dry_run": dry_run, "scanned": scanned},
            ensure_ascii=False,
        ),
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()

    success, failed, stats = _profile_source_list(
        db,
        matched,
        official_domains=official_domains,
        run=run,
        dry_run=dry_run,
    )
    run.success = success
    run.failed = failed
    run.status = "finished"
    run.finished_at = datetime.now(UTC)
    run.message = json.dumps({"sample_type": sample_type, "dry_run": dry_run, **stats}, ensure_ascii=False)

    result = {
        "sample_type": sample_type,
        "scanned": scanned,
        "total": len(matched),
        **stats,
        "dry_run": dry_run,
    }
    log_process_audit(
        db,
        process_name="source_governance",
        action="run_sample",
        message=f"sample_type={sample_type} total={len(matched)}",
        detail={"run_id": run.id, **result},
    )

    if dry_run:
        db.rollback()
        result["run_id"] = None
    else:
        db.commit()
        result["run_id"] = run.id

    return result


def run_url_source_profiling(
    db: Session,
    *,
    batch_size: int = 1000,
    after_id: int = 0,
    only_pending: bool = True,
    create_candidates: bool = True,
) -> models.SourceGovernanceRun:
    del create_candidates
    run, _ = profile_url_sources_batch(
        db,
        limit=batch_size,
        only_ungoverned=only_pending,
        after_id=after_id,
        dry_run=False,
    )
    if run is None:
        raise RuntimeError("profile_url_sources_batch returned no run")
    return run


def _duplicate_url_count(db: Session) -> int:
    subq = (
        select(models.UrlSource.duplicate_group_key)
        .where(models.UrlSource.duplicate_group_key.is_not(None))
        .group_by(models.UrlSource.duplicate_group_key)
        .having(func.count() > 1)
    ).subquery()
    return db.scalar(select(func.count()).select_from(subq)) or 0


def governance_dashboard(db: Session) -> dict:
    total = db.scalar(select(func.count()).select_from(models.UrlSource)) or 0
    unprofiled = db.scalar(
        select(func.count())
        .select_from(models.UrlSource)
        .where(
            models.UrlSource.governance_status.in_(("pending", "profiled", "error"))
            | models.UrlSource.governance_status.notin_(tuple(ALL_GOVERNANCE_STATUSES))
        )
    ) or 0
    profiled = max(0, total - unprofiled)
    official_count = db.scalar(
        select(func.count()).select_from(models.UrlSource).where(models.UrlSource.is_official_domain.is_(True))
    ) or 0
    pdf_count = db.scalar(
        select(func.count()).select_from(models.UrlSource).where(models.UrlSource.is_probable_pdf.is_(True))
    ) or 0
    cloud_drive_count = db.scalar(
        select(func.count()).select_from(models.UrlSource).where(models.UrlSource.is_cloud_drive.is_(True))
    ) or 0
    invalid_count = db.scalar(
        select(func.count()).select_from(models.UrlSource).where(models.UrlSource.governance_status == GOV_INVALID)
    ) or 0
    need_ocr_count = db.scalar(
        select(func.count()).select_from(models.UrlSource).where(models.UrlSource.governance_status == GOV_NEED_OCR)
    ) or 0
    high_priority_count = db.scalar(
        select(func.count())
        .select_from(models.UrlSource)
        .where(models.UrlSource.governance_status == GOV_HIGH_PRIORITY)
    ) or 0
    clue_only_count = db.scalar(
        select(func.count()).select_from(models.UrlSource).where(models.UrlSource.governance_status == GOV_CLUE_ONLY)
    ) or 0
    duplicate_count = _duplicate_url_count(db)

    url_status_rows = db.execute(
        select(models.UrlSource.governance_status, func.count())
        .group_by(models.UrlSource.governance_status)
        .order_by(models.UrlSource.governance_status)
    ).all()
    trusted_status_rows = db.execute(
        select(models.TrustedSource.governance_status, func.count())
        .group_by(models.TrustedSource.governance_status)
        .order_by(models.TrustedSource.governance_status)
    ).all()

    return {
        "total": total,
        "profiled": profiled,
        "unprofiled": unprofiled,
        "official_count": official_count,
        "pdf_count": pdf_count,
        "cloud_drive_count": cloud_drive_count,
        "duplicate_count": duplicate_count,
        "invalid_count": invalid_count,
        "need_ocr_count": need_ocr_count,
        "high_priority_count": high_priority_count,
        "clue_only_count": clue_only_count,
        "blacklist_candidate_count": db.scalar(
            select(func.count())
            .select_from(models.UrlSource)
            .where(models.UrlSource.governance_status.in_((GOV_BLACKLIST, GOV_PAUSED)))
        )
        or 0,
        "url_sources": {status or "unknown": count for status, count in url_status_rows},
        "trusted_sources": {status or "unknown": count for status, count in trusted_status_rows},
        "recent_runs": [
            {
                "id": item.id,
                "run_type": item.run_type,
                "status": item.status,
                "total": item.total,
                "success": item.success,
                "failed": item.failed,
                "message": item.message,
                "started_at": item.started_at,
                "finished_at": item.finished_at,
            }
            for item in db.scalars(
                select(models.SourceGovernanceRun).order_by(models.SourceGovernanceRun.id.desc()).limit(10)
            ).all()
        ],
    }


def governance_summary(db: Session) -> dict:
    return governance_dashboard(db)
