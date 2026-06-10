"""URL 来源画像（兼容层）：委托 source_governance 第二阶段实现。"""

from __future__ import annotations

import json

from app import models
from app.source_governance import profile_url_source_row


class UrlSourceProfile:
    __slots__ = (
        "host",
        "url_type",
        "file_ext",
        "is_official_domain",
        "is_cloud_drive",
        "is_probable_pdf",
        "is_probable_detail_page",
        "source_quality_score",
        "governance_status",
        "duplicate_group_key",
    )

    def __init__(self, **kwargs):
        for key in self.__slots__:
            setattr(self, key, kwargs.get(key))

    def to_dict(self) -> dict:
        return {key: getattr(self, key) for key in self.__slots__}


def profile_url(url: str, *, extra_official_domains: set[str] | None = None) -> UrlSourceProfile:
    row = profile_url_source_row(url, extra_official_domains=extra_official_domains)
    return UrlSourceProfile(
        host=row["host"],
        url_type=row["url_type"],
        file_ext=row["file_ext"],
        is_official_domain=row["is_official_domain"],
        is_cloud_drive=row["is_cloud_drive"],
        is_probable_pdf=row["is_probable_pdf"],
        is_probable_detail_page=row["is_probable_detail_page"],
        source_quality_score=row["source_quality_score"],
        governance_status=row["governance_status"],
        duplicate_group_key=row["duplicate_group_key"],
    )


def apply_profile_to_url_source(source: models.UrlSource, profile: UrlSourceProfile) -> None:
    source.host = profile.host
    source.url_type = profile.url_type
    source.file_ext = profile.file_ext
    source.is_official_domain = profile.is_official_domain
    source.is_cloud_drive = profile.is_cloud_drive
    source.is_probable_pdf = profile.is_probable_pdf
    source.is_probable_detail_page = profile.is_probable_detail_page
    source.source_quality_score = profile.source_quality_score
    source.governance_status = profile.governance_status
    source.duplicate_group_key = profile.duplicate_group_key


def profile_evidence_json(source: models.UrlSource, profile: UrlSourceProfile) -> str:
    return json.dumps({"url": source.url, "profile": profile.to_dict()}, ensure_ascii=False)


def extract_host(url: str) -> str | None:
    return profile_url(url).host


def build_duplicate_group_key(url: str) -> str | None:
    return profile_url(url).duplicate_group_key
