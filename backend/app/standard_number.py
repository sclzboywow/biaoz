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
    r"^(GB/T|GB|JGJ/T|JGJ|CJJ/T|CJJ|CECS|DB\d{0,2}/T|DB\d{0,2}|T/[A-Z0-9]+|[A-Z]{2,8}/T|[A-Z]{2,8})"
)


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
