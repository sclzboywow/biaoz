"""自动治理决策引擎：证据汇总、冲突检测、置信度评分与决策输出。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import models
from app.standard_number import normalize_standard_no

DECISION_AUTO_CONFIRMED = "AUTO_CONFIRMED"
DECISION_AUTO_MERGED = "AUTO_MERGED"
DECISION_AUTO_DOWNGRADED = "AUTO_DOWNGRADED"
DECISION_AUTO_REJECTED = "AUTO_REJECTED"
DECISION_NEED_REVIEW = "NEED_REVIEW"

RISK_HIGH = "high"
RISK_MEDIUM = "medium"
RISK_LOW = "low"

LEVEL_RANK = {"A+": 4, "A": 3, "B": 2, "C": 1}
HIGH_TRUST_LEVELS = {"A", "A+"}
CLEAR_STATUSES = {"现行", "废止", "被替代", "即将实施"}
LOCAL_ACTIVE_STATUSES = {"现行", "来源确认现行", "待复核", "待确认"}
LOCAL_ABOLISHED_STATUSES = {"废止", "来源确认废止", "已废止", "确认废止"}


@dataclass
class ConflictItem:
    conflict_type: str
    severity: str
    message: str
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvidenceBundle:
    resource: models.StandardResource
    trusted_source: models.TrustedSource | None
    evidence_rows: list[models.StandardEvidence]
    file_matches: list[models.StandardFileMatch]
    documents: list[models.Document]
    document_versions: list[models.DocumentVersion]
    url_sources: list[models.UrlSource]
    relations: list[models.StandardRelation]
    duplicate_resources: list[models.StandardResource]
    conflicts: list[ConflictItem] = field(default_factory=list)
    name_similarity: int = 0
    highest_source_level: str | None = None
    highest_source_weight: int = 0

    def to_summary(self) -> dict:
        return {
            "resource_id": self.resource.id,
            "standard_no": self.resource.standard_no,
            "standard_name": self.resource.standard_name,
            "source_status": self.resource.source_status,
            "evidence_count": len(self.evidence_rows),
            "match_count": len(self.file_matches),
            "document_count": len(self.documents),
            "duplicate_count": len(self.duplicate_resources),
            "conflict_count": len(self.conflicts),
            "name_similarity": self.name_similarity,
            "highest_source_level": self.highest_source_level,
            "highest_source_weight": self.highest_source_weight,
        }


@dataclass
class GovernanceDecisionResult:
    decision: str
    confidence_score: int
    decision_reason: str
    evidence_count: int
    highest_source_level: str | None
    highest_source_weight: int
    conflict_count: int
    risk_level: str
    conflicts: list[ConflictItem] = field(default_factory=list)
    should_alert: bool = False
    alert_type: str | None = None
    alert_message: str | None = None
    dedupe_key: str | None = None

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["conflicts"] = [item.to_dict() for item in self.conflicts]
        return payload


def _similarity(left: str | None, right: str | None) -> int:
    return int(SequenceMatcher(None, (left or "").strip(), (right or "").strip()).ratio() * 100)


def _resource_number(resource: models.StandardResource) -> str | None:
    if resource.normalized_standard_no:
        return resource.normalized_standard_no
    if resource.standard_no:
        return normalize_standard_no(resource.standard_no).normalized
    return None


def _source_level(source: models.TrustedSource | None, evidence: models.StandardEvidence | None = None) -> str:
    if evidence and evidence.source_level:
        return evidence.source_level.strip().upper()
    if source and source.trust_level:
        return source.trust_level.strip().upper()
    return "B"


def _source_weight(source: models.TrustedSource | None) -> int:
    if source is None:
        return 30
    return source.status_authority_weight or source.trust_score or 30


def _is_pdf_valid(version: models.DocumentVersion | None, url_source: models.UrlSource | None) -> bool:
    if version is None:
        return True
    name = (version.file_name or "").lower()
    if not name.endswith(".pdf"):
        return False
    if url_source and url_source.file_ext and url_source.file_ext.lower() not in {"pdf", ""}:
        if url_source.file_ext.lower() not in {"pdf"}:
            return False
    return True


def build_evidence_bundle(db: Session, target: models.StandardResource) -> EvidenceBundle:
    trusted_source = db.get(models.TrustedSource, target.source_id)
    evidence_rows = list(
        db.scalars(
            select(models.StandardEvidence)
            .where(models.StandardEvidence.standard_resource_id == target.id)
            .order_by(models.StandardEvidence.captured_at.desc())
        ).all()
    )
    file_matches = list(
        db.scalars(
            select(models.StandardFileMatch).where(models.StandardFileMatch.standard_resource_id == target.id)
        ).all()
    )
    document_ids = {match.document_id for match in file_matches}
    documents = list(db.scalars(select(models.Document).where(models.Document.id.in_(document_ids))).all()) if document_ids else []
    version_ids = {match.document_version_id for match in file_matches if match.document_version_id}
    document_versions = (
        list(db.scalars(select(models.DocumentVersion).where(models.DocumentVersion.id.in_(version_ids))).all())
        if version_ids
        else []
    )
    url_source_ids = {version.url_source_id for version in document_versions if version.url_source_id}
    url_sources = (
        list(db.scalars(select(models.UrlSource).where(models.UrlSource.id.in_(url_source_ids))).all())
        if url_source_ids
        else []
    )
    relations = list(
        db.scalars(
            select(models.StandardRelation).where(
                or_(
                    models.StandardRelation.current_standard_resource_id == target.id,
                    models.StandardRelation.related_standard_resource_id == target.id,
                )
            )
        ).all()
    )

    resource_no = _resource_number(target)
    duplicate_resources: list[models.StandardResource] = []
    if resource_no:
        duplicate_resources = list(
            db.scalars(
                select(models.StandardResource).where(
                    models.StandardResource.id != target.id,
                    or_(
                        models.StandardResource.normalized_standard_no == resource_no,
                        models.StandardResource.standard_no == target.standard_no,
                    ),
                )
            ).all()
        )

    bundle = EvidenceBundle(
        resource=target,
        trusted_source=trusted_source,
        evidence_rows=evidence_rows,
        file_matches=file_matches,
        documents=documents,
        document_versions=document_versions,
        url_sources=url_sources,
        relations=relations,
        duplicate_resources=duplicate_resources,
    )

    if documents:
        bundle.name_similarity = max(_similarity(document.title, target.standard_name) for document in documents)
    else:
        bundle.name_similarity = 100 if target.standard_name else 0

    bundle.highest_source_level = _source_level(trusted_source)
    bundle.highest_source_weight = _source_weight(trusted_source)
    for evidence in evidence_rows:
        level = _source_level(trusted_source, evidence)
        if LEVEL_RANK.get(level, 0) > LEVEL_RANK.get(bundle.highest_source_level or "B", 0):
            bundle.highest_source_level = level

    return bundle


def detect_conflicts(bundle: EvidenceBundle) -> list[ConflictItem]:
    conflicts: list[ConflictItem] = []
    resource = bundle.resource

    status_by_level: dict[str, set[str]] = {}
    for evidence in bundle.evidence_rows:
        level = _source_level(bundle.trusted_source, evidence)
        status = (evidence.raw_status_text or evidence.parsed_status or "").strip()
        if status:
            status_by_level.setdefault(level, set()).add(status)

    a_plus_statuses = status_by_level.get("A+", set())
    if len(a_plus_statuses) > 1:
        conflicts.append(
            ConflictItem(
                conflict_type="a_plus_status_conflict",
                severity=RISK_HIGH,
                message=f"A+ 来源状态冲突：{', '.join(sorted(a_plus_statuses))}",
                sources=["A+"],
            )
        )

    high_statuses = set()
    for level in HIGH_TRUST_LEVELS:
        high_statuses.update(status_by_level.get(level, set()))
    if resource.source_status:
        high_statuses.add(resource.source_status.strip())

    for document in bundle.documents:
        local_status = document.system_status or document.valid_status or document.manual_status
        source_status = resource.source_status or "未知"
        if source_status in {"废止", "被替代"} and local_status in LOCAL_ACTIVE_STATUSES:
            conflicts.append(
                ConflictItem(
                    conflict_type="authority_abolished_local_active",
                    severity=RISK_HIGH,
                    message=f"权威来源显示 {source_status}，本地仍为 {local_status}",
                    sources=[bundle.trusted_source.source_name if bundle.trusted_source else "可信源"],
                )
            )
        if len(high_statuses) > 1 and local_status and local_status not in high_statuses:
            conflicts.append(
                ConflictItem(
                    conflict_type="authority_local_status_conflict",
                    severity=RISK_MEDIUM,
                    message=f"高权重来源状态 {', '.join(sorted(high_statuses))} 与本地 {local_status} 不一致",
                    sources=[bundle.trusted_source.source_name if bundle.trusted_source else "可信源"],
                )
            )

    if bundle.name_similarity and bundle.name_similarity < 60 and _resource_number(resource):
        conflicts.append(
            ConflictItem(
                conflict_type="number_match_low_name_similarity",
                severity=RISK_HIGH,
                message=f"编号一致但名称相似度仅 {bundle.name_similarity}%",
            )
        )

    unclear_relations = [
        relation
        for relation in bundle.relations
        if (relation.relation_type or "").strip() in {"", "相关", "未知"} and not relation.is_manual_confirmed
    ]
    if unclear_relations:
        conflicts.append(
            ConflictItem(
                conflict_type="unclear_replacement_relation",
                severity=RISK_MEDIUM,
                message=f"存在 {len(unclear_relations)} 条未确认的替代/相关关系",
            )
        )

    for document in bundle.documents:
        versions = [version for version in bundle.document_versions if version.document_id == document.id]
        if len(versions) >= 2:
            hashes = {version.file_hash for version in versions}
            if len(hashes) > 1 and document.title == resource.standard_name:
                conflicts.append(
                    ConflictItem(
                        conflict_type="hash_changed_metadata_unchanged",
                        severity=RISK_HIGH,
                        message=f"文件 hash 变化但元数据未更新：document_id={document.id}",
                    )
                )

    for version in bundle.document_versions:
        url_source = next((item for item in bundle.url_sources if item.id == version.url_source_id), None)
        if not _is_pdf_valid(version, url_source):
            conflicts.append(
                ConflictItem(
                    conflict_type="pdf_validation_failed",
                    severity=RISK_HIGH,
                    message=f"PDF 校验异常：{version.file_name}",
                )
            )

    ocr_failures = [
        source
        for source in bundle.url_sources
        if source.governance_status == "需 OCR" or (source.error_message and "OCR" in source.error_message.upper())
    ]
    if len(ocr_failures) >= 2:
        conflicts.append(
            ConflictItem(
                conflict_type="ocr_consecutive_failure",
                severity=RISK_HIGH,
                message=f"OCR 连续失败 {len(ocr_failures)} 次",
            )
        )

    high_value_failures = [
        source
        for source in bundle.url_sources
        if source.status in {"失效", "异常"}
        and (source.is_official_domain or (source.source_quality_score or 0) >= 70)
    ]
    if len(high_value_failures) >= 2:
        conflicts.append(
            ConflictItem(
                conflict_type="high_value_source_fetch_failure",
                severity=RISK_HIGH,
                message=f"高价值来源连续抓取失败 {len(high_value_failures)} 次",
            )
        )

    bundle.conflicts = conflicts
    return conflicts


def calculate_confidence_score(bundle: EvidenceBundle) -> int:
    resource = bundle.resource
    score = 20

    level = bundle.highest_source_level or "B"
    score += LEVEL_RANK.get(level, 1) * 8
    score += min(20, bundle.highest_source_weight // 5)

    resource_no = _resource_number(resource)
    if resource_no:
        score += 10
        if all(_resource_number(item) == resource_no for item in bundle.duplicate_resources):
            score += 5

    if bundle.name_similarity >= 80:
        score += 18
    elif bundle.name_similarity >= 60:
        score += 8
    elif bundle.documents:
        score -= 12

    status = (resource.source_status or "").strip()
    if status in CLEAR_STATUSES:
        score += 12
    else:
        score -= 8

    if bundle.file_matches:
        score += min(15, len(bundle.file_matches) * 5)
        if all(match.status in {"自动确认", "已确认"} for match in bundle.file_matches):
            score += 8

    if bundle.evidence_rows:
        score += min(10, len(bundle.evidence_rows) * 2)

    score -= min(40, len(bundle.conflicts) * 10)

    if resource.source_confidence:
        score += min(10, resource.source_confidence // 10)

    return max(0, min(100, score))


def make_governance_decision(bundle: EvidenceBundle) -> GovernanceDecisionResult:
    if not bundle.conflicts:
        detect_conflicts(bundle)

    confidence = calculate_confidence_score(bundle)
    resource = bundle.resource
    resource_no = _resource_number(resource)
    status = (resource.source_status or "").strip()
    level = (bundle.highest_source_level or "B").upper()
    conflicts = bundle.conflicts
    high_conflicts = [item for item in conflicts if item.severity == RISK_HIGH]
    risk_level = RISK_LOW
    if high_conflicts:
        risk_level = RISK_HIGH
    elif conflicts:
        risk_level = RISK_MEDIUM

    need_review_types = {
        "a_plus_status_conflict",
        "authority_abolished_local_active",
        "number_match_low_name_similarity",
        "unclear_replacement_relation",
        "hash_changed_metadata_unchanged",
        "ocr_consecutive_failure",
        "pdf_validation_failed",
        "high_value_source_fetch_failure",
    }
    triggered_review = [item for item in conflicts if item.conflict_type in need_review_types]

    if not resource_no and not resource.standard_name:
        return GovernanceDecisionResult(
            decision=DECISION_AUTO_REJECTED,
            confidence_score=confidence,
            decision_reason="缺少标准编号与名称，无法治理",
            evidence_count=len(bundle.evidence_rows),
            highest_source_level=level,
            highest_source_weight=bundle.highest_source_weight,
            conflict_count=len(conflicts),
            risk_level=RISK_HIGH,
            conflicts=conflicts,
        )

    if triggered_review:
        primary = triggered_review[0]
        return GovernanceDecisionResult(
            decision=DECISION_NEED_REVIEW,
            confidence_score=confidence,
            decision_reason=primary.message,
            evidence_count=len(bundle.evidence_rows),
            highest_source_level=level,
            highest_source_weight=bundle.highest_source_weight,
            conflict_count=len(conflicts),
            risk_level=risk_level,
            conflicts=conflicts,
            should_alert=risk_level == RISK_HIGH,
            alert_type=primary.conflict_type,
            alert_message=primary.message,
            dedupe_key=f"governance:{resource.id}:{primary.conflict_type}",
        )

    auto_confirm = (
        level in HIGH_TRUST_LEVELS
        and bool(resource_no)
        and bundle.name_similarity >= 80
        and status in CLEAR_STATUSES
        and confidence >= 85
        and not conflicts
        and all(_is_pdf_valid(version, next((s for s in bundle.url_sources if s.id == version.url_source_id), None)) for version in bundle.document_versions)
    )
    if auto_confirm:
        return GovernanceDecisionResult(
            decision=DECISION_AUTO_CONFIRMED,
            confidence_score=confidence,
            decision_reason="高置信度来源，编号/名称/状态一致且无冲突",
            evidence_count=len(bundle.evidence_rows),
            highest_source_level=level,
            highest_source_weight=bundle.highest_source_weight,
            conflict_count=0,
            risk_level=RISK_LOW,
            conflicts=conflicts,
        )

    if len(bundle.duplicate_resources) >= 1 and bundle.name_similarity >= 80 and confidence >= 70:
        return GovernanceDecisionResult(
            decision=DECISION_AUTO_MERGED,
            confidence_score=confidence,
            decision_reason=f"检测到 {len(bundle.duplicate_resources) + 1} 条同编号记录，建议自动合并",
            evidence_count=len(bundle.evidence_rows),
            highest_source_level=level,
            highest_source_weight=bundle.highest_source_weight,
            conflict_count=len(conflicts),
            risk_level=RISK_LOW,
            conflicts=conflicts,
        )

    if level in {"B", "C"} or confidence < 40 or (resource.source_confidence or 100) < 50:
        return GovernanceDecisionResult(
            decision=DECISION_AUTO_DOWNGRADED,
            confidence_score=confidence,
            decision_reason="来源权重或置信度偏低，降级为线索/低优先级",
            evidence_count=len(bundle.evidence_rows),
            highest_source_level=level,
            highest_source_weight=bundle.highest_source_weight,
            conflict_count=len(conflicts),
            risk_level=RISK_LOW,
            conflicts=conflicts,
        )

    if confidence < 15:
        return GovernanceDecisionResult(
            decision=DECISION_AUTO_REJECTED,
            confidence_score=confidence,
            decision_reason="置信度过低，自动拒绝",
            evidence_count=len(bundle.evidence_rows),
            highest_source_level=level,
            highest_source_weight=bundle.highest_source_weight,
            conflict_count=len(conflicts),
            risk_level=RISK_MEDIUM,
            conflicts=conflicts,
        )

    return GovernanceDecisionResult(
        decision=DECISION_NEED_REVIEW,
        confidence_score=confidence,
        decision_reason="未达到自动确认阈值，需人工复核",
        evidence_count=len(bundle.evidence_rows),
        highest_source_level=level,
        highest_source_weight=bundle.highest_source_weight,
        conflict_count=len(conflicts),
        risk_level=RISK_MEDIUM,
        conflicts=conflicts,
        should_alert=False,
    )
