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

# 全国标准信息公共服务平台收录的行业标准代号（2 位字母）
INDUSTRY_STANDARD_CODES = (
    "AQ BB CB CH CJ CY DA DB DZ DL DY EJ FZ GA GC GF GH GM GY "
    "HB HG HJ HS HY JB JC JG JR JS JT JY KA LB LD LS LY MH MR MT MZ "
    "NB NY QB QC QJ QX RB RF SB SC SF SH SJ SL SN SW SY TB TD TY "
    "WB WH WJ WM WS WW XB XF YB YC YD YJ YS YY YZ ZY"
).split()

# 工程建设协会标准、建工行业标准等扩展代号
EXTRA_STANDARD_CODES = (
    "CECS JJF JJG JTS GJB "
    "JGJ CJJ HGJ "
    "JTG JT/T JTG/T "
    "RB/T SL/T NB/T DL/T"
).split()

INDUSTRY_CODES_PATTERN = "|".join(
    sorted({code.upper() for code in (*INDUSTRY_STANDARD_CODES, *EXTRA_STANDARD_CODES)}, key=len, reverse=True)
)

# 团体标准 T/社会团体代号、企业标准 Q/企业代号
ORG_STANDARD_PREFIX = rf"(?:T|Q)/[A-Z][A-Z0-9]{{1,14}}"

# 标准代号（规范化用，可接受已截出的编号）
STANDARD_PREFIX_ALTS = (
    r"GB/T|GB/Z|GB|"
    r"JGJ/T|JGJ|CJJ/T|CJJ|HGJ/T|HGJ|"
    r"JTG/T|JTG|JT/T|"
    r"RB/T|SL/T|NB/T|DL/T|"
    r"DB\d{2}/T|DB\d{2}|"
    rf"{ORG_STANDARD_PREFIX}|"
    r"JJF|JJG|CECS|"
    r"T/[A-Z0-9]+|"
    r"[A-Z]{2,8}/T|"
    rf"{INDUSTRY_CODES_PATTERN}|"
    r"[A-Z]{2,8}"
)

# 自由文本提取：仅允许白名单双字母行标，避免从图集号中截出 CG60 等片段
STANDARD_PREFIX_IN_TEXT = (
    r"GB/T|GB/Z|GB|"
    r"JGJ/T|JGJ|CJJ/T|CJJ|HGJ/T|HGJ|"
    r"JTG/T|JTG|JT/T|"
    r"RB/T|SL/T|NB/T|DL/T|"
    r"DB\d{2}/T|DB\d{2}|"
    rf"{ORG_STANDARD_PREFIX}|"
    r"JJF|JJG|CECS|"
    r"T/[A-Z][A-Z0-9]{1,14}|"
    r"[A-Z]{2,8}/T|"
    rf"{INDUSTRY_CODES_PATTERN}"
)

PREFIX_PATTERN = re.compile(rf"^({STANDARD_PREFIX_ALTS})")

STANDARD_NO_IN_TEXT_PATTERN = re.compile(
    rf"(?<![A-Z0-9/])(?:{STANDARD_PREFIX_IN_TEXT})"
    r"[\s\-_.]*\d[\d\.]*"
    r"(?:[\s\-_.]*\d{4}[A-Za-z]*)?",
    re.I,
)

# 采标双编号：GB/T 20000-2016/ISO 9001:2015
ADOPTED_STANDARD_PATTERN = re.compile(
    rf"(?<![A-Z0-9/])(?:{STANDARD_PREFIX_IN_TEXT})"
    r"[\s\-_.]*\d[\d\.]*[\s\-_.]*\d{4}"
    r"/(?:ISO|IEC|EN|DIN|ASTM)\s*[\s\-_.]*\d[\d\.\-]*(?::\d{4})?",
    re.I,
)

# 国际标准：ISO 9001:2015、IEC 61508-2010、ASTM D1234
INTL_STANDARD_PATTERN = re.compile(
    r"(?<![A-Z0-9])(?:ISO|IEC|EN|DIN|ASTM|JIS|BS|ANSI|API|ASME)"
    r"[\s\-_/]*[A-Z]?\s*\d[\d\.\-]*(?:\s*:\s*\d{4})?",
    re.I,
)

# 国家建筑标准设计图集：03G101-1、23CG60、02SS405-1
NATIONAL_ATLAS_PATTERN = re.compile(
    r"(?<![A-Z0-9])"
    r"\d{2}"
    r"(?:[CS][A-Z]|[A-Z])"
    r"\d{2,4}"
    r"(?:-\d+)?"
    r"(?![A-Z0-9/])",
    re.I,
)

