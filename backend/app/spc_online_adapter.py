from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlencode, urljoin

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app import models
from app.samr_public_adapters import _detail_hash, _limit, _parse_date, _system_status, _upsert_resource
from app.status_calibration import attach_change_logs_to_documents, calibrate_resource_status
from app.trusted_source_adapters import TrustedSourceAdapter, TrustedSourceSyncOptions, TrustedSourceSyncStats, registry


SPC_BASE_URL = "https://www.spc.org.cn"
SPC_PAGE_DELAY_SECONDS = float(os.getenv("SPC_PAGE_DELAY_SECONDS", "2"))
SPC_DETAIL_DELAY_SECONDS = float(os.getenv("SPC_DETAIL_DELAY_SECONDS", "1"))
SPC_RETRY_ATTEMPTS = int(os.getenv("SPC_RETRY_ATTEMPTS", "3"))
SPC_FAST_METADATA_ONLY = os.getenv("SPC_FAST_METADATA_ONLY", "0") == "1"


@dataclass(frozen=True)
class SpcCategory:
    type_code: str
    category_name: str
    resource_type: str
    sctype: str | None = None
    scname: str | None = None

    @property
    def category_id(self) -> str:
        if self.sctype:
            return f"spc_{self.type_code.lower()}_{self.sctype.lower()}"
        return f"spc_{self.type_code.lower()}"

    @property
    def category_path(self) -> str:
        if self.sctype:
            name = f"{self.sctype} {self.scname or ''}".strip()
            return f"中国标准在线服务网 / {self.category_name} / {name}"
        return f"中国标准在线服务网 / {self.category_name}"

    @property
    def source_url(self) -> str:
        params = {"type": self.type_code}
        if self.sctype:
            params["sctype"] = self.sctype
            params["scname"] = self.scname or ""
        return f"{SPC_BASE_URL}/standardonline/datalist?{urlencode(params)}"


SPC_CATEGORIES: tuple[SpcCategory, ...] = (
    SpcCategory("CN", "国家标准", "国家标准"),
    SpcCategory("QT", "行业标准", "行业标准"),
    SpcCategory("DFBZ", "地方标准", "地方标准"),
    SpcCategory("TC", "团体标准", "团体标准"),
    SpcCategory("QYBZ", "企业标准", "企业标准"),
    SpcCategory("JJ", "计量技术规范", "计量技术规范"),
)


def _now() -> datetime:
    return datetime.now(UTC)


