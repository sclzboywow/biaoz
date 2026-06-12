#!/usr/bin/env python3
"""Probe batch-2 trusted sources and write recon markdown docs."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]
if not (ROOT / "backend").exists() and (BACKEND / "app").exists():
    ROOT = BACKEND.parent
DOCS = Path(os.getenv("BATCH2_RECON_DOCS", str(ROOT / "docs" / "batch2-source-recon")))

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/json,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


@dataclass(frozen=True)
class SourceProbe:
    adapter_key: str
    name: str
    base_url: str
    probe_urls: tuple[str, ...]
    notes: str = ""


SOURCES = (
    SourceProbe(
        "mot_transport_standard_public",
        "交通运输标准化信息系统",
        "https://jtst.mot.gov.cn",
        (
            "https://jtst.mot.gov.cn/",
            "https://jtst.mot.gov.cn/search/std",
            "https://jtst.mot.gov.cn/search/std?q=JTG",
        ),
        "JT/JTG 标准库；优先 JSON 列表，降级 HTML 搜索页。",
    ),
    SourceProbe(
        "mwr_water_standard_public",
        "水利部水利技术标准查询系统",
        "http://gjkj.mwr.gov.cn/jsjd1/bzh/bzhfbgg/index.htm",
        (
            "http://gjkj.mwr.gov.cn/jsjd1/bzh/bzhfbgg/index.htm",
            "https://gjkj.mwr.gov.cn/",
        ),
        "SL/SL/T；HTML 列表 + 详情页。",
    ),
    SourceProbe(
        "cnca_rb_standard_public",
        "认证认可标准化信息服务平台",
        "https://rbtest.cnca.cn/portal/xxcx/std",
        ("https://rbtest.cnca.cn/portal/xxcx/std",),
        "RB/T 标准查询；SUI 前端，探测内嵌 API。",
    ),
    SourceProbe(
        "miit_standard_public",
        "工业和信息化标准信息服务平台",
        "https://std.miit.gov.cn",
        ("https://std.miit.gov.cn/", "https://std.miit.gov.cn/std/list"),
        "增强型：计划/公示/报批/复审。",
    ),
    SourceProbe(
        "nea_energy_announcement_public",
        "国家能源局能源标准",
        "https://www.nea.gov.cn/ztzl/nybz/bzgl/index.htm",
        ("https://www.nea.gov.cn/ztzl/nybz/bzgl/index.htm",),
        "公告型：计划/目录/废止。",
    ),
    SourceProbe(
        "nrs_natural_resource_standard_public",
        "自然资源标准化信息服务平台",
        "https://www.nrsis.org.cn/",
        ("https://www.nrsis.org.cn/", "http://www.nrsis.org.cn/"),
        "TD/CH 标准公开。",
    ),
    SourceProbe(
        "mem_fire_rescue_announcement_public",
        "国家消防救援局",
        "https://www.119.gov.cn/",
        ("https://www.119.gov.cn/",),
        "政策/征求意见公告。",
    ),
    SourceProbe(
        "mem_emergency_announcement_public",
        "应急管理部",
        "https://www.mem.gov.cn/",
        ("https://www.mem.gov.cn/",),
        "安全生产/危化/征求意见。",
    ),
    SourceProbe(
        "cnca_certification_portal_public",
        "全国认证认可信息公共服务平台",
        "https://cx.cnca.cn/",
        ("https://cx.cnca.cn/",),
        "资质/证书数据，独立 certification_records 表。",
    ),
)


def _probe_url(client: httpx.Client, url: str) -> dict:
    result: dict = {"url": url, "ok": False}
    try:
        response = client.get(url, timeout=25)
        result["status_code"] = response.status_code
        result["content_type"] = response.headers.get("content-type", "")
        result["bytes"] = len(response.content)
        result["ok"] = response.status_code < 400
        text = response.text[:120_000]
        if "application/json" in result["content_type"]:
            try:
                result["json_keys"] = list(response.json().keys())[:20]
            except ValueError:
                result["json_error"] = True
        else:
            soup = BeautifulSoup(text, "html.parser")
            result["title"] = (soup.title.string or "").strip() if soup.title else ""
            result["link_count"] = len(soup.find_all("a", href=True))
            result["table_count"] = len(soup.find_all("table"))
            api_hints = sorted(
                {
                    match
                    for match in re.findall(r'["\'](/[^"\']{4,100})["\']', text)
                    if any(token in match.lower() for token in ("std", "query", "list", "search", "portal", "api"))
                }
            )[:25]
            if api_hints:
                result["api_path_hints"] = api_hints
    except Exception as exc:
        result["error"] = repr(exc)[:500]
    return result


def _write_doc(source: SourceProbe, probes: list[dict]) -> Path:
    DOCS.mkdir(parents=True, exist_ok=True)
    path = DOCS / f"{source.adapter_key}.md"
    lines = [
        f"# {source.name}",
        "",
        f"- adapter_key: `{source.adapter_key}`",
        f"- base_url: {source.base_url}",
        f"- notes: {source.notes}",
        "",
        "## Probe results",
        "",
        "```json",
        json.dumps(probes, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Implementation strategy",
        "",
        "- Phase 1: read-only list/detail sync into `standard_resources` (or `certification_records` for cx).",
        "- Phase 2: `LocalIndexSearchAdapterMixin.search` + optional `search_external`.",
        "- Default `enabled=false` until validated.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    written: list[str] = []
    with httpx.Client(headers=DEFAULT_HEADERS, follow_redirects=True) as client:
        for source in SOURCES:
            probes = [_probe_url(client, url) for url in source.probe_urls]
            path = _write_doc(source, probes)
            written.append(str(path))
            print(source.adapter_key, "probes", len(probes), "doc", path)
    print("recon_batch2_summary", json.dumps({"written": written}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
