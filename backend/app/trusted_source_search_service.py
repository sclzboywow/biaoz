from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app import models
from app.standard_number import normalize_standard_no, standard_no_token_match
from app.trusted_source_adapters import TrustedSourceSearchQuery, TrustedSourceSearchResult

logger = logging.getLogger(__name__)


def _similarity(left: str | None, right: str | None) -> int:
    return int(SequenceMatcher(None, left or "", right or "").ratio() * 100)


def _resource_to_search_result(
    resource: models.StandardResource,
    *,
    query: TrustedSourceSearchQuery,
) -> TrustedSourceSearchResult:
    title_score = _similarity(query.standard_name, resource.standard_name)
    resource_no = resource.normalized_standard_no or normalize_standard_no(resource.standard_no).normalized
    number_match = bool(
        (query.normalized_standard_no and standard_no_token_match(resource_no, query.normalized_standard_no))
        or (query.standard_no and standard_no_token_match(resource.standard_no, query.standard_no))
        or (query.standard_no and standard_no_token_match(resource.normalized_standard_no, query.standard_no))
    )
    if number_match and title_score >= 80:
        score = 95
        advice = "编号与标题高度一致"
    elif number_match:
        score = 85
        advice = "标准编号一致"
    else:
        score = max(50, title_score)
        advice = f"标题相似度 {title_score}%"

    return TrustedSourceSearchResult(
        source_id=resource.source_id,
        source_name=resource.source_name or "",
        standard_no=resource.standard_no,
        normalized_standard_no=resource.normalized_standard_no or resource_no,
        standard_name=resource.standard_name,
        source_status=resource.source_status,
        publish_date=resource.publish_date,
        effective_date=resource.effective_date,
        abolish_date=resource.abolish_date,
        detail_url=resource.detail_url,
        pdf_trial_url=resource.pdf_trial_url,
        confidence_score=score,
        match_reason=f"本地可信源索引命中：{advice}",
        raw={
            "standard_resource_id": resource.id,
            "search_backend": "local_index",
            "title_similarity": title_score,
            "number_match": number_match,
        },
    )


def search_standard_resources_index(
    db: Session,
    query: TrustedSourceSearchQuery,
    *,
    source_id: int | None = None,
    limit: int = 20,
) -> list[TrustedSourceSearchResult]:
    """Search synced standard_resources rows as the phase-1 local trusted-source index."""
    filters = []
    if query.normalized_standard_no:
        token = query.normalized_standard_no.strip()
        filters.append(models.StandardResource.normalized_standard_no == token)
        filters.append(models.StandardResource.normalized_standard_no.ilike(f"%{token}%"))
    if query.standard_no:
        token = query.standard_no.strip()
        filters.append(models.StandardResource.standard_no == token)
        filters.append(models.StandardResource.standard_no.ilike(f"%{token}%"))
    if not filters and query.standard_name:
        filters.append(models.StandardResource.standard_name.ilike(f"%{query.standard_name[:40]}%"))
    if not filters and query.keywords:
        for keyword in query.keywords[:5]:
            keyword = keyword.strip()
            if not keyword:
                continue
            if re.fullmatch(r"[A-Z0-9./-]{3,}", keyword, flags=re.I):
                filters.append(models.StandardResource.standard_no.ilike(f"%{keyword}%"))
                filters.append(models.StandardResource.normalized_standard_no.ilike(f"%{keyword}%"))
            else:
                filters.append(models.StandardResource.standard_name.ilike(f"%{keyword[:40]}%"))
    if not filters:
        return []

    statement = select(models.StandardResource).where(or_(*filters))
    if source_id is not None:
        statement = statement.where(models.StandardResource.source_id == source_id)

    resources = list(
        db.scalars(
            statement.order_by(desc(models.StandardResource.updated_at), desc(models.StandardResource.id)).limit(max(1, min(limit, 100)))
        )
    )
    results = [_resource_to_search_result(resource, query=query) for resource in resources]
    results.sort(key=lambda item: item.confidence_score, reverse=True)
    return results[:limit]


def adapter_search_via_local_index(
    db: Session,
    source_id: int,
    query: TrustedSourceSearchQuery,
    *,
    limit: int = 20,
) -> list[TrustedSourceSearchResult]:
    """Default adapter search implementation backed by the local standard_resources index."""
    source = db.get(models.TrustedSource, source_id)
    if source is None or not source.enabled:
        return []
    results = search_standard_resources_index(db, query, source_id=source_id, limit=limit)
    for item in results:
        item.raw["adapter_key"] = source.adapter_key
    return results