# 双专业字母图集：05SJ806、02SS405（无 C/S 前缀时）
NATIONAL_MULTI_PROF_ATLAS_PATTERN = re.compile(
    r"(?<![A-Z0-9])"
    r"\d{2}"
    r"[A-Z]{2}"
    r"\d{2,4}"
    r"(?:-\d+)?"
    r"(?![A-Z0-9/])",
    re.I,
)

# 给排水等专项图集：04S520
DRAWING_CODE_PATTERN = re.compile(r"(?<![A-Z0-9])\d{2}S\d{3}(?![A-Z0-9/])", re.I)

# 建标/华北标：J16Z607
JIANBIAO_ATLAS_PATTERN = re.compile(r"(?<![A-Z0-9])[A-Z]\d{2}[A-Z]\d{2,4}(?![A-Z0-9/])", re.I)

# 建标简式：S1-23
JIANBIAO_DASH_PATTERN = re.compile(r"(?<![A-Z0-9])[A-Z]\d{1,2}-\d{2,4}(?![A-Z0-9/])", re.I)

# 地方图集（省在前）：陕02J02
PROVINCIAL_ATLAS_PATTERN = re.compile(
    r"(?<![A-Z0-9])"
    r"[\u4e00-\u9fff]{1,2}"
    r"\d{2}"
    r"[A-Z]{1,4}"
    r"\d{1,4}"
    r"(?:-\d+)?"
    r"(?![A-Z0-9/])",
    re.I,
)

# 地方图集（年在前）：97浙TJ1、2006浙J44
PROVINCIAL_YEAR_FIRST_ATLAS_PATTERN = re.compile(
    r"(?<![A-Z0-9])"
    r"(?:\d{2}|20\d{2})"
    r"[\u4e00-\u9fff]{1,2}"
    r"[A-Z]{1,4}"
    r"\d{1,4}"
    r"(?:-\d+)?"
    r"(?![A-Z0-9/])",
    re.I,
)

# 地方图集（省名在前无年）：浙G16-91、浙J4-93、浙85J801
PROVINCIAL_NAME_FIRST_ATLAS_PATTERN = re.compile(
    r"(?<![A-Z0-9])"
    r"[\u4e00-\u9fff]{1,2}"
    r"\d{0,2}"
    r"[A-Z]{1,4}"
    r"\d{1,4}"
    r"(?:-\d+)?"
    r"(?![A-Z0-9/])",
    re.I,
)

# 市级图集：2013甬SS-01、2013甬j01
CITY_ATLAS_PATTERN = re.compile(
    r"(?<![A-Z0-9])"
    r"(?:\d{2}|20\d{2})"
    r"[\u4e00-\u9fff]"
    r"[A-Z]{1,4}"
    r"[\d\-]+"
    r"(?![A-Z0-9/])",
    re.I,
)

# 地方简码：05YJ
LOCAL_ATLAS_SHORT_PATTERN = re.compile(
    r"(?<![A-Z0-9])"
    r"\d{2}"
    r"[A-Z]{2,4}"
    r"\d{0,4}"
    r"(?:-\d+)?"
    r"(?![A-Z0-9/])",
    re.I,
)

ATLAS_CODE_PATTERNS = (
    JIANBIAO_ATLAS_PATTERN,
    JIANBIAO_DASH_PATTERN,
    PROVINCIAL_YEAR_FIRST_ATLAS_PATTERN,
    CITY_ATLAS_PATTERN,
    PROVINCIAL_ATLAS_PATTERN,
    PROVINCIAL_NAME_FIRST_ATLAS_PATTERN,
    NATIONAL_MULTI_PROF_ATLAS_PATTERN,
    NATIONAL_ATLAS_PATTERN,
    DRAWING_CODE_PATTERN,
    LOCAL_ATLAS_SHORT_PATTERN,
)

CODE_TEXT_PATTERNS = (
    ADOPTED_STANDARD_PATTERN,
    STANDARD_NO_IN_TEXT_PATTERN,
    INTL_STANDARD_PATTERN,
    *ATLAS_CODE_PATTERNS,
)


def _extract_revision_note(raw: str) -> tuple[str, str | None]:
    match = re.search(r"(\(.+?\)|\uff08.+?\uff09)", raw)
    if not match:
        return raw, None
    return raw[: match.start()] + raw[match.end() :], match.group(1).strip()