def _delay(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").replace("\u3000", " ").split())


def _first_text(soup: BeautifulSoup, selector: str) -> str | None:
    item = soup.select_one(selector)
    return _clean_text(item.get_text(" ", strip=True)) if item else None


def _hash_html(html: str) -> str:
    return hashlib.sha256(html.encode("utf-8", errors="ignore")).hexdigest()


def _ensure_category(db: Session, source: models.TrustedSource, config: SpcCategory) -> models.SourceCategory:
    category = (
        db.query(models.SourceCategory)
        .filter(
            models.SourceCategory.source_id == source.id,
            models.SourceCategory.source_category_id == config.category_id,
        )
        .first()
    )
    if category is None:
        category = models.SourceCategory(
            source_id=source.id,
            source_category_id=config.category_id,
            category_name=config.category_name,
            category_path=config.category_path,
            source_url=config.source_url,
            sync_status="待同步",
        )
        db.add(category)
        db.flush()
    else:
        category.category_name = config.category_name
        category.category_path = config.category_path
        category.source_url = config.source_url
    return category


def _parse_total_count(soup: BeautifulSoup) -> int | None:
    text = soup.get_text(" ", strip=True)
    patterns = (
        r"共\s*([0-9,]+)\s*条",
        r"总计\s*([0-9,]+)\s*条",
        r"([0-9,]+)\s*条记录",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def _parse_list_items(html: str, category: SpcCategory) -> tuple[list[dict[str, Any]], int | None]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict[str, Any]] = []
    for row in soup.find_all("tr"):
        cells = [_clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all("td")]
        if len(cells) < 6 or not cells[1]:
            continue
        detail_link = row.find("a", href=lambda href: href and "/online/" in href)
        detail_url = urljoin(SPC_BASE_URL, detail_link.get("href")) if detail_link else None
        item_id = detail_url.rstrip("/").rsplit("/", 1)[-1].replace(".html", "") if detail_url else f"{category.type_code}:{cells[1]}"
        items.append(
            {
                "source_item_id": item_id,
                "standard_no": cells[1],
                "standard_name": cells[2],
                "source_status": cells[3],
                "publish_date": _parse_date(cells[4]),
                "effective_date": _parse_date(cells[5]),
                "detail_url": detail_url,
                "type_code": category.type_code,
            }
        )
    return items, _parse_total_count(soup)


def _table_label_values(soup: BeautifulSoup) -> dict[str, str]:
    values: dict[str, str] = {}
    for row in soup.find_all("tr"):
        cells = [_clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td", "li", "p", "span"])]
        cells = [cell for cell in cells if cell]
        for index, cell in enumerate(cells[:-1]):
            label = cell.rstrip("：:")
            if 1 <= len(label) <= 20 and ("：" in cell or cell.endswith(":")):
                values[label] = cells[index + 1]
    text = soup.get_text("\n", strip=True)
    for label in (
        "标准号",
        "标准名称",
        "英文名称",
        "标准状态",
        "发布日期",
        "实施日期",
        "中国标准分类号",
        "中标分类号",
        "国际标准分类号",
        "标准页数",
        "标准字数",
        "开本页数",
        "价格",
        "主管部门",
        "归口单位",
        "发布单位",
        "起草单位",
        "起草人",
    ):
        if label in values:
            continue
        match = re.search(rf"{re.escape(label)}[：:\s]+([^\n\r]+)", text)
        if match:
            values[label] = _clean_text(match.group(1))
    return values


def _find_detail_block(soup: BeautifulSoup, keywords: tuple[str, ...]) -> str | None:
    for keyword in keywords:
        node = soup.find(string=lambda text: text and keyword in text)
        if node is None:
            continue
        parent = node.parent
        while parent and parent.name not in {"li", "div", "section", "table"}:
            parent = parent.parent
        if parent:
            text = _clean_text(parent.get_text(" ", strip=True))
            if len(text) > len(keyword):
                return text
    return None


def _parse_detail(html: str, detail_url: str, category: SpcCategory) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    values = _table_label_values(soup)
    title = _first_text(soup, "h1") or _first_text(soup, ".detail-title") or (soup.title.get_text(strip=True) if soup.title else "")
    online = soup.find(attrs={"onclick": lambda value: value and "onlineReading" in value})
    online_onclick = online.get("onclick") if online else None
    online_enabled = bool(online_onclick)
    standard_no = values.get("标准号") or None
    if not standard_no:
        match = re.search(r"([A-Z]{1,5}(?:/[A-Z]+)?(?:\s|&nbsp;|-)*[0-9][A-Z0-9./-]*-?[0-9]{4})", title)
        standard_no = _clean_text(match.group(1)) if match else None
    source_status = values.get("标准状态") or None
    summary_parts = [
        f"SPC分类：{category.category_name}",
        f"在线阅读：{'可见入口' if online_enabled else '未发现入口'}",
        f"英文名称：{values.get('英文名称')}" if values.get("英文名称") else "",
        f"ICS：{values.get('国际标准分类号')}" if values.get("国际标准分类号") else "",
        f"CCS：{values.get('中标分类号') or values.get('中国标准分类号')}" if values.get("中标分类号") or values.get("中国标准分类号") else "",
        f"页数：{values.get('标准页数') or values.get('开本页数')}" if values.get("标准页数") or values.get("开本页数") else "",
        f"价格：{values.get('价格')}" if values.get("价格") else "",
    ]
    return {
        "standard_no": standard_no,
        "standard_name": values.get("标准名称") or title.replace("-中国标准在线服务网", "").strip(),
        "source_status": source_status,
        "publish_date": _parse_date(values.get("发布日期")),
        "effective_date": _parse_date(values.get("实施日期")),
        "chief_editor_unit": values.get("起草单位") or values.get("归口单位") or values.get("主管部门"),
        "keywords": values.get("国际标准分类号") or values.get("中标分类号") or values.get("中国标准分类号"),
        "summary": "\n".join(part for part in summary_parts if part),
        "catalog_text": json.dumps(
            {
                "labels": values,
                "online_reading": {
                    "enabled": online_enabled,
                    "form_action": "/stdlib/stdonline",
                    "method": "POST",
                    "onclick": online_onclick,
                    "verified_pdf_stream": False,
                    "note": "会员在线阅读需要登录态，默认采集只记录官方入口，不批量保存阅读流文件。",
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        "mandatory_provisions": _find_detail_block(soup, ("范围", "适用范围", "主要技术内容")),
        "change_info": _find_detail_block(soup, ("代替", "被代替", "替代关系")),
        "product_info": _find_detail_block(soup, ("定价", "价格", "页数")),
        "detail_hash": _hash_html(html),
        "detail_url": detail_url,
        "online_reading_url": f"{SPC_BASE_URL}/stdlib/stdonline",
        "online_reading_enabled": online_enabled,
    }


class SpcOnlineAdapter(TrustedSourceAdapter):
    adapter_key = "spc_standard_online"

    def _client(self) -> httpx.Client:
        return httpx.Client(
            follow_redirects=True,
            timeout=60,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StandardDocsIngest/1.0",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": f"{SPC_BASE_URL}/standardonline/datalist?type=CN",
            },
        )

    def _fetch(self, client: httpx.Client, url: str) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, SPC_RETRY_ATTEMPTS + 1):
            try:
                response = client.get(url)
                response.raise_for_status()
                return response
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < SPC_RETRY_ATTEMPTS:
                    _delay(min(2 * attempt, 10))
        raise RuntimeError(f"SPC fetch failed: {url}: {last_error}")

    def _categories(self, category_id: str | None) -> list[SpcCategory]:
        if not category_id:
            return list(SPC_CATEGORIES)
        if ":" in category_id:
            parts = category_id.split(":", 2)
            type_code = parts[0].upper()
            sctype = parts[1].strip()
            scname = parts[2].strip() if len(parts) > 2 else ""
            base = next((item for item in SPC_CATEGORIES if item.type_code == type_code), None)
            if base and sctype:
                return [
                    SpcCategory(
                        base.type_code,
                        base.category_name,
                        base.resource_type,
                        sctype=sctype,
                        scname=scname,
                    )
                ]
            return []
        return [item for item in SPC_CATEGORIES if item.category_id == category_id or item.type_code == category_id.upper()]

    def sync(self, db: Session, source_id: int, options: TrustedSourceSyncOptions) -> TrustedSourceSyncStats:
        source = db.get(models.TrustedSource, source_id)
        if source is None:
            raise ValueError(f"trusted source not found: {source_id}")
        categories = self._categories(options.category_id)
        if not categories:
            raise ValueError(f"SPC category not found: {options.category_id}")

        stats = TrustedSourceSyncStats(categories=len(categories))
        with self._client() as client:
            for config in categories[: options.category_limit or len(categories)]:
                category = _ensure_category(db, source, config)
                if options.only_pending_categories and category.sync_status == "已同步":
                    continue
                start_page = max(0, category.last_synced_page or 0) if options.only_pending_categories else 0
                end_page = start_page + max(options.max_pages, 1) - 1
                category.sync_status = "同步中"
                category.last_sync_started_at = _now()
                category.last_sync_error = None
                db.commit()

                errors = 0
                for page_index in range(start_page, end_page + 1):
                    list_url = f"{config.source_url}&pageIndex={page_index}"
                    try:
                        response = self._fetch(client, list_url)
                        items, total_count = _parse_list_items(response.text, config)
                    except Exception as exc:
                        errors += 1
                        category.last_sync_error = str(exc)
                        break

                    if total_count is not None:
                        category.resource_count = total_count
                    if not items:
                        break
                    stats.pages += 1
                    category.last_synced_page = page_index + 1

                    for item in items:
                        detail: dict[str, Any] = {}
                        if options.include_detail and item.get("detail_url"):
                            try:
                                detail_response = self._fetch(client, item["detail_url"])
                                detail = _parse_detail(detail_response.text, item["detail_url"], config)
                            except Exception as exc:
                                errors += 1
                                category.last_sync_error = str(exc)
                            _delay(SPC_DETAIL_DELAY_SECONDS)

                        standard_no = detail.get("standard_no") or item.get("standard_no")
                        source_status = detail.get("source_status") or item.get("source_status")
                        summary = detail.get("summary") or f"SPC分类：{config.category_name}\n详情页：{item.get('detail_url') or ''}"
                        detail_hash = detail.get("detail_hash") or _detail_hash(item)
                        resource, created = _upsert_resource(
                            db,
                            source,
                            str(item["source_item_id"]),
                            {
                                "standard_no": standard_no,
                                "source_status_raw": source_status,
                                "standard_name": detail.get("standard_name") or item.get("standard_name") or standard_no or str(item["source_item_id"]),
                                "resource_type": config.resource_type,
                                "source_status": source_status,
                                "system_status": _system_status(source_status),
                                "publish_date": detail.get("publish_date") or item.get("publish_date"),
                                "effective_date": detail.get("effective_date") or item.get("effective_date"),
                                "chief_editor_unit": _limit(detail.get("chief_editor_unit"), 500),
                                "summary": summary,
                                "keywords": detail.get("keywords"),
                                "source_category_path": config.category_path,
                                "detail_url": item.get("detail_url"),
                                "pdf_trial_url": detail.get("online_reading_url") if detail.get("online_reading_enabled") else None,
                                "detail_hash": detail_hash,
                            },
                            evidence_summary=summary,
                        )
                        if detail:
                            db.flush()
                            standard_details = (
                                db.query(models.StandardDetail)
                                .filter(models.StandardDetail.standard_resource_id == resource.id)
                                .all()
                            )
                            if not standard_details:
                                standard_details = [models.StandardDetail(standard_resource_id=resource.id)]
                                for standard_detail in standard_details:
                                    db.add(standard_detail)
                            for standard_detail in standard_details:
                                db.add(standard_detail)
                                standard_detail.catalog_text = detail.get("catalog_text")
                                standard_detail.mandatory_provisions = detail.get("mandatory_provisions")
                                standard_detail.change_info = detail.get("change_info")
                                standard_detail.product_info = detail.get("product_info")
                        evidence_note = (
                            "SPC详情页入库；发现官方在线阅读入口，阅读流需会员登录态和一次性token。"
                            if detail.get("online_reading_enabled")
                            else "SPC列表/详情页入库。"
                        )
                        exists = (
                            db.query(models.StandardEvidence)
                            .filter(
                                models.StandardEvidence.standard_resource_id == resource.id,
                                models.StandardEvidence.page_html_hash == detail_hash,
                                models.StandardEvidence.evidence_note == evidence_note,
                            )
                            .first()
                        )
                        if exists is None:
                            db.add(
                                models.StandardEvidence(
                                    standard_resource_id=resource.id,
                                    source_name=source.source_name,
                                    source_level=source.trust_level,
                                    source_url=item.get("detail_url"),
                                    raw_status_text=source_status,
                                    parsed_status=resource.system_status,
                                    page_summary=summary,
                                    page_html_hash=detail_hash,
                                    evidence_note=evidence_note,
                                )
                            )
                        stats.created += 1 if created else 0
                        stats.updated += 0 if created else 1
                        stats.items += 1
                        if not SPC_FAST_METADATA_ONLY:
                            calibration = calibrate_resource_status(db, resource)
                            stats.matches += calibration["matches"]
                            stats.sync_logs += calibration["sync_logs"]
                            stats.alerts += calibration["alerts"]
                            stats.linked_change_logs += attach_change_logs_to_documents(db, resource)
                    db.commit()
                    _delay(SPC_PAGE_DELAY_SECONDS)

                stored_count = db.query(models.StandardResource).filter(models.StandardResource.source_id == source.id).count()
                if category.resource_count is None:
                    category.resource_count = stored_count
                category.last_sync_finished_at = _now()
                category.last_synced_at = category.last_sync_finished_at
                if errors:
                    category.sync_status = "同步失败" if stats.items == 0 else "待同步"
                else:
                    total_pages = None
                    if category.resource_count:
                        total_pages = max(1, (category.resource_count + 9) // 10)
                    category.sync_status = "已同步" if total_pages and (category.last_synced_page or 0) >= total_pages else "待同步"
                stats.errors += errors
                db.commit()
        return stats


registry.register(SpcOnlineAdapter())
