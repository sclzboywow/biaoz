from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from sqlalchemy.orm import Session


@dataclass
class TrustedSourceListItem:
    source_item_id: str
    standard_no: str | None
    standard_name: str
    source_status: str | None = None
    resource_type: str | None = None
    source_category_path: str | None = None
    detail_url: str | None = None
    publish_date: date | None = None
    effective_date: date | None = None
    abolish_date: date | None = None
    summary: str | None = None
    keywords: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class TrustedSourceDetail:
    storage_date: date | None = None
    chief_editor_unit: str | None = None
    summary: str | None = None
    catalog_text: str | None = None
    mandatory_provisions: str | None = None
    expert_interpretation: str | None = None
    product_info: str | None = None
    change_info: str | None = None
    related_books: str | None = None
    pdf_trial_url: str | None = None
    detail_hash: str | None = None
    raw_html_path: str | None = None
    raw_text_path: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class TrustedSourceSyncOptions:
    max_pages: int = 1
    include_detail: bool = True
    category_id: str | None = None
    only_pending_categories: bool = False
    category_limit: int | None = None


@dataclass
class TrustedSourceSyncStats:
    pages: int = 0
    items: int = 0
    created: int = 0
    updated: int = 0
    skipped_existing_detail: int = 0
    categories: int = 0
    errors: int = 0
    matches: int = 0
    sync_logs: int = 0
    alerts: int = 0
    linked_change_logs: int = 0


@dataclass
class TrustedSourceSearchQuery:
    standard_no: str | None = None
    normalized_standard_no: str | None = None
    standard_name: str | None = None
    keywords: list[str] = field(default_factory=list)
    publish_date: date | None = None
    effective_date: date | None = None


@dataclass
class TrustedSourceSearchResult:
    source_id: int
    source_name: str
    standard_no: str | None
    normalized_standard_no: str | None
    standard_name: str
    source_status: str | None = None
    publish_date: date | None = None
    effective_date: date | None = None
    abolish_date: date | None = None
    detail_url: str | None = None
    pdf_trial_url: str | None = None
    confidence_score: int = 0
    match_reason: str | None = None
    raw: dict = field(default_factory=dict)


class TrustedSourceAdapter(Protocol):
    adapter_key: str

    def sync(self, db: Session, source_id: int, options: TrustedSourceSyncOptions) -> TrustedSourceSyncStats:
        ...

    def search(self, db: Session, source_id: int, query: TrustedSourceSearchQuery) -> list[TrustedSourceSearchResult]:
        ...


class TrustedSourceAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, TrustedSourceAdapter] = {}

    def register(self, adapter: TrustedSourceAdapter) -> None:
        self._adapters[adapter.adapter_key] = adapter

    def get(self, key: str) -> TrustedSourceAdapter | None:
        return self._adapters.get(key)


registry = TrustedSourceAdapterRegistry()
