from __future__ import annotations

import re

from app.standard_number import (
    canonicalize_standard_no_text,
    extract_standard_no_from_text,
    normalize_standard_no,
)
from app.storage import safe_stem, safe_upload_filename
from app.trusted_source_adapters import TrustedSourceSearchQuery

ATLAS_CODE_PATTERN = re.compile(r"\d{2}[A-Z]\d{2,4}", re.I)
DRAWING_CODE_PATTERN = re.compile(r"\d{2}S\d{3}", re.I)
TOKEN_SPLIT_PATTERN = re.compile(r"[\s_\-－—,，;；]+")
NOISE_TOKENS = {
    "scan",
    "copy",
    "v1",
    "v2",
    "final",
    "draft",
    "扫描",
    "扫描件",
    "归档",
    "水印",
    "电子版",
    "正式版",
}


def _query_key(query: TrustedSourceSearchQuery) -> tuple:
    return (
        query.standard_no or "",
        query.normalized_standard_no or "",
        query.standard_name or "",
        tuple(query.keywords or ()),
    )


def _add_query(queries: list[TrustedSourceSearchQuery], seen: set[tuple], **kwargs) -> None:
    keywords = [item.strip() for item in kwargs.pop("keywords", []) if item and str(item).strip()]
    query = TrustedSourceSearchQuery(keywords=keywords, **kwargs)
    if not (query.standard_no or query.normalized_standard_no or query.standard_name or query.keywords):
        return
    key = _query_key(query)
    if key in seen:
        return
    seen.add(key)
    queries.append(query)


def _title_tokens(text: str | None) -> list[str]:
    if not text:
        return []
    tokens: list[str] = []
    for token in TOKEN_SPLIT_PATTERN.split(text.strip()):
        value = token.strip(" .()（）[]【】")
        if len(value) < 2:
            continue
        if value.lower() in NOISE_TOKENS:
            continue
        tokens.append(value)
    return tokens


def _strip_known_codes(text: str, codes: list[str]) -> str:
    title = text
    for code in codes:
        title = re.sub(re.escape(code), " ", title, flags=re.I)
    title = re.sub(r"[\s_\-－—]+", " ", title).strip()
    return title


def build_intake_search_queries(
    *,
    original_file_name: str | None,
    extracted_standard_no: str | None = None,
    normalized_standard_no: str | None = None,
    extracted_title: str | None = None,
    max_slices: int = 8,
) -> list[TrustedSourceSearchQuery]:
    """Build multiple external-search slices from filename/title fragments."""
    queries: list[TrustedSourceSearchQuery] = []
    seen: set[tuple] = set()

    safe_name = safe_upload_filename(original_file_name)
    stem = safe_stem(safe_name)
    texts = [value for value in [extracted_standard_no, normalized_standard_no, safe_name, stem, original_file_name] if value]

    if extracted_standard_no or normalized_standard_no:
        _add_query(
            queries,
            seen,
            standard_no=extracted_standard_no,
            normalized_standard_no=normalized_standard_no,
            standard_name=extracted_title,
        )

    for text in texts:
        canonical = canonicalize_standard_no_text(text)
        standard_no = extract_standard_no_from_text(canonical)
        if not standard_no:
            continue
        parts = normalize_standard_no(standard_no)
        _add_query(
            queries,
            seen,
            standard_no=standard_no,
            normalized_standard_no=parts.normalized,
            standard_name=extracted_title or _strip_known_codes(stem, [standard_no]),
        )

    code_tokens: list[str] = []
    for text in [safe_name, stem, extracted_title or ""]:
        for pattern in (DRAWING_CODE_PATTERN, ATLAS_CODE_PATTERN):
            for match in pattern.finditer(text):
                code = match.group(0).upper()
                if code not in code_tokens:
                    code_tokens.append(code)

    clean_title = _strip_known_codes(extracted_title or stem, code_tokens)
    if clean_title:
        _add_query(queries, seen, standard_name=clean_title, keywords=_title_tokens(clean_title))

    for code in code_tokens:
        _add_query(queries, seen, keywords=[code], standard_name=clean_title or None)
        _add_query(queries, seen, standard_no=code, standard_name=clean_title or None)

    for token in _title_tokens(stem):
        if re.fullmatch(r"[A-Z0-9./-]{3,}", token, flags=re.I):
            _add_query(queries, seen, keywords=[token], standard_name=clean_title or None)
        elif re.search(r"[\u4e00-\u9fff]", token) and len(token) >= 3:
            _add_query(queries, seen, keywords=[token], standard_name=token)

    if not queries and stem:
        _add_query(queries, seen, standard_name=stem, keywords=_title_tokens(stem))

    return queries[:max_slices]
