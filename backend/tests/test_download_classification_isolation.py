"""Integration tests for URL download classification isolation."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app import models
from app.classification_decisions import DECISION_CONFLICT_BLOCK
from app.document_classification_service import (
    DocumentClassificationResult,
    apply_classification_to_document_fields,
)
from app.download_service import DownloadedContent, archive_downloaded_content
from app.storage import StorageStatus


def _storage_status(root: Path) -> StorageStatus:
    return StorageStatus(
        root=root,
        available=True,
        exists=True,
        is_dir=True,
        writable=True,
        auto_create=True,
        pause_download_if_unavailable=False,
        message="ok",
    )


def test_archive_conflict_does_not_pollute_existing_document(db, monkeypatch, tmp_path):
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    monkeypatch.setattr(
        "app.download_service.check_storage_root",
        lambda _db, _root: _storage_status(storage_root),
    )
    monkeypatch.setattr(
        "app.settings_store.get_bool_setting",
        lambda _db, key, default=False: True if key == "ingest_enabled" else default,
    )
    monkeypatch.setattr(
        "app.download_service.configured_storage_backend",
        lambda _db: "local",
    )

    existing = models.Document(
        title="正式标准",
        standard_no="GB/T 50300-2013",
        normalized_standard_no="GB/T 50300-2013",
        valid_status="现行",
        review_status="已确认",
        system_status="现行",
        metadata_status="人工确认",
    )
    db.add(existing)
    db.flush()
    before = {
        "valid_status": existing.valid_status,
        "review_status": existing.review_status,
        "metadata_status": existing.metadata_status,
        "classification_decision": existing.classification_decision,
    }

    source = models.UrlSource(
        url="https://example.com/conflict.pdf",
        source_name="冲突测试源",
        check_frequency="manual",
    )
    db.add(source)
    db.flush()

    classification = DocumentClassificationResult(
        title="冲突合集",
        original_file_name="GB50016_GB50116_conflict.pdf",
        standard_no="GB 99995-2099",
        normalized_standard_no="GB 99995-2099",
        standard_prefix="GB",
        standard_level="国家标准",
        valid_status="冲突拦截",
        review_status="冲突拦截",
        metadata_status="系统冲突拦截",
        confidence_score=20,
        risk_level="high",
        decision=DECISION_CONFLICT_BLOCK,
        decision_reason="多编号冲突",
        matched_document_id=existing.id,
    )

    def fake_classify(*args, **kwargs):
        return classification

    monkeypatch.setattr("app.download_service.classify_document_file", fake_classify)

    content = b"%PDF-1.4 conflict test"
    result = archive_downloaded_content(
        db,
        source,
        storage_root,
        DownloadedContent(
            status_code=200,
            url=source.url,
            content=content,
            content_type="application/pdf",
        ),
    )

    db.refresh(existing)
    assert existing.valid_status == before["valid_status"]
    assert existing.review_status == before["review_status"]
    assert existing.metadata_status == before["metadata_status"]
    assert existing.classification_decision == before["classification_decision"]

    archived = db.get(models.Document, result.document_id)
    assert archived is not None
    assert archived.id != existing.id
    assert archived.valid_status == "冲突拦截"
    assert archived.review_status == "冲突拦截"
    assert archived.classification_decision == DECISION_CONFLICT_BLOCK

    version = db.get(models.DocumentVersion, result.version_id)
    assert version is not None
    assert version.document_id == archived.id
    assert version.document_id != existing.id

    evidence_count = db.scalars(
        select(models.StandardEvidence).where(models.StandardEvidence.document_id == existing.id)
    ).all()
    assert len(evidence_count) == 0


def test_apply_classification_fields_include_matched_resource_id():
    result = DocumentClassificationResult(
        title="测试",
        matched_resource_id=42,
        decision=DECISION_CONFLICT_BLOCK,
    )
    fields = apply_classification_to_document_fields(result)
    assert fields["matched_resource_id"] == 42