def _external_dedupe_key(item: TrustedSourceSearchResult) -> str | None:
    external_item_id = item.raw.get("external_item_id")
    if external_item_id:
        return f"{item.source_id}:{external_item_id}"
    if item.detail_url:
        return f"{item.source_id}:{item.detail_url}"
    normalized = item.normalized_standard_no or item.standard_no
    if normalized:
        return f"{item.source_id}:{normalized}:{item.standard_name}"
    return None


def search_trusted_sources_sliced(
    db: Session,
    queries: list[TrustedSourceSearchQuery],
    *,
    source_id: int | None = None,
    include_external: bool = False,
    limit: int = 20,
    errors: list[dict[str, str | int]] | None = None,
) -> list[TrustedSourceSearchResult]:
    """Run multiple query slices and merge/deduplicate results."""
    if not queries:
        return []
    limit = max(1, min(limit, 100))
    per_slice_limit = max(3, min(limit, (limit // len(queries)) + 2))
    merged: list[TrustedSourceSearchResult] = []
    seen_local_ids: set[int] = set()
    seen_external_keys: set[str] = set()

    for query in queries:
        batch = search_trusted_sources(
            db,
            query,
            source_id=source_id,
            include_external=include_external,
            limit=per_slice_limit,
            errors=errors,
        )
        for item in batch:
            resource_id = item.raw.get("standard_resource_id")
            if resource_id is not None:
                if resource_id in seen_local_ids:
                    continue
                seen_local_ids.add(resource_id)
            external_key = _external_dedupe_key(item)
            if external_key is not None:
                if external_key in seen_external_keys:
                    continue
                seen_external_keys.add(external_key)
            merged.append(item)
            if len(merged) >= limit:
                return _sort_search_results(merged)[:limit]

    return _sort_search_results(merged)[:limit]


def search_trusted_sources(
    db: Session,
    query: TrustedSourceSearchQuery,
    *,
    source_id: int | None = None,
    include_external: bool = False,
    limit: int = 20,
    errors: list[dict[str, str | int]] | None = None,
) -> list[TrustedSourceSearchResult]:
    """Unified trusted-source search entry used by intake, review, and API."""
    limit = max(1, min(limit, 100))
    results = search_standard_resources_index(db, query, source_id=source_id, limit=limit)
    if not include_external:
        return results

    from app.trusted_source_adapters import registry

    seen_local_ids = {
        item.raw.get("standard_resource_id")
        for item in results
        if item.raw.get("standard_resource_id") is not None
    }
    seen_external_keys = {
        key
        for item in results
        if (key := _external_dedupe_key(item)) is not None
    }

    source_query = select(models.TrustedSource).where(
        models.TrustedSource.enabled.is_(True),
        models.TrustedSource.adapter_key.is_not(None),
    )
    if source_id is not None:
        source_query = source_query.where(models.TrustedSource.id == source_id)
    sources = list(db.scalars(source_query.order_by(models.TrustedSource.id)))

    for source in sources:
        if not source.adapter_key:
            continue
        adapter = registry.get(source.adapter_key)
        if adapter is None:
            continue
        search_external = getattr(adapter, "search_external", None)
        if search_external is None:
            continue
        try:
            adapter_results = search_external(db, source.id, query)
        except NotImplementedError:
            continue
        except Exception as exc:
            logger.exception(
                "external trusted-source search failed source_id=%s adapter=%s",
                source.id,
                source.adapter_key,
            )
            if errors is not None:
                errors.append(
                    {
                        "source_id": source.id,
                        "source_name": source.source_name or "",
                        "adapter_key": source.adapter_key or "",
                        "message": str(exc),
                    }
                )
            continue

        for item in adapter_results:
            item.raw.setdefault("search_backend", "external")
            item.raw.setdefault("adapter_key", source.adapter_key)
            resource_id = item.raw.get("standard_resource_id")
            if resource_id is not None and resource_id in seen_local_ids:
                continue
            external_key = _external_dedupe_key(item)
            if external_key is not None and external_key in seen_external_keys:
                continue
            if resource_id is not None:
                seen_local_ids.add(resource_id)
            if external_key is not None:
                seen_external_keys.add(external_key)
            results.append(item)
            if len(results) >= limit:
                return _sort_search_results(results)[:limit]

    return _sort_search_results(results)[:limit]


def _sort_search_results(results: list[TrustedSourceSearchResult]) -> list[TrustedSourceSearchResult]:
    return sorted(results, key=lambda item: item.confidence_score, reverse=True)


class LocalIndexSearchAdapterMixin:
    """Phase-1 adapter search backed by the local standard_resources index."""

    def search(self, db: Session, source_id: int, query: TrustedSourceSearchQuery) -> list[TrustedSourceSearchResult]:
        return adapter_search_via_local_index(db, source_id, query, limit=20)

    def search_external(self, db: Session, source_id: int, query: TrustedSourceSearchQuery) -> list[TrustedSourceSearchResult]:
        raise NotImplementedError
