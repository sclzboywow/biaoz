"""全国认证认可信息公共服务平台 adapter (certification_records)."""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app import models
from app.batch2_adapters.base import (
    CategoryConfig,
    TrustedSourceSearchQuery,
    TrustedSourceSyncOptions,
    TrustedSourceSyncStats,
    absolute_url,
    detail_hash,
    ensure_single_category,
    fetch_html,
    finalize_category_sync,
    make_client,
    now_utc,
    parse_html_list_items,
)
from app.trusted_source_search_service import LocalIndexSearchAdapterMixin
from app.trusted_source_adapters import TrustedSourceSearchResult, registry

CNCA_GOV_BASE = "https://www.cnca.gov.cn"
CXCNCA_BASE = "https://cx.cnca.cn"
CNCA_LIST_URLS = (
    f"{CNCA_GOV_BASE}/zwxx/gg/index.html",
    f"{CNCA_GOV_BASE}/zwxx/tz/index.html",
    f"{CNCA_GOV_BASE}/",
    "http://rzjg.cnca.cn/jgsp/base/tBaNotice/publicResultLists",
    "http://rzjg.cnca.cn/jgsp/base/tBaNotice/publicRZResultLists",
    "http://rzjg.cnca.cn/jgsp/base/QWfApply/queryCancelInfo",
)
CXCNCA_FALLBACK_PATHS = ("/", "/cnas/", "/cnca/", "/rjw/webin/index.html")


def parse_rzjg_public_rows(html: str, base_url: str) -> list[tuple[str, str | None, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[tuple[str, str | None, str]] = []
    for table in soup.find_all("table"):
        first_row = table.find("tr")
        headers = [cell.get_text(" ", strip=True) for cell in first_row.find_all(["td", "th"])] if first_row else []
        if not any("机构" in cell for cell in headers):
            continue
        for row in table.find_all("tr")[1:]:
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            org_name = cells[1] if len(cells) > 1 else cells[0]
            if len(org_name) < 4 or org_name.startswith("当前"):
                continue
            notice_no = cells[0] if cells else org_name
            title = f"{notice_no} {org_name}".strip()
            anchor = row.find("a", href=True)
            detail_url = absolute_url(base_url, anchor["href"]) if anchor and not anchor["href"].startswith("javascript") else None
            record_type = "认证机构审批公示"
            if "注销" in " ".join(headers + cells):
                record_type = "认证机构注销公示"
            rows.append((title, detail_url, record_type))
    return rows


class CncaCertificationPortalAdapter(LocalIndexSearchAdapterMixin):
    adapter_key = "cnca_certification_portal_public"

    config = CategoryConfig(
        "cnca_certification_portal",
        "认证认可资质",
        "全国认证认可信息公共服务平台 / 资质证书",
        CNCA_GOV_BASE,
    )

    def _upsert_record(
        self,
        db: Session,
        source: models.TrustedSource,
        *,
        item_id: str,
        title: str,
        detail_url: str | None,
        record_type: str,
    ) -> tuple[models.CertificationRecord, bool]:
        existing = (
            db.query(models.CertificationRecord)
            .filter(
                models.CertificationRecord.source_id == source.id,
                models.CertificationRecord.source_item_id == item_id,
            )
            .first()
        )
        created = existing is None
        record = existing or models.CertificationRecord(source_id=source.id, source_item_id=item_id)
        record.record_type = record_type
        record.org_name = title[:500]
        record.certificate_no = None
        record.standard_refs = None
        record.status = "公开索引"
        record.detail_url = detail_url
        record.raw_json = json.dumps({"title": title, "url": detail_url, "type": record_type}, ensure_ascii=False)
        record.last_synced_at = now_utc()
        if created:
            db.add(record)
        return record, created

    def _classify_record_type(self, title: str) -> str:
        upper = title.upper()
        if "检验检测" in title or "CMA" in upper or "资质认定" in title:
            return "检验检测机构"
        if "CNAS" in upper or "实验室认可" in title:
            return "实验室认可"
        if "CCC" in upper or "强制性产品认证" in title:
            return "强制性产品认证"
        if "认证机构" in title and "公示" in title:
            return "认证机构审批公示"
        if "注销" in title:
            return "认证机构注销公示"
        return "认证资质索引"

    def _ingest_html_list(
        self,
        db: Session,
        source: models.TrustedSource,
        *,
        html: str,
        base_url: str,
        seen: set[str],
        stats: TrustedSourceSyncStats,
    ) -> None:
        for item in parse_html_list_items(html, base_url, resource_type="认证资质"):
            if item.title in seen:
                continue
            seen.add(item.title)
            record_type = self._classify_record_type(item.title)
            item_id = detail_hash({"title": item.title, "url": item.detail_url, "type": record_type})
            _, created = self._upsert_record(
                db,
                source,
                item_id=item_id,
                title=item.title,
                detail_url=item.detail_url,
                record_type=record_type,
            )
            stats.created += 1 if created else 0
            stats.updated += 0 if created else 1
            stats.items += 1

    def sync(self, db: Session, source_id: int, options: TrustedSourceSyncOptions) -> TrustedSourceSyncStats:
        source = db.get(models.TrustedSource, source_id)
        if source is None:
            raise ValueError(f"trusted source not found: {source_id}")
        category = ensure_single_category(db, source, self.config)
        db.commit()

        stats = TrustedSourceSyncStats(categories=1)
        category.sync_status = "同步中"
        category.last_sync_started_at = now_utc()
        category.last_sync_error = None
        db.commit()

        errors = 0
        seen: set[str] = set()
        with make_client(referer=CNCA_GOV_BASE) as client:
            try:
                for list_url in CNCA_LIST_URLS[: max(1, options.max_pages)]:
                    try:
                        html = fetch_html(client, list_url)
                    except RuntimeError:
                        continue
                    stats.pages += 1
                    if "rzjg.cnca.cn" in list_url:
                        base = re.match(r"https?://[^/]+", list_url)
                        base_url = base.group(0) if base else list_url
                        for title, detail_url, record_type in parse_rzjg_public_rows(html, base_url):
                            if title in seen:
                                continue
                            seen.add(title)
                            item_id = detail_hash({"title": title, "url": detail_url, "type": record_type})
                            _, created = self._upsert_record(
                                db,
                                source,
                                item_id=item_id,
                                title=title,
                                detail_url=detail_url,
                                record_type=record_type,
                            )
                            stats.created += 1 if created else 0
                            stats.updated += 0 if created else 1
                            stats.items += 1
                    else:
                        self._ingest_html_list(db, source, html=html, base_url=CNCA_GOV_BASE, seen=seen, stats=stats)

                if stats.items == 0:
                    for path in CXCNCA_FALLBACK_PATHS:
                        url = f"{CXCNCA_BASE.rstrip('/')}{path}"
                        try:
                            html = fetch_html(client, url)
                        except RuntimeError:
                            continue
                        stats.pages += 1
                        self._ingest_html_list(db, source, html=html, base_url=CXCNCA_BASE, seen=seen, stats=stats)

                db.commit()
                category.resource_count = stats.items
            except Exception as exc:
                errors = 1
                category.last_sync_error = str(exc)[:500]
        finalize_category_sync(db, category, stats, errors=errors, page_number=stats.pages or 1, total_pages=1)
        return stats

    def search(self, db: Session, source_id: int, query: TrustedSourceSearchQuery) -> list[TrustedSourceSearchResult]:
        return []

    def search_external(self, db: Session, source_id: int, query: TrustedSourceSearchQuery) -> list[TrustedSourceSearchResult]:
        return []


registry.register(CncaCertificationPortalAdapter())
