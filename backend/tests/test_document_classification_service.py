"""Tests for document classification service (Issue #6)."""

from __future__ import annotations

from app import models
from app.classification_decisions import DECISION_CONFLICT_BLOCK, DECISION_DUPLICATE_EXISTING, DECISION_QUARANTINE
from app.document_binding import is_document_project_bindable
from app.document_classification_service import (
    apply_decision_thresholds,
    classify_document_file,
    infer_standard_level,
    map_source_status,
)


def test_infer_standard_level_gb(db):
    assert infer_standard_level("GB/T 50300-2013", "GB/T") == "国家标准"


def test_infer_standard_level_jgj(db):
    assert infer_standard_level("JGJ 59-2011", "JGJ") == "行业标准"


def test_infer_standard_level_db51(db):
    assert infer_standard_level("DB51/T 1234-2020", "DB51/T") == "地方标准"


def test_infer_standard_level_t_cecs(db):
    assert infer_standard_level("T/CECS 100-2020", "T/CECS") == "团体标准"


def test_infer_standard_level_q_enterprise(db):
    assert infer_standard_level("Q/ABC 001-2022", "Q/ABC") == "企业标准"


def test_infer_standard_level_atlas(db):
    assert infer_standard_level("03G101-1", None) == "标准图集"


def test_classify_gb50300_auto(db):
    result = classify_document_file(
        db,
        file_name="GB_T_50300-2013 建筑工程施工质量验收统一标准.pdf",
    )
    assert result.standard_prefix == "GB/T"
    assert result.standard_level == "国家标准"
    assert result.category == "工程建设"
    assert result.confidence_score >= 40
    assert result.decision in {"auto_confirm", "auto_classify", "quarantine"}


def test_classify_jgj59(db):
    result = classify_document_file(db, file_name="JGJ 59-2011 建筑施工安全检查标准.pdf")
    assert result.standard_prefix == "JGJ"
    assert result.standard_level == "行业标准"
    assert result.category in {"工程建设", "安全生产"}


def test_classify_no_number_quarantine(db):
    result = classify_document_file(db, file_name="建筑工程验收规范扫描件.pdf")
    assert result.decision == DECISION_QUARANTINE
    assert result.review_status == "风险隔离"


def test_classify_multi_number_conflict(db):
    result = classify_document_file(
        db,
        file_name="GB 50016-2014 和 GB 50116-2013 消防规范合集.pdf",
    )
    assert result.decision == DECISION_CONFLICT_BLOCK
    assert result.risk_level == "high"
    assert result.review_status == "冲突拦截"


def test_classify_duplicate_hash(db):
    document = models.Document(title="已有文件", standard_no="GB/T 50300-2013", valid_status="现行", review_status="已确认")
    db.add(document)
    db.flush()
    version = models.DocumentVersion(
        document_id=document.id,
        file_name="old.pdf",
        file_path="url-sources/1/old.pdf",
        file_hash="abc123hash",
        file_size=100,
        is_current=True,
    )
    db.add(version)
    db.commit()

    result = classify_document_file(db, file_name="GB_T_50300-2013.pdf", file_hash="abc123hash")
    assert result.decision == DECISION_DUPLICATE_EXISTING
    assert result.confidence_score == 100


def test_map_source_status_abolished(db):
    _, system, valid = map_source_status("废止")
    assert system == "来源确认废止"
    assert valid == "来源确认废止"


def test_resource_abolished_status_on_classify(db):
    source = models.TrustedSource(source_name="测试源", base_url="https://example.com", trust_level="A", trust_score=100)
    db.add(source)
    db.flush()
    resource = models.StandardResource(
        source_id=source.id,
        standard_no="GB/T 50300-2013",
        normalized_standard_no="GB/T 50300-2013",
        standard_prefix="GB/T",
        standard_name="建筑工程施工质量验收统一标准",
        source_status="废止",
    )
    db.add(resource)
    db.commit()

    result = classify_document_file(
        db,
        file_name="GB_T_50300-2013 建筑工程施工质量验收统一标准.pdf",
    )
    assert result.valid_status == "来源确认废止"
    assert result.system_status == "来源确认废止"


def test_apply_decision_thresholds():
    decision, risk = apply_decision_thresholds(92, has_conflict=False, is_duplicate=False)
    assert decision == "auto_confirm"
    assert risk == "low"


def test_document_binding_excludes_quarantine(db):
    doc = models.Document(
        title="隔离",
        valid_status="隔离留存",
        review_status="风险隔离",
        metadata_status="系统隔离",
        classification_decision="quarantine",
    )
    assert is_document_project_bindable(doc, db=db) is False


def test_document_binding_allows_auto_confirm(db):
    doc = models.Document(
        title="现行",
        valid_status="来源确认现行",
        review_status="自动确认",
        metadata_status="系统自动确认",
        classification_decision="auto_confirm",
    )
    assert is_document_project_bindable(doc, db=db) is True
