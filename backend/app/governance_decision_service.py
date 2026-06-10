"""批量自动治理决策与异常监督查询。"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import models
from app.alerts import upsert_pending_alert
from app.governance_decision_engine import (
    DECISION_AUTO_CONFIRMED,
    DECISION_AUTO_DOWNGRADED,
    DECISION_AUTO_MERGED,
    DECISION_AUTO_REJECTED,
    DECISION_NEED_REVIEW,
    RISK_HIGH,
    GovernanceDecisionResult,
    build_evidence_bundle,
    make_governance_decision,
)

PROCESS_TYPE = "GOVERNANCE_DECISION"
SYSTEM_DECIDER = "governance-engine"


def log_governance_decision_audit(
    db: Session,
    *,
    step_name: str,
    target_type: str,
    target_id: int,
    source_id: int | None,
    result: str,
    confidence_score: int | None = None,
    input_summary: str | None = None,
    output_summary: str | None = None,
    error_message: str | None = None,
    status: str = "ok",
) -> models.ProcessAuditLog:
    row = models.ProcessAuditLog(
        process_name="governance_decision",
        process_type=PROCESS_TYPE,
        step_name=step_name,
        action=step_name,
        target_type=target_type,
        target_id=target_id,
        source_id=source_id,
        status=status,
        message=result,
        confidence_score=confidence_score,
        input_summary=input_summary,
        output_summary=output_summary,
        error_message=error_message,
        detail_json=json.dumps(
            {
                "result": result,
                "confidence_score": confidence_score,
                "source_id": source_id,
            },
            ensure_ascii=False,
        ),
    )
    db.add(row)
    return row


def _apply_decision_to_resource(resource: models.StandardResource, result: GovernanceDecisionResult) -> None:
    resource.auto_decision = result.decision
    resource.confidence_score = result.confidence_score
    resource.decision_reason = result.decision_reason
    resource.risk_level = result.risk_level
    resource.last_governed_at = datetime.now(UTC)

    if result.decision == DECISION_AUTO_CONFIRMED:
        resource.system_status = resource.system_status or "来源确认现行"
        resource.manual_status = resource.manual_status or "自动确认"
    elif result.decision == DECISION_AUTO_DOWNGRADED:
        resource.system_status = resource.system_status or "仅参考"
    elif result.decision == DECISION_AUTO_REJECTED:
        resource.system_status = resource.system_status or "已拒绝"
    elif result.decision == DECISION_AUTO_MERGED:
        resource.system_status = resource.system_status or "待合并"
    elif result.decision == DECISION_NEED_REVIEW:
        resource.system_status = resource.system_status or "待复核"


def _persist_decision(
    db: Session,
    *,
    run_id: int | None,
    resource: models.StandardResource,
    result: GovernanceDecisionResult,
    dry_run: bool,
) -> models.GovernanceDecision | None:
    if dry_run:
        return None
    row = models.GovernanceDecision(
        run_id=run_id,
        target_type="standard_resource",
        target_id=resource.id,
        decision=result.decision,
        reason=result.decision_reason,
        decision_reason=result.decision_reason,
        confidence_score=result.confidence_score,
        evidence_count=result.evidence_count,
        highest_source_level=result.highest_source_level,
        highest_source_weight=result.highest_source_weight,
        conflict_count=result.conflict_count,
        risk_level=result.risk_level,
        decided_by=SYSTEM_DECIDER,
        decided_at=datetime.now(UTC),
        metadata_json=json.dumps(result.to_dict(), ensure_ascii=False),
    )
    db.add(row)
    return row


def _resource_query(
    db: Session,
    *,
    source_id: int | None,
    only_unprocessed: bool,
):
    query = select(models.StandardResource).order_by(models.StandardResource.id.asc())
    if source_id is not None:
        query = query.where(models.StandardResource.source_id == source_id)
    if only_unprocessed:
        query = query.where(models.StandardResource.auto_decision.is_(None))
    return query


def run_governance_decisions(
    db: Session,
    *,
    limit: int = 1000,
    source_id: int | None = None,
    only_unprocessed: bool = True,
    dry_run: bool = False,
) -> dict:
    limit = max(1, min(limit, 10000))
    resources = list(db.scalars(_resource_query(db, source_id=source_id, only_unprocessed=only_unprocessed).limit(limit)).all())

    run = models.SourceGovernanceRun(
        run_type="run_decisions",
        status="running",
        total=len(resources),
        config_json=json.dumps(
            {
                "limit": limit,
                "source_id": source_id,
                "only_unprocessed": only_unprocessed,
                "dry_run": dry_run,
            },
            ensure_ascii=False,
        ),
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()

    stats = {
        "processed": 0,
        "auto_confirmed": 0,
        "auto_merged": 0,
        "auto_downgraded": 0,
        "auto_rejected": 0,
        "need_review": 0,
        "high_risk_count": 0,
        "conflict_count": 0,
        "dry_run": dry_run,
        "run_id": run.id,
    }

    for resource in resources:
        run.processed += 1
        stats["processed"] += 1
        try:
            bundle = build_evidence_bundle(db, resource)
            result = make_governance_decision(bundle)
            stats["conflict_count"] += result.conflict_count
            if result.risk_level == RISK_HIGH:
                stats["high_risk_count"] += 1

            decision_key = result.decision.lower()
            if decision_key == "auto_confirmed":
                stats["auto_confirmed"] += 1
            elif decision_key == "auto_merged":
                stats["auto_merged"] += 1
            elif decision_key == "auto_downgraded":
                stats["auto_downgraded"] += 1
            elif decision_key == "auto_rejected":
                stats["auto_rejected"] += 1
            elif decision_key == "need_review":
                stats["need_review"] += 1

            if not dry_run:
                _apply_decision_to_resource(resource, result)
                _persist_decision(db, run_id=run.id, resource=resource, result=result, dry_run=False)
                if result.should_alert and result.dedupe_key and result.alert_message:
                    document_id = bundle.documents[0].id if bundle.documents else None
                    upsert_pending_alert(
                        db,
                        alert_type=result.alert_type or "治理异常",
                        message=f"{resource.standard_no or '-'} {resource.standard_name}：{result.alert_message}",
                        alert_level=models.AlertLevel.high.value,
                        risk_level=result.risk_level,
                        dedupe_key=result.dedupe_key,
                        document_id=document_id,
                    )

            log_governance_decision_audit(
                db,
                step_name="make_governance_decision",
                target_type="standard_resource",
                target_id=resource.id,
                source_id=resource.source_id,
                result=result.decision,
                confidence_score=result.confidence_score,
                input_summary=json.dumps(bundle.to_summary(), ensure_ascii=False),
                output_summary=json.dumps(result.to_dict(), ensure_ascii=False),
            )
            run.success += 1
        except Exception as exc:
            run.failed += 1
            log_governance_decision_audit(
                db,
                step_name="make_governance_decision",
                target_type="standard_resource",
                target_id=resource.id,
                source_id=resource.source_id,
                result="ERROR",
                status="failed",
                error_message=str(exc),
            )

    run.status = "finished"
    run.finished_at = datetime.now(UTC)
    run.message = json.dumps(stats, ensure_ascii=False)
    log_governance_decision_audit(
        db,
        step_name="run_decisions_batch",
        target_type="governance_run",
        target_id=run.id,
        source_id=source_id,
        result="finished",
        output_summary=json.dumps(stats, ensure_ascii=False),
    )

    if dry_run:
        db.rollback()
        stats["run_id"] = None
    else:
        db.commit()

    return stats


def list_governance_exceptions(
    db: Session,
    *,
    cursor: int | None = None,
    page_size: int = 50,
    q: str | None = None,
    risk_level: str | None = None,
) -> dict:
    page_size = max(1, min(page_size, 200))
    query = (
        select(models.GovernanceDecision, models.StandardResource)
        .join(models.StandardResource, models.StandardResource.id == models.GovernanceDecision.target_id)
        .where(
            models.GovernanceDecision.target_type == "standard_resource",
            or_(
                models.GovernanceDecision.decision == DECISION_NEED_REVIEW,
                models.GovernanceDecision.risk_level == RISK_HIGH,
            ),
        )
        .order_by(models.GovernanceDecision.id.desc())
    )
    if cursor:
        query = query.where(models.GovernanceDecision.id < cursor)
    if risk_level:
        query = query.where(models.GovernanceDecision.risk_level == risk_level)
    if q:
        keyword = f"%{q.strip()}%"
        query = query.where(
            or_(
                models.StandardResource.standard_no.like(keyword),
                models.StandardResource.standard_name.like(keyword),
                models.GovernanceDecision.decision_reason.like(keyword),
            )
        )

    rows = db.execute(query.limit(page_size + 1)).all()
    has_more = len(rows) > page_size
    rows = rows[:page_size]

    total = db.scalar(
        select(func.count())
        .select_from(models.GovernanceDecision)
        .where(
            models.GovernanceDecision.target_type == "standard_resource",
            or_(
                models.GovernanceDecision.decision == DECISION_NEED_REVIEW,
                models.GovernanceDecision.risk_level == RISK_HIGH,
            ),
        )
    ) or 0

    items = []
    for decision, resource in rows:
        metadata = {}
        if decision.metadata_json:
            try:
                metadata = json.loads(decision.metadata_json)
            except json.JSONDecodeError:
                metadata = {}
        conflicts = metadata.get("conflicts") or []
        conflict_sources = sorted(
            {
                source
                for conflict in conflicts
                for source in (conflict.get("sources") or [])
            }
        )
        alert = db.scalars(
            select(models.Alert)
            .where(
                models.Alert.status == models.AlertStatus.pending.value,
                models.Alert.message.like(f"%{resource.standard_name[:40]}%"),
            )
            .order_by(models.Alert.id.desc())
            .limit(1)
        ).first()
        items.append(
            {
                "decision_id": decision.id,
                "resource_id": resource.id,
                "standard_no": resource.standard_no,
                "standard_name": resource.standard_name,
                "exception_type": conflicts[0]["conflict_type"] if conflicts else decision.decision,
                "risk_level": decision.risk_level or resource.risk_level,
                "highest_source_level": decision.highest_source_level,
                "highest_source_weight": decision.highest_source_weight,
                "conflict_sources": conflict_sources,
                "system_suggestion": decision.decision_reason or decision.reason,
                "handle_status": alert.status if alert else ("未处理" if decision.decision == DECISION_NEED_REVIEW else "已决策"),
                "confidence_score": decision.confidence_score,
                "conflict_count": decision.conflict_count or 0,
                "decided_at": decision.decided_at,
            }
        )

    next_cursor = rows[-1][0].id if has_more and rows else None
    return {
        "total": total,
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def governance_supervision_summary(db: Session) -> dict:
    return {
        "pending_exceptions": db.scalar(
            select(func.count())
            .select_from(models.GovernanceDecision)
            .where(
                models.GovernanceDecision.decision == DECISION_NEED_REVIEW,
                models.GovernanceDecision.target_type == "standard_resource",
            )
        )
        or 0,
        "high_risk_exceptions": db.scalar(
            select(func.count())
            .select_from(models.GovernanceDecision)
            .where(
                models.GovernanceDecision.risk_level == RISK_HIGH,
                models.GovernanceDecision.target_type == "standard_resource",
            )
        )
        or 0,
        "auto_confirmed": db.scalar(
            select(func.count())
            .select_from(models.StandardResource)
            .where(models.StandardResource.auto_decision == DECISION_AUTO_CONFIRMED)
        )
        or 0,
        "auto_merged": db.scalar(
            select(func.count())
            .select_from(models.StandardResource)
            .where(models.StandardResource.auto_decision == DECISION_AUTO_MERGED)
        )
        or 0,
        "auto_downgraded": db.scalar(
            select(func.count())
            .select_from(models.StandardResource)
            .where(models.StandardResource.auto_decision == DECISION_AUTO_DOWNGRADED)
        )
        or 0,
        "pending_alerts": db.scalar(
            select(func.count())
            .select_from(models.Alert)
            .where(models.Alert.status == models.AlertStatus.pending.value)
        )
        or 0,
        "recent_runs": [
            {
                "id": item.id,
                "run_type": item.run_type,
                "status": item.status,
                "total": item.total,
                "success": item.success,
                "failed": item.failed,
                "message": item.message,
                "finished_at": item.finished_at,
            }
            for item in db.scalars(
                select(models.SourceGovernanceRun)
                .where(models.SourceGovernanceRun.run_type == "run_decisions")
                .order_by(models.SourceGovernanceRun.id.desc())
                .limit(5)
            ).all()
        ],
    }
