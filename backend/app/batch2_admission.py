"""Batch-2 trusted source file admission and formal-library policy.

Batch-2 enters the formal pipeline only with verified standard body files.
Announcement / plan / publicity materials remain clues (StandardEvidence only).
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.settings_store import get_bool_setting
from app.standard_number import normalize_standard_no

BATCH2_ADAPTER_KEYS: tuple[str, ...] = (
    "mot_transport_standard_public",
    "mwr_water_standard_public",
    "cnca_rb_standard_public",
    "miit_standard_public",
    "nea_energy_announcement_public",
    "nrs_natural_resource_standard_public",
    "mem_fire_rescue_announcement_public",
    "mem_emergency_announcement_public",
    "cnca_certification_portal_public",
)

BATCH2_ANNOUNCEMENT_ADAPTER_KEYS: tuple[str, ...] = (
    "miit_standard_public",
    "nea_energy_announcement_public",
    "mem_fire_rescue_announcement_public",
    "mem_emergency_announcement_public",
    "mwr_water_standard_public",
)

BATCH2_STANDARD_BODY_ADAPTER_KEYS: tuple[str, ...] = (
    "mot_transport_standard_public",
    "nrs_natural_resource_standard_public",
    "cnca_rb_standard_public",
)

FILE_INGEST_ANNOUNCEMENT_CLUE = "announcement_clue"
FILE_INGEST_FILE_MISSING = "file_missing"
FILE_INGEST_MANUAL_REVIEW = "manual_review"
FILE_INGEST_FILE_READY = "file_ready"
FILE_INGEST_ADMITTED = "admitted"
FILE_INGEST_EVIDENCE_ONLY = "evidence_only"

OFFICIAL_FILE_EXTENSIONS = frozenset({".pdf", ".doc", ".docx", ".xls", ".xlsx"})
OFFICIAL_ONLINE_READING_HINTS = (
    "online",
    "stdonline",
    "reading",
    "preview",
    "在线阅读",
    "在线预览",
    "全文公开",
)

EXCLUDED_FILE_RESOURCE_TYPES = (
    "标准公告",
    "征求意见",
    "废止目录",
    "标准计划",
    "政策通知",
    "工业和信息化标准增强",
)

EXCLUDED_FILE_TITLE_KEYWORDS = (
    "公告",
    "征求意见",
    "报批",
    "公示",
    "目录",
    "废止",
    "计划",
    "通知",
    "通报",
    "清单",
)


@dataclass(frozen=True)
class FileAdmissionResult:
    allowed: bool
    evidence_only: bool
    reason: str


def is_batch2_adapter_key(adapter_key: str | None) -> bool:
    return bool(adapter_key and adapter_key in BATCH2_ADAPTER_KEYS)


def is_batch2_announcement_adapter(adapter_key: str | None) -> bool:
    return bool(adapter_key and adapter_key in BATCH2_ANNOUNCEMENT_ADAPTER_KEYS)


def is_batch2_standard_body_adapter(adapter_key: str | None) -> bool:
    return bool(adapter_key and adapter_key in BATCH2_STANDARD_BODY_ADAPTER_KEYS)


def is_batch2_trusted_source(source: models.TrustedSource | None) -> bool:
    return is_batch2_adapter_key(source.adapter_key if source else None)


def is_batch2_standard_resource(
    db: Session,
    resource: models.StandardResource | None,
    *,
    trusted_source: models.TrustedSource | None = None,
) -> bool:
    if resource is None:
        return False
    if trusted_source is None:
        trusted_source = db.get(models.TrustedSource, resource.source_id)
    return is_batch2_trusted_source(trusted_source)


def batch2_pipeline_enabled(db: Session) -> bool:
    return get_bool_setting(db, "batch2_file_ingest_enabled", default=False)


def sanitize_batch2_resource_updates(updates: dict) -> dict:
    return dict(updates)


def _similarity(left: str | None, right: str | None) -> int:
    return int(SequenceMatcher(None, (left or "").strip(), (right or "").strip()).ratio() * 100)


def _url_extension(url: str | None) -> str:
    if not url:
        return ""
    path = urlparse(url).path or url
    return Path(path.split("?", 1)[0]).suffix.lower()


def is_official_online_reading_url(url: str | None) -> bool:
    if not url:
        return False
    lowered = url.lower()
    return any(token in lowered for token in OFFICIAL_ONLINE_READING_HINTS)


def is_openstd_official_url(url: str | None) -> bool:
    if not url:
        return False
    lowered = url.lower()
    return "openstd.samr.gov.cn" in lowered and "hcno=" in lowered


def is_mot_kfs_official_url(url: str | None) -> bool:
    if not url:
        return False
    lowered = url.lower()
    return "jtst.mot.gov.cn/kfs/file/" in lowered


def is_supported_official_file_url(url: str | None, file_name: str | None = None) -> bool:
    extension = _url_extension(url) or _url_extension(file_name)
    if extension in OFFICIAL_FILE_EXTENSIONS:
        return True
    if is_openstd_official_url(url) or is_mot_kfs_official_url(url):
        return True
    return is_official_online_reading_url(url)


def is_excluded_batch2_file_resource(
    *,
    resource_type: str | None,
    title: str | None,
    standard_name: str | None = None,
    adapter_key: str | None = None,
) -> bool:
    if is_batch2_announcement_adapter(adapter_key):
        return True
    label = " ".join(part for part in (resource_type, title, standard_name) if part)
    if resource_type and resource_type in EXCLUDED_FILE_RESOURCE_TYPES:
        return True
    return any(keyword in label for keyword in EXCLUDED_FILE_TITLE_KEYWORDS)


def validate_standard_file_consistency(
    *,
    standard_no: str | None,
    standard_name: str | None,
    file_title: str | None,
    file_text_sample: str | None = None,
    minimum_similarity: int = 60,
) -> tuple[bool, str]:
    number_parts = normalize_standard_no(standard_no)
    normalized_no = number_parts.normalized or (standard_no or "").strip()
    if not normalized_no:
        return False, "missing_standard_no"
    haystack = " ".join(part for part in (file_title, file_text_sample, standard_name) if part).upper()
    if normalized_no.upper() not in haystack and (standard_no or "").upper() not in haystack:
        return False, "standard_no_mismatch"
    if standard_name and file_title and _similarity(standard_name, file_title) < minimum_similarity:
        if normalized_no.upper() in haystack or (standard_no or "").upper() in haystack:
            return True, "ok"
        return False, f"title_similarity<{minimum_similarity}"
    return True, "ok"


def validate_pdf_body_structure(
    *,
    content: bytes,
    standard_no: str | None,
    standard_name: str | None,
    pdf_title: str | None = None,
) -> tuple[bool, str]:
    if len(content) < 1024:
        return False, "pdf_too_small"
    try:
        from app.ocr_download_service import validate_pdf

        validation = validate_pdf(content)
    except Exception as exc:
        return False, f"pdf_validation_error:{exc}"
    if not validation.valid:
        return False, validation.message or "pdf_invalid"
    return validate_standard_file_consistency(
        standard_no=standard_no,
        standard_name=standard_name,
        file_title=pdf_title or validation.title,
        file_text_sample=validation.title,
    )


def evaluate_batch2_file_admission(
    db: Session,
    *,
    resource: models.StandardResource,
    trusted_source: models.TrustedSource | None = None,
    official_file_url: str | None = None,
    file_name: str | None = None,
    file_title: str | None = None,
    file_content: bytes | None = None,
    content_type: str | None = None,
) -> FileAdmissionResult:
    if trusted_source is None:
        trusted_source = db.get(models.TrustedSource, resource.source_id)
    if not is_batch2_trusted_source(trusted_source):
        return FileAdmissionResult(True, False, "not_batch2")

    adapter_key = trusted_source.adapter_key if trusted_source else None
    if is_excluded_batch2_file_resource(
        resource_type=resource.resource_type,
        title=resource.standard_name,
        standard_name=resource.standard_name,
        adapter_key=adapter_key,
    ):
        return FileAdmissionResult(False, True, "excluded_announcement_or_plan_type")

    candidate_url = official_file_url or resource.official_file_url or resource.pdf_trial_url or resource.detail_url
    if not candidate_url:
        return FileAdmissionResult(False, True, "missing_official_file_url")

    if not is_supported_official_file_url(candidate_url, file_name=file_name):
        return FileAdmissionResult(False, True, "unsupported_official_file_type")

    is_pdf = _url_extension(candidate_url) == ".pdf" or (content_type or "").lower().startswith("application/pdf")
    if file_content and is_pdf:
            ok, reason = validate_pdf_body_structure(
                content=file_content,
                standard_no=resource.standard_no,
                standard_name=resource.standard_name,
                pdf_title=file_title or file_name,
            )
            if not ok:
                return FileAdmissionResult(False, True, reason)

    ok, reason = validate_standard_file_consistency(
        standard_no=resource.standard_no,
        standard_name=resource.standard_name,
        file_title=file_title or file_name or resource.standard_name,
    )
    if not ok:
        return FileAdmissionResult(False, True, reason)

    return FileAdmissionResult(True, False, "admitted")


def should_block_batch2_formal_file_ingest(
    db: Session,
    *,
    resource: models.StandardResource | None,
    trusted_source: models.TrustedSource | None = None,
) -> tuple[bool, str]:
    if resource is None:
        return True, "missing_resource"
    if trusted_source is None:
        trusted_source = db.get(models.TrustedSource, resource.source_id)
    if not is_batch2_trusted_source(trusted_source):
        return False, ""
    adapter_key = trusted_source.adapter_key if trusted_source else None
    if is_excluded_batch2_file_resource(
        resource_type=resource.resource_type,
        title=resource.standard_name,
        standard_name=resource.standard_name,
        adapter_key=adapter_key,
    ):
        return True, FILE_INGEST_ANNOUNCEMENT_CLUE
    if resource.file_ingest_status in {FILE_INGEST_ANNOUNCEMENT_CLUE, FILE_INGEST_EVIDENCE_ONLY, FILE_INGEST_FILE_MISSING}:
        return True, resource.file_ingest_status or FILE_INGEST_FILE_MISSING
    if resource.file_ingest_status not in {FILE_INGEST_FILE_READY, FILE_INGEST_ADMITTED}:
        return True, resource.file_ingest_status or FILE_INGEST_MANUAL_REVIEW
    if not (resource.official_file_url or resource.pdf_trial_url):
        return True, FILE_INGEST_FILE_MISSING
    if not batch2_pipeline_enabled(db):
        return True, "batch2_pipeline_disabled"
    return False, ""


def record_batch2_file_evidence_only(
    db: Session,
    *,
    resource: models.StandardResource,
    url_source: models.UrlSource,
    file_hash: str,
    summary: str,
    reason: str,
    trusted_source: models.TrustedSource | None = None,
) -> models.StandardEvidence:
    existing = db.scalars(
        select(models.StandardEvidence).where(
            models.StandardEvidence.standard_resource_id == resource.id,
            models.StandardEvidence.page_html_hash == file_hash,
        )
    ).first()
    if existing:
        return existing

    if trusted_source is None:
        trusted_source = db.get(models.TrustedSource, resource.source_id)
    source_level = (trusted_source.trust_level if trusted_source else None) or "B"

    evidence = models.StandardEvidence(
        standard_resource_id=resource.id,
        document_id=None,
        source_name=resource.source_name,
        source_level=source_level,
        source_url=url_source.url,
        raw_status_text=reason,
        parsed_status=FILE_INGEST_EVIDENCE_ONLY,
        page_summary=summary,
        page_html_hash=file_hash,
        evidence_note=f"第二批源材料仅作线索/证据，不入正式文件库：{reason}",
    )
    db.add(evidence)
    resource.file_ingest_status = FILE_INGEST_EVIDENCE_ONLY
    db.flush()
    return evidence


def resolve_batch2_download_target(resource: models.StandardResource) -> dict | None:
    url = (resource.official_file_url or resource.pdf_trial_url or "").strip()
    if not url or resource.file_ingest_status not in {FILE_INGEST_FILE_READY, FILE_INGEST_ADMITTED}:
        return None
    if not is_supported_official_file_url(url):
        return None
    if is_openstd_official_url(url):
        from app.gb688_captcha_download import extract_hcno

        hcno = extract_hcno(url)
        if hcno:
            return {
                "provider": "openstd",
                "download_url": url,
                "captcha_url": None,
                "hcno": hcno,
                "host": "openstd.samr.gov.cn",
            }
    host = urlparse(url).hostname or ""
    return {
        "provider": "batch2_direct",
        "download_url": url,
        "captcha_url": None,
        "host": host.lower() or None,
    }