def normalize_atlas_code(value: str | None) -> str | None:
    if not value:
        return None
    compact = value.upper().translate(DASH_TRANSLATION)
    compact = re.sub(r"\s+", "", compact)
    compact = compact.strip(":-：;；,，")
    return compact or None


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

    if re.match(r"^[\u4e00-\u9fff]", compact):
        atlas = normalize_atlas_code(compact)
        return StandardNumberParts(raw, atlas, None, None, None, revision_note)

    prefix_match = PREFIX_PATTERN.match(compact)
    if not prefix_match:
        atlas = normalize_atlas_code(compact)
        return StandardNumberParts(raw, atlas, None, None, None, revision_note)

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

    if "/" in prefix and len(prefix) <= 18:
        if year and "-" not in main_no:
            normalized = f"{prefix} {main_no}-{year}"
        else:
            normalized = f"{prefix} {remainder}".strip()
    else:
        normalized = f"{prefix} {main_no}"
        if year:
            normalized = f"{normalized}-{year}"

    return StandardNumberParts(raw, normalized, prefix, main_no, year, revision_note)


def canonicalize_atlas_code_text(text: str) -> str:
    """Collapse common atlas filename variants before atlas extraction."""
    value = text.translate(DASH_TRANSLATION)
    value = re.sub(r"(\d{2}|20\d{2})\s*([\u4e00-\u9fff]{1,2})\s*([A-Z]{1,4})\s*(\d{1,4})", r"\1\2\3\4", value, flags=re.I)
    value = re.sub(r"([\u4e00-\u9fff]{1,2})\s*(\d{2})\s*([A-Z]{1,4})\s*(\d{1,4})", r"\1\2\3\4", value, flags=re.I)
    value = re.sub(
        r"(?<![A-Z0-9])(\d{2})\s*-\s*([CS][A-Z]|[A-Z]{1,2})\s*-\s*(\d{2,4})(?:\s*-\s*(\d+))?",
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{f'-{m.group(4)}' if m.group(4) else ''}",
        value,
        flags=re.I,
    )
    value = re.sub(
        r"(?<![A-Z0-9])(\d{2})\s*([CS][A-Z])\s*(\d{2,4})(?:\s*-\s*(\d+))?",
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{f'-{m.group(4)}' if m.group(4) else ''}",
        value,
        flags=re.I,
    )
    value = re.sub(
        r"(?<![A-Z0-9])(\d{2})\s*([CS])?\s*([A-Z])\s*(\d{2,4})(?:\s*-\s*(\d+))?",
        lambda m: f"{m.group(1)}{m.group(2) or ''}{m.group(3)}{m.group(4)}{f'-{m.group(5)}' if m.group(5) else ''}",
        value,
        flags=re.I,
    )
    value = re.sub(r"(\d{2})\s+S\s+(\d{3})", r"\1S\2", value, flags=re.I)
    return value


def _prefix_tq_slash(value: str, *, kind: str) -> str:
    """Normalize leading T/Q group/enterprise codes only; org code must start with a letter."""
    value = re.sub(
        rf"(?i)^({kind})[\s\-_]+([A-Z][A-Z0-9]{{1,14}})(?=[\s\-_.\d])",
        rf"\1/\2 ",
        value,
    )
    value = re.sub(
        rf"(?i)^({kind})([A-Z][A-Z0-9]{{1,14}})(?=\d)",
        rf"\1/\2 ",
        value,
    )
    return value


def canonicalize_standard_no_text(text: str) -> str:
    """Normalize common filename variants before standard-number extraction."""
    value = text.translate(DASH_TRANSLATION).replace("／", "/").strip()
    value = re.sub(r"(?i)^(T|Q)[\s_\-]+", r"\1/", value)
    for glued, spaced in (
        ("GBT", "GB/T "),
        ("GBZ", "GB/Z "),
        ("JGJT", "JGJ/T "),
        ("CJJT", "CJJ/T "),
        ("HGJT", "HGJ/T "),
        ("NBT", "NB/T "),
        ("DLT", "DL/T "),
        ("HJT", "HJ/T "),
        ("SHT", "SH/T "),
        ("SYT", "SY/T "),
        ("NYT", "NY/T "),
        ("HGT", "HG/T "),
        ("GAT", "GA/T "),
        ("JJFT", "JJF "),
        ("JJGT", "JJG "),
        ("TCECS", "T/CECS "),
        ("TCAMDA", "T/CAMDA "),
    ):
        value = re.sub(rf"(?<![A-Za-z0-9]){glued}(?=\d)", spaced, value, flags=re.I)
    value = re.sub(r"(?i)(?<![A-Za-z0-9])GB[\s\-_]*T(?=[\s\-_.\d])", "GB/T ", value)
    value = re.sub(r"(?i)(?<![A-Za-z0-9])GB[\s\-_]*Z(?=[\s\-_.\d])", "GB/Z ", value)
    value = re.sub(r"(?i)(?<![A-Za-z0-9])JGJ[\s\-_]*T(?=[\s\-_.\d])", "JGJ/T ", value)
    value = re.sub(r"(?i)(?<![A-Za-z0-9])CJJ[\s\-_]*T(?=[\s\-_.\d])", "CJJ/T ", value)
    value = re.sub(r"(?i)(?<![A-Za-z0-9])HGJ[\s\-_]*T(?=[\s\-_.\d])", "HGJ/T ", value)
    value = re.sub(r"(?i)(?<![A-Za-z0-9])(DB\d{2})[\s\-_]*T(?=[\s\-_.\d])", r"\1/T ", value)
    value = re.sub(r"(?i)(?<![A-Za-z0-9])(DB\d{2})T(?=\d)", r"\1/T ", value)
    value = re.sub(
        r"(?i)(?<![A-Za-z0-9])([A-Z]{2,6})[\s\-_]*T(?=[\s\-_.\d])",
        r"\1/T ",
        value,
    )
    value = re.sub(
        r"(?i)(?<![A-Za-z0-9])([A-Z]{2,6})T(?=\d)",
        r"\1/T ",
        value,
    )
    value = _prefix_tq_slash(value, kind="T")
    value = _prefix_tq_slash(value, kind="Q")
    value = re.sub(r"(?i)\bISO[\s\-_]*(\d)", r"ISO \1", value)
    value = re.sub(r"(?i)\bIEC[\s\-_]*(\d)", r"IEC \1", value)
    value = re.sub(r"(?<=[A-Z/])\s*_+(?=\d)", " ", value)
    return canonicalize_atlas_code_text(value)


