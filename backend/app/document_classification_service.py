"""Unified document file classification: confidence scoring and auto-decisions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app import models
from app.classification_decisions import (
    DECISION_AUTO_CLASSIFY,
    DECISION_AUTO_CONFIRM,
    DECISION_CONFLICT_BLOCK,
    DECISION_DUPLICATE_EXISTING,
    DECISION_LINK_EXISTING,
    DECISION_MANUAL_REVIEW,
    DECISION_NEW_VERSION,
    DECISION_QUARANTINE,
    FORMAL_INGEST_DECISIONS,
    ISOLATED_INGEST_DECISIONS,
    LEGACY_INTAKE_DECISION_MAP,
)
from app.intake_search_slices import NOISE_TOKENS, build_intake_search_queries, collect_intake_match_numbers
from app.settings_store import get_bool_setting, get_classification_thresholds, get_int_setting
from app.standard_number import (
    StandardNumberParts,
    canonicalize_standard_no_text,
    extract_all_codes_from_text,
    extract_standard_no_from_text,
    normalize_atlas_code,
    normalize_standard_no,
    standard_no_token_match,
)
from app.storage import safe_stem, safe_suffix, safe_upload_filename
from app.trusted_source_search_service import search_trusted_sources_sliced

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

HIGH_TRUST_LEVELS = {"A", "A+"}

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "工程建设": [
        "建筑",
        "工程",
        "施工",
        "验收",
        "设计",
        "结构",
        "混凝土",
        "钢结构",
        "地基",
        "基坑",
        "城市道路",
        "给水",
        "排水",
        "暖通",
        "电气",
    ],
    "消防安全": ["消防", "防火", "灭火", "火灾", "喷淋", "自动报警", "疏散"],
    "医药卫生": ["医疗", "医药", "药品", "药物", "医院", "卫生", "核医学", "放射", "医疗器械", "GMP", "药典"],
    "生态环保": ["环境", "环保", "污染", "排放", "水质", "大气", "噪声", "固废"],
    "信息技术": ["信息", "数据", "网络", "安全", "密码", "软件", "系统", "接口"],
    "计量检测": ["计量", "校准", "检测", "试验", "检验", "测量"],
    "安全生产": ["安全生产", "危险化学品", "应急", "矿山", "职业健康"],
}


@dataclass
class ClassificationCandidate:
    candidate_type: str
    candidate_id: int | None = None
    source_id: int | None = None
    source_name: str | None = None
    standard_no: str | None = None
    normalized_standard_no: str | None = None
    standard_name: str | None = None
    source_status: str | None = None
    source_category_path: str | None = None
    publish_date: date | None = None
    effective_date: date | None = None
    abolish_date: date | None = None
    detail_url: str | None = None
    official_file_url: str | None = None
    title_similarity: int = 0
    match_score: int = 0
    match_reason: str | None = None


@dataclass
class DocumentClassificationResult:
    title: str
    original_file_name: str | None = None
    standard_no: str | None = None
    raw_standard_no: str | None = None
    normalized_standard_no: str | None = None
    standard_prefix: str | None = None
    standard_main_no: str | None = None
    standard_year: str | None = None
    standard_revision_note: str | None = None
    standard_level: str | None = None
    category: str | None = None
    category_id: int | None = None
    source_status: str | None = None
    system_status: str | None = None
    valid_status: str | None = None
    review_status: str | None = None
    metadata_status: str | None = None
    confidence_score: int = 0
    risk_level: str = RISK_MEDIUM
    decision: str = DECISION_QUARANTINE
    decision_reason: str = ""
    matched_resource_id: int | None = None
    matched_document_id: int | None = None
    matched_version_id: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    candidates: list[ClassificationCandidate] = field(default_factory=list)


def _similarity(left: str | None, right: str | None) -> int:
    return int(SequenceMatcher(None, (left or "").strip(), (right or "").strip()).ratio() * 100)


def clean_file_title(file_name: str) -> tuple[str, str, str]:
    safe_name = safe_upload_filename(file_name)
    stem = safe_stem(safe_name)
    suffix = safe_suffix(safe_name)
    title = stem
    for token in NOISE_TOKENS:
        title = re.sub(rf"(?i)\b{re.escape(token)}\b", " ", title)
    title = re.sub(r"[\s_\-－—]+", " ", title).strip()
    return safe_name, stem, title or stem


def infer_standard_level(standard_no: str | None, standard_prefix: str | None) -> str:
    prefix = (standard_prefix or standard_no or "").upper().strip()
    if not prefix:
        return "未识别"
    if re.match(r"^(GB|GB/T|GB/Z)(\s|$|/)", prefix, re.I):
        return "国家标准"
    if re.match(r"^DB\d{2}(/T)?", prefix, re.I):
        return "地方标准"
    if re.match(r"^T/", prefix, re.I):
        return "团体标准"
    if re.match(r"^Q/", prefix, re.I):
        return "企业标准"
    if re.match(r"^(ISO|IEC|EN|DIN|ASTM|JIS|ANSI|API|ASME)(\s|$|/)", prefix, re.I):
        return "国际/国外标准"
    if re.match(r"^[A-Z]{2,8}(/T)?$", prefix):
        return "行业标准"
    atlas_text = (standard_no or prefix or "").upper().strip()
    if re.match(r"^\d{2}[A-Z]", atlas_text) or re.match(r"^\d{2}[CS][A-Z]", atlas_text, re.I):
        return "标准图集"
    return "未识别"


def map_source_status(source_status: str | None) -> tuple[str, str, str]:
    """Return (source_status, system_status, valid_status)."""
    status = (source_status or "").strip()
    if status == "现行":
        return status, "来源确认现行", "来源确认现行"
    if status == "废止":
        return status, "来源确认废止", "来源确认废止"
    if status == "被替代":
        return status, "疑似被替代", "疑似被替代"
    if status == "即将实施":
        return status, "待生效", "待生效"
    if status:
        mapped = {
            "现行": ("来源确认现行", "来源确认现行"),
            "废止": ("来源确认废止", "来源确认废止"),
            "被替代": ("疑似被替代", "疑似被替代"),
        }.get(status)
        if mapped:
            return status, mapped[0], mapped[1]
    return status or None, "系统推定未知", "系统推定未知"


def apply_decision_status_fields(decision: str) -> tuple[str, str, str | None]:
    """Return (review_status, metadata_status, valid_status override or None)."""
    mapping = {
        DECISION_DUPLICATE_EXISTING: ("自动确认", "系统自动确认", None),
        DECISION_AUTO_CONFIRM: ("自动确认", "系统自动确认", None),
        DECISION_AUTO_CLASSIFY: ("自动分类", "系统自动分类", None),
        DECISION_LINK_EXISTING: ("自动分类", "系统自动关联", None),
        DECISION_NEW_VERSION: ("自动分类", "系统识别新版本", None),
        DECISION_QUARANTINE: ("风险隔离", "系统隔离", "隔离留存"),
        DECISION_CONFLICT_BLOCK: ("冲突拦截", "系统冲突拦截", "冲突拦截"),
    }
    return mapping.get(decision, ("待复核", "系统识别", None))


def apply_decision_thresholds(
    score: int,
    *,
    has_conflict: bool,
    is_duplicate: bool,
    confirm_threshold: int = 90,
    classify_threshold: int = 70,
    quarantine_threshold: int = 40,
) -> tuple[str, str]:
    if is_duplicate:
        return DECISION_DUPLICATE_EXISTING, RISK_LOW
    if has_conflict:
        return DECISION_CONFLICT_BLOCK, RISK_HIGH
    if score >= confirm_threshold:
        return DECISION_AUTO_CONFIRM, RISK_LOW
    if score >= classify_threshold:
        return DECISION_AUTO_CLASSIFY, RISK_MEDIUM
    if score >= quarantine_threshold:
        return DECISION_QUARANTINE, RISK_MEDIUM
    return DECISION_CONFLICT_BLOCK, RISK_HIGH


def is_auto_classification_enabled(db: Session) -> bool:
    return get_bool_setting(db, "auto_classification_enabled", default=True)


def is_isolated_classification_decision(decision: str | None) -> bool:
    return decision in ISOLATED_INGEST_DECISIONS


def can_link_classification_to_existing_document(result: DocumentClassificationResult) -> bool:
    if is_isolated_classification_decision(result.decision):
        return False
    if result.decision == DECISION_MANUAL_REVIEW:
        return False
    if result.decision in FORMAL_INGEST_DECISIONS and result.matched_document_id:
        return True
    return False


def apply_manual_review_classification(result: DocumentClassificationResult) -> None:
    result.decision = DECISION_MANUAL_REVIEW
    result.confidence_score = 0
    result.risk_level = RISK_MEDIUM
    result.decision_reason = "自动分类已关闭，待人工复核"
    result.review_status = models.ReviewStatus.pending.value
    result.valid_status = models.ValidStatus.pending.value
    result.metadata_status = None
    result.classification_decision = None
    result.classification_confidence_score = None
    result.classification_risk_level = None
    result.classification_reason = None
    result.matched_document_id = None


def apply_fields_to_document(document: models.Document, fields: dict[str, Any]) -> None:
    for key, value in fields.items():
        if value is not None:
            setattr(document, key, value)


def infer_category_from_keywords(title: str | None) -> str | None:
    if not title:
        return None
    text = title.lower()
    best_category: str | None = None
    best_hits = 0
    for category, keywords in CATEGORY_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in text)
        if hits > best_hits:
            best_hits = hits
            best_category = category
    return best_category if best_hits > 0 else None


def resolve_category(
    db: Session,
    *,
    resource_category_path: str | None,
    source_category: str | None,
    source_category_id: int | None,
    title: str | None,
) -> tuple[str | None, int | None]:
    if resource_category_path:
        parts = [p.strip() for p in resource_category_path.replace("\\", "/").split("/") if p.strip()]
        if parts:
            name = parts[-1]
            cat = db.scalars(select(models.Category).where(models.Category.category_name == name).limit(1)).first()
            return name, cat.id if cat else None
    if source_category:
        cat = db.scalars(select(models.Category).where(models.Category.category_name == source_category).limit(1)).first()
        return source_category, source_category_id or (cat.id if cat else None)
    keyword_cat = infer_category_from_keywords(title)
    if keyword_cat:
        cat = db.scalars(select(models.Category).where(models.Category.category_name == keyword_cat).limit(1)).first()
        return keyword_cat, cat.id if cat else None
    return "未分类", None


def _extract_metadata_from_texts(*texts: str | None) -> tuple[str | None, list[str], str | None]:
    combined = canonicalize_standard_no_text("\n".join(t for t in texts if t))
    primary = extract_standard_no_from_text(combined)
    all_codes = extract_all_codes_from_text(combined)
    normalized_codes: list[str] = []
    seen: set[str] = set()
    for code in all_codes:
        norm = normalize_standard_no(code).normalized or normalize_atlas_code(code) or code
        key = (norm or code).upper()
        if key not in seen:
            seen.add(key)
            normalized_codes.append(norm or code)
    title_source = combined
    for code in all_codes:
        title_source = re.sub(re.escape(code), " ", title_source, flags=re.I)
    title_source = re.sub(r"[\s_\-－—]+", " ", title_source).strip()
    return primary, normalized_codes, title_source or None


def _score_extracted_metadata(
    result: DocumentClassificationResult,
    *,
    title: str | None,
    all_codes: list[str],
) -> int:
    score = 0
    parts = normalize_standard_no(result.standard_no)
    main_no = (parts.main_no or "").lstrip("_-")
    if parts.normalized and main_no:
        score += 40
    elif parts.normalized or result.standard_no:
        score += 25
    if result.standard_prefix and result.standard_level not in {None, "未识别"}:
        score += 10
    if parts.year:
        score += 5
    if infer_category_from_keywords(title):
        score += 10
    if len(all_codes) == 1:
        score += 5
    return score


def _detect_multi_standard_conflict(codes: list[str]) -> bool:
    if len(codes) <= 1:
        return False
    prefixes: set[str] = set()
    for code in codes:
        parts = normalize_standard_no(code)
        prefix = (parts.prefix or code.split()[0] if code else "").upper()
        main = parts.main_no or ""
        prefixes.add(f"{prefix}:{main}")
    return len(prefixes) > 1


def match_existing_versions_by_hash(db: Session, file_hash: str | None) -> list[ClassificationCandidate]:
    if not file_hash:
        return []
    candidates: list[ClassificationCandidate] = []
    for version in db.scalars(
        select(models.DocumentVersion)
        .where(models.DocumentVersion.file_hash == file_hash)
        .order_by(desc(models.DocumentVersion.is_current), desc(models.DocumentVersion.id))
        .limit(5)
    ):
        document = db.get(models.Document, version.document_id)
        candidates.append(
            ClassificationCandidate(
                candidate_type="document_version",
                candidate_id=version.id,
                source_name="本地归档库",
                standard_no=document.standard_no if document else None,
                normalized_standard_no=document.normalized_standard_no if document else None,
                standard_name=document.title if document else version.file_name,
                match_score=100,
                match_reason=f"文件 hash 与版本 #{version.id} 完全一致",
            )
        )
    return candidates


def match_existing_documents_for_classification(
    db: Session,
    *,
    numbers: list[str],
    title: str | None,
) -> list[ClassificationCandidate]:
    if not numbers:
        return []
    candidates: list[ClassificationCandidate] = []
    seen_ids: set[int] = set()
    for number in numbers:
        normalized = normalize_standard_no(number).normalized or number
        filters = [
            models.Document.normalized_standard_no == normalized,
            models.Document.standard_no == number,
            func.upper(models.Document.standard_no) == number.upper(),
        ]
        for document in db.scalars(
            select(models.Document).where(or_(*filters)).order_by(desc(models.Document.updated_at)).limit(10)
        ):
            if document.id in seen_ids:
                continue
            if not standard_no_token_match(document.standard_no, number) and not standard_no_token_match(
                document.normalized_standard_no, number
            ):
                continue
            seen_ids.add(document.id)
            exact = bool(document.standard_no and standard_no_token_match(document.standard_no, number))
            title_score = _similarity(title, document.title)
            score = 0
            if exact:
                score += 40
            if document.normalized_standard_no and normalized and document.normalized_standard_no == normalized:
                score += 40
            if title_score >= 90:
                score += 20
            elif title_score >= 80:
                score += 15
            elif title_score >= 60:
                score += 8
            if document.valid_status and document.valid_status not in {"待确认"}:
                score += 5
            candidates.append(
                ClassificationCandidate(
                    candidate_type="document",
                    candidate_id=document.id,
                    source_name="本地标准文件",
                    standard_no=document.standard_no,
                    normalized_standard_no=document.normalized_standard_no,
                    standard_name=document.title,
                    source_status=document.source_status,
                    title_similarity=title_score,
                    match_score=score,
                    match_reason=f"标准编号一致（{number}），标题相似度 {title_score}%",
                )
            )
    return candidates


def _resource_trust_bonus(db: Session, source_id: int | None) -> int:
    if not source_id:
        return 0
    source = db.get(models.TrustedSource, source_id)
    if source and (source.trust_level or "").upper() in HIGH_TRUST_LEVELS:
        return 30
    return 0


def match_standard_resources_for_classification(
    db: Session,
    *,
    numbers: list[str],
    title: str | None,
    allow_external_search: bool,
) -> list[ClassificationCandidate]:
    queries = build_intake_search_queries(
        original_file_name=title or "",
        extracted_standard_no=numbers[0] if numbers else None,
        normalized_standard_no=normalize_standard_no(numbers[0]).normalized if numbers else None,
        extracted_title=title,
    )
    if not queries:
        return []
    results = search_trusted_sources_sliced(
        db,
        queries,
        include_external=allow_external_search,
        limit=20,
    )
    candidates: list[ClassificationCandidate] = []
    for item in results:
        resource_id = item.raw.get("standard_resource_id")
        title_score = item.raw.get("title_similarity") or _similarity(title, item.standard_name)
        score = 0
        if item.normalized_standard_no and numbers:
            if any(
                item.normalized_standard_no == normalize_standard_no(n).normalized
                or standard_no_token_match(item.standard_no, n)
                for n in numbers
            ):
                score += 40
        score += _resource_trust_bonus(db, item.source_id)
        if title_score >= 90:
            score += 20
        elif title_score >= 80:
            score += 15
        if item.source_status in {"现行", "废止", "被替代", "即将实施"}:
            score += 10
        resource = db.get(models.StandardResource, int(resource_id)) if resource_id else None
        if resource and resource.source_category_path:
            score += 5
        if item.detail_url or item.pdf_trial_url:
            score += 5
        score = max(score, item.confidence_score or 0)
        candidates.append(
            ClassificationCandidate(
                candidate_type="standard_resource",
                candidate_id=int(resource_id) if resource_id is not None else None,
                source_id=item.source_id,
                source_name=item.source_name,
                standard_no=item.standard_no,
                normalized_standard_no=item.normalized_standard_no,
                standard_name=item.standard_name,
                source_status=item.source_status,
                source_category_path=resource.source_category_path if resource else None,
                publish_date=item.publish_date,
                effective_date=item.effective_date,
                abolish_date=item.abolish_date,
                detail_url=item.detail_url,
                official_file_url=item.pdf_trial_url,
                title_similarity=title_score,
                match_score=score,
                match_reason=item.match_reason or f"可信源命中，标题相似度 {title_score}%",
            )
        )
    return candidates


def _resource_status_conflict(resources: list[ClassificationCandidate]) -> bool:
    statuses = {r.source_status for r in resources if r.source_status}
    if "现行" in statuses and "废止" in statuses:
        return True
    return False


def _resource_title_conflict(resources: list[ClassificationCandidate]) -> bool:
    if len(resources) <= 1:
        return False
    names = [r.standard_name for r in resources if r.standard_name]
    if len(names) <= 1:
        return False
    base = names[0]
    for name in names[1:]:
        if _similarity(base, name) < 60:
            return True
    return False


def classify_document_file(
    db: Session,
    *,
    file_name: str,
    file_hash: str | None = None,
    source: models.UrlSource | None = None,
    content_type: str | None = None,
    source_name: str | None = None,
    source_category: str | None = None,
    allow_external_search: bool = False,
) -> DocumentClassificationResult:
    thresholds = get_classification_thresholds(db)

    safe_name, _stem, title = clean_file_title(file_name)
    texts = [file_name, _stem, source_name, source_category]
    if source:
        texts.extend([source.source_name, source.remark, source.url, source.category])
    primary_no, all_codes, extracted_title = _extract_metadata_from_texts(*texts)
    display_title = extracted_title or title or safe_name

    number_parts = normalize_standard_no(primary_no or (all_codes[0] if all_codes else None))
    if not number_parts.normalized and all_codes:
        atlas_norm = normalize_atlas_code(all_codes[0])
        if atlas_norm:
            number_parts = StandardNumberParts(
                raw=all_codes[0],
                normalized=atlas_norm,
                prefix=None,
                main_no=None,
                year=None,
                revision_note=None,
            )

    result = DocumentClassificationResult(
        title=display_title,
        original_file_name=file_name,
        standard_no=number_parts.raw or primary_no,
        raw_standard_no=number_parts.raw,
        normalized_standard_no=number_parts.normalized,
        standard_prefix=number_parts.prefix,
        standard_main_no=number_parts.main_no,
        standard_year=number_parts.year,
        standard_revision_note=number_parts.revision_note,
        standard_level=infer_standard_level(number_parts.raw or primary_no, number_parts.prefix),
    )

    match_numbers = collect_intake_match_numbers(
        original_file_name=file_name,
        extracted_standard_no=result.standard_no,
        normalized_standard_no=result.normalized_standard_no,
        extracted_title=display_title,
    )

    version_candidates = match_existing_versions_by_hash(db, file_hash)
    result.candidates.extend(version_candidates)
    if version_candidates:
        top = version_candidates[0]
        result.matched_version_id = top.candidate_id
        if top.candidate_id:
            version = db.get(models.DocumentVersion, top.candidate_id)
            if version:
                result.matched_document_id = version.document_id
        result.confidence_score = 100
        result.risk_level = RISK_LOW
        result.decision = DECISION_DUPLICATE_EXISTING
        result.decision_reason = top.match_reason or "文件 hash 与已有版本完全一致"
        _finalize_result_fields(db, result, source, source_category)
        return result

    if not is_auto_classification_enabled(db):
        _finalize_result_fields(db, result, source, source_category)
        apply_manual_review_classification(result)
        result.evidence = build_classification_evidence(result)
        return result

    has_conflict = _detect_multi_standard_conflict(all_codes)
    doc_candidates = match_existing_documents_for_classification(db, numbers=match_numbers, title=display_title)
    ext_allowed = allow_external_search and get_bool_setting(db, "auto_external_search_enabled", default=False)
    resource_candidates = match_standard_resources_for_classification(
        db,
        numbers=match_numbers,
        title=display_title,
        allow_external_search=ext_allowed,
    )
    result.candidates.extend(doc_candidates)
    result.candidates.extend(resource_candidates)

    if _resource_status_conflict(resource_candidates):
        has_conflict = True
    if len([r for r in resource_candidates if r.match_score >= 70]) > 1 and _resource_title_conflict(
        [r for r in resource_candidates if r.match_score >= 70]
    ):
        has_conflict = True

    score = 0
    best_resource: ClassificationCandidate | None = None
    best_document: ClassificationCandidate | None = None

    if resource_candidates:
        best_resource = max(resource_candidates, key=lambda item: item.match_score)
        score = max(score, best_resource.match_score)
        result.matched_resource_id = best_resource.candidate_id
        if best_resource.source_status:
            src, sys, val = map_source_status(best_resource.source_status)
            result.source_status = src
            result.system_status = sys
            result.valid_status = val

    if doc_candidates:
        best_document = max(doc_candidates, key=lambda item: item.match_score)
        score = max(score, best_document.match_score)
        result.matched_document_id = best_document.candidate_id

    score = max(score, _score_extracted_metadata(result, title=display_title, all_codes=all_codes))

    if not result.standard_no and not display_title:
        score = min(score, 35)
        has_conflict = has_conflict or bool(len(all_codes) > 1)

    if not match_numbers and not result.standard_no:
        score = max(score, 30)

    decision, risk = apply_decision_thresholds(
        score,
        has_conflict=has_conflict,
        is_duplicate=False,
        confirm_threshold=thresholds["confirm"],
        classify_threshold=thresholds["classify"],
        quarantine_threshold=thresholds["quarantine"],
    )

    if decision in FORMAL_INGEST_DECISIONS:
        if best_document and best_document.match_score >= 70:
            decision = DECISION_NEW_VERSION if best_document.match_score >= 80 else DECISION_LINK_EXISTING
        elif best_resource and not best_document:
            if decision == DECISION_AUTO_CONFIRM:
                pass
            elif decision == DECISION_AUTO_CLASSIFY:
                pass

    if not result.standard_no and not match_numbers:
        decision = DECISION_QUARANTINE
        risk = RISK_MEDIUM if score >= thresholds["quarantine"] else RISK_HIGH
        result.decision_reason = "无法提取有效标准编号，进入风险隔离"
    elif has_conflict:
        decision = DECISION_CONFLICT_BLOCK
        risk = RISK_HIGH
        result.decision_reason = "检测到多个不同标准编号或可信源状态/标题冲突"
    else:
        parts_reason: list[str] = []
        if best_resource:
            parts_reason.append(f"可信源匹配：{best_resource.standard_name}")
        if best_document:
            parts_reason.append(f"本地文件匹配：{best_document.standard_name}")
        if not parts_reason:
            parts_reason.append("依据文件名与编号规则评分")
        result.decision_reason = "；".join(parts_reason)

    result.confidence_score = min(100, max(0, score if decision != DECISION_DUPLICATE_EXISTING else 100))
    result.risk_level = risk
    result.decision = decision
    _finalize_result_fields(db, result, source, source_category)
    return result


def _finalize_result_fields(
    db: Session,
    result: DocumentClassificationResult,
    source: models.UrlSource | None,
    source_category: str | None,
) -> None:
    resource_path = None
    if result.matched_resource_id:
        resource = db.get(models.StandardResource, result.matched_resource_id)
        if resource:
            resource_path = resource.source_category_path
            if not result.source_status and resource.source_status:
                src, sys, val = map_source_status(resource.source_status)
                result.source_status = src
                result.system_status = sys
                result.valid_status = val

    cat_name, cat_id = resolve_category(
        db,
        resource_category_path=resource_path,
        source_category=source_category or (source.category if source else None),
        source_category_id=source.category_id if source else None,
        title=result.title,
    )
    result.category = cat_name
    result.category_id = cat_id

    review_status, metadata_status, valid_override = apply_decision_status_fields(result.decision)
    result.review_status = review_status
    result.metadata_status = metadata_status
    if valid_override:
        result.valid_status = valid_override
    elif not result.valid_status:
        _, _, val = map_source_status(result.source_status)
        result.valid_status = val

    result.evidence = build_classification_evidence(result)


def build_classification_evidence(result: DocumentClassificationResult) -> dict[str, Any]:
    return {
        "decision": result.decision,
        "confidence_score": result.confidence_score,
        "risk_level": result.risk_level,
        "decision_reason": result.decision_reason,
        "file_name": result.original_file_name,
        "standard_no": result.standard_no,
        "standard_level": result.standard_level,
        "category": result.category,
        "matched_resource_id": result.matched_resource_id,
        "matched_document_id": result.matched_document_id,
        "matched_version_id": result.matched_version_id,
    }


def apply_classification_to_document_fields(result: DocumentClassificationResult) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "title": result.title,
        "standard_no": result.standard_no,
        "raw_standard_no": result.raw_standard_no,
        "normalized_standard_no": result.normalized_standard_no,
        "standard_prefix": result.standard_prefix,
        "standard_main_no": result.standard_main_no,
        "standard_year": result.standard_year,
        "standard_revision_note": result.standard_revision_note,
        "standard_level": result.standard_level,
        "category": result.category,
        "category_id": result.category_id,
        "source_status": result.source_status,
        "system_status": result.system_status,
        "valid_status": result.valid_status,
        "review_status": result.review_status,
        "metadata_status": result.metadata_status,
        "review_remark": result.decision_reason,
        "classification_decision": result.decision,
        "classification_confidence_score": result.confidence_score,
        "classification_risk_level": result.risk_level,
        "classification_reason": result.decision_reason,
        "matched_resource_id": result.matched_resource_id,
    }
    return fields


def map_to_legacy_intake_decision(decision: str) -> str:
    return LEGACY_INTAKE_DECISION_MAP.get(decision, "need_review")


def should_formal_ingest(decision: str) -> bool:
    return decision in FORMAL_INGEST_DECISIONS


def record_classification_evidence(
    db: Session,
    *,
    document: models.Document | None,
    classification: DocumentClassificationResult,
    source: models.UrlSource | None = None,
    file_hash: str | None = None,
    resource_id: int | None = None,
) -> models.StandardEvidence:
    note = json.dumps(build_classification_evidence(classification), ensure_ascii=False)
    evidence = models.StandardEvidence(
        document_id=document.id if document else None,
        standard_resource_id=resource_id or classification.matched_resource_id,
        source_name=(source.source_name if source else None) or "文件分类",
        source_level="file_classification",
        source_url=source.url if source else None,
        raw_status_text=classification.decision,
        parsed_status=classification.decision,
        page_summary=f"{classification.original_file_name or classification.title} score={classification.confidence_score}",
        page_html_hash=file_hash,
        evidence_note=note,
    )
    db.add(evidence)
    return evidence
