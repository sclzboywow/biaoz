from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class StandardNumberParts:
    raw: str | None
    normalized: str | None
    prefix: str | None
    main_no: str | None
    year: str | None
    revision_note: str | None


DASH_TRANSLATION = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\uff0d": "-",
        "\u2212": "-",
    }
)

PREFIX_PATTERN = re.compile(
    r"^(GB/T|GB/Z|GB|JGJ/T|JGJ|CJJ/T|CJJ|CECS|DB\d{0,2}/T|DB\d{0,2}|T/[A-Z0-9]+|[A-Z]{2,8}/T|[A-Z]{2,8})"
)

STANDARD_NO_IN_TEXT_PATTERN = re.compile(
    r"(?:"
    r"GB/T|GB/Z|JGJ/T|CJJ/T|DB\d{0,2}/T|"
    r"T/[A-Z0-9]+|[A-Z]{2,8}/T|"
    r"GB|JGJ|CJJ|CECS|DB\d{0,2}|[A-Z]{2,8}"
    r")"
    r"[\s\-_.]*\d[\d\.]*[\s\-_.]*\d{4}[A-Za-z]*",
    re.I,
)

DRAWING_CODE_PATTERN = re.compile(r"\d{2}S\d{3}", re.I)
ATLAS_CODE_PATTERN = re.compile(r"\d{2}[A-Z]\d{2,4}", re.I)


def _extract_revision_note(raw: str) -> tuple[str, str | None]:
    match = re.search(r"(\(.+?\)|\uff08.+?\uff09)", raw)
    if not match:
        return raw, None
    return raw[: match.start()] + raw[match.end() :], match.group(1).strip()


def normalize_standard_no(value: str | None) -> StandardNumberParts:
    if value is None:
        return StandardNumberParts(None, None, None, None, None, None)

    raw = value.strip()
    if not raw:
        return StandardNumberParts(raw, None, None, None, None, None)

    raw = re.sub(r"[\u200b-\u200f\ufeff\x00-\x1f\x7f-\x9f]", "", raw)
    raw = re.sub(r"^\?+(?=[\u4e00-\u9fff])", "", raw)
    raw = re.sub(r"\?+(?=号)", "", raw)
    without_note, revision_note = _extract_revision_note(raw)
    compact = without_note.upper().translate(DASH_TRANSLATION)
    compact = re.sub(r"\s+", "", compact)
    compact = compact.strip(":-：;；,，")
    if not compact:
        return StandardNumberParts(raw, None, None, None, None, revision_note)

    prefix_match = PREFIX_PATTERN.match(compact)
    if not prefix_match:
        return StandardNumberParts(raw, compact, None, None, None, revision_note)

    prefix = prefix_match.group(1)
    remainder = compact[prefix_match.end() :].strip(" -")
    if not remainder:
        return StandardNumberParts(raw, prefix, prefix, None, None, revision_note)

    year = None
    main_no = remainder
    year_match = re.match(r"^(.+)-(\d{4})(?:[A-Z]*)?$", remainder)
    if year_match:
        main_no = year_match.group(1)
        year = year_match.group(2)

    normalized = f"{prefix} {main_no}"
    if year:
        normalized = f"{normalized}-{year}"

    return StandardNumberParts(raw, normalized, prefix, main_no, year, revision_note)


def canonicalize_standard_no_text(text: str) -> str:
    """Normalize common filename variants before standard-number extraction."""
    value = text.translate(DASH_TRANSLATION).replace("／", "/")
    value = re.sub(r"(?<![A-Za-z0-9])GBT(?=\d)", "GB/T ", value, flags=re.I)
    value = re.sub(r"(?<![A-Za-z0-9])GBZ(?=\d)", "GB/Z ", value, flags=re.I)
    value = re.sub(r"(?<![A-Za-z0-9])JGJT(?=\d)", "JGJ/T ", value, flags=re.I)
    value = re.sub(r"(?<![A-Za-z0-9])CJJT(?=\d)", "CJJ/T ", value, flags=re.I)
    value = re.sub(r"(?i)(?<![A-Za-z0-9])GB[\s\-_]*T(?=[\s\-_.\d])", "GB/T ", value)
    value = re.sub(r"(?i)(?<![A-Za-z0-9])GB[\s\-_]*Z(?=[\s\-_.\d])", "GB/Z ", value)
    value = re.sub(r"(?i)(?<![A-Za-z0-9])JGJ[\s\-_]*T(?=[\s\-_.\d])", "JGJ/T ", value)
    value = re.sub(r"(?i)(?<![A-Za-z0-9])CJJ[\s\-_]*T(?=[\s\-_.\d])", "CJJ/T ", value)
    value = re.sub(r"(?i)(?<![A-Za-z0-9])(DB\d{0,2})[\s\-_]*T(?=[\s\-_.\d])", r"\1/T ", value)
    value = re.sub(r"(?i)(?<![A-Za-z0-9])(DB\d{0,2})T(?=\d)", r"\1/T ", value)
    return value


def extract_atlas_code_from_text(text: str | None) -> str | None:
    if not text:
        return None
    canonical = canonicalize_standard_no_text(text).upper()
    for pattern in (DRAWING_CODE_PATTERN, ATLAS_CODE_PATTERN):
        match = pattern.search(canonical)
        if match:
            return match.group(0).upper()
    return None


def extract_standard_no_from_text(text: str | None) -> str | None:
    if not text:
        return None
    canonical = canonicalize_standard_no_text(text)
    match = STANDARD_NO_IN_TEXT_PATTERN.search(canonical)
    if match:
        return re.sub(r"\s+", " ", match.group(0)).strip()
    return extract_atlas_code_from_text(canonical)