def _normalize_matched_code(match: re.Match[str], *, source_text: str) -> str:
    token = re.sub(r"\s+", " ", match.group(0)).strip()
    if re.match(rf"(?i)(?:{ORG_STANDARD_PREFIX}|T/|Q/)", token):
        return normalize_standard_no(token).normalized or token
    if re.match(r"(?i)^(?:ISO|IEC|EN|DIN|ASTM|JIS|BS|ANSI|API|ASME)", token):
        return re.sub(r"\s+", " ", token.upper().replace(" : ", ":"))
    if re.search(r"[\u4e00-\u9fff]", token) or re.match(r"(?i)^\d{2}[A-Z]", token):
        return normalize_atlas_code(token) or token
    return token


def _find_code_matches(text: str) -> list[tuple[int, str]]:
    canonical = canonicalize_standard_no_text(text)
    atlas_canonical = canonicalize_atlas_code_text(canonical)
    merged = f"{canonical}\n{atlas_canonical}"
    matches: list[tuple[int, int, str]] = []

    for pattern in CODE_TEXT_PATTERNS:
        for match in pattern.finditer(merged):
            code = _normalize_matched_code(match, source_text=merged)
            if not code:
                continue
            matches.append((match.start(), len(code), code))

    if not matches:
        return []

    matches.sort(key=lambda item: (-item[1], item[0]))
    deduped: list[tuple[int, str]] = []
    seen: set[str] = set()
    for _, _, code in sorted(matches, key=lambda item: item[0]):
        upper = code.upper()
        if upper in seen:
            continue
        seen.add(upper)
        deduped.append((_, code))
    return deduped


def _find_best_atlas_match(text: str) -> str | None:
    for _, code in _find_code_matches(text):
        if re.search(r"[\u4e00-\u9fff]", code) or re.match(r"(?i)^\d{2}[A-Z]", code) or re.match(
            r"(?i)^[A-Z]\d", code
        ):
            return code
    return None


def extract_atlas_code_from_text(text: str | None) -> str | None:
    if not text:
        return None
    return _find_best_atlas_match(text)


def extract_standard_no_from_text(text: str | None) -> str | None:
    if not text:
        return None
    matches = _find_code_matches(text)
    if not matches:
        return None
    for _, code in matches:
        if re.match(rf"(?i)(?:{STANDARD_PREFIX_IN_TEXT}|ISO|IEC|EN|DIN|ASTM)", code):
            return code
    return matches[0][1]


def extract_all_codes_from_text(text: str | None) -> list[str]:
    """Extract all standard / atlas / specification codes from free text."""
    if not text:
        return []
    return [code for _, code in _find_code_matches(text)]


_COMPOUND_NO_SPLIT = re.compile(r"[、,，;；/\s]+")


def standard_no_token_match(haystack: str | None, token: str | None) -> bool:
    """Match a single code against exact or compound numbers like 16MG02、16MG03."""
    if not haystack or not token:
        return False
    left = haystack.strip().upper()
    right = token.strip().upper()
    if not left or not right:
        return False
    if left == right:
        return True
    if right in left and re.search(rf"(?<![A-Z0-9]){re.escape(right)}(?![A-Z0-9])", left):
        return True
    for part in _COMPOUND_NO_SPLIT.split(left):
        part = part.strip("()（）[]【】")
        if part and part == right:
            return True
    return False
