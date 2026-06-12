#!/usr/bin/env python3
from pathlib import Path

from app.local_file_intake_service import extract_local_file_metadata
from app.standard_number import extract_all_codes_from_text, extract_standard_no_from_text, normalize_standard_no
from app.storage import filesystem_safe_filename, safe_stem, safe_upload_filename

CASES = [
    # 国标 / 行标变种
    ("GB/T 1568-2008-scan-copy.pdf", "GB/T 1568-2008"),
    ("GB/T 43556.1-2023 光纤光缆.pdf", "GB/T 43556.1-2023"),
    ("扫描件_归档_GBT43556.1-2023_v2(水印).pdf", "GB/T 43556.1-2023"),
    ("GB-T43556.1-2023_v2.pdf", "GB/T 43556.1-2023"),
    ("GB T 1568-2008 扫描版.pdf", "GB/T 1568-2008"),
    ("GB50016-2014 建筑设计防火规范.pdf", "GB50016-2014"),
    ("NBT10421-2020 低压配网.pdf", "NB/T 10421-2020"),
    ("DLT5023-2005 电力建设.pdf", "DL/T 5023-2005"),
    ("WS T 877-2026 卫生标准.pdf", "WS/T 877-2026"),
    ("YYT 10001-2026 医药标准.pdf", "YY/T 10001-2026"),
    ("CJ 14-2016 城镇建设标准.pdf", "CJ 14-2016"),
    # 地标 / 团标 / 企标
    ("DB11T 1234-2020 北京地标.pdf", "DB11/T 1234-2020"),
    ("T_CECS 101-2021 协会标准.pdf", "T/CECS 101-2021"),
    ("TCECS101-2021.pdf", "T/CECS 101-2021"),
    ("T/CAMDA 001-2016 团体标准.pdf", "T/CAMDA 001-2016"),
    ("Q_ABC 1234-2020 企业标准.pdf", "Q/ABC 1234-2020"),
    # 采标 / 国际标准
    ("GB/T 20000-2016_ISO9001-2015.pdf", "GB/T 20000-2016/ISO 9001"),
    ("ISO9001-2015 质量管理体系.pdf", "ISO 9001"),
    ("IEC61508-2010 功能安全.pdf", "IEC 61508"),
    # 国家图集
    ("04S520 埋地塑料排水管道施工.pdf", "04S520"),
    ("23CG60预制桩桩顶机械连接螺丝紧固式.pdf", "23CG60"),
    ("23-CG-60 预制桩.pdf", "23CG60"),
    ("03G101-1 混凝土结构平法图集.pdf", "03G101-1"),
    ("05SJ806 民用建筑互提资料深度图样.pdf", "05SJ806"),
    ("02SS405-1 装配式管道吊挂支架.pdf", "02SS405-1"),
    # 建标 / 地方图集
    ("J16Z607 混凝土结构加固图集.pdf", "J16Z607"),
    ("S1-23 华北标图集.pdf", "S1-23"),
    ("陕02J02 陕西省建筑标准图集.pdf", "陕02J02"),
    ("97浙TJ1 防盗安全门.pdf", "97浙TJ1"),
    ("2006浙J44 排气道.pdf", "2006浙J44"),
    ("浙G16-91 混凝土小型空心砌块.pdf", "浙G16-91"),
    ("2013甬SS-01 蒸压加气砼砌块.pdf", "2013甬SS-01"),
    ("05YJ 河南建筑标准图集.pdf", "05YJ"),
    # 无编号
    ("会议纪要_2024年内部讨论稿.pdf", None),
]

print("=== extraction ===")
failed = 0
for name, expected in CASES:
    safe = safe_upload_filename(name)
    raw = extract_standard_no_from_text(safe_stem(safe)) or extract_standard_no_from_text(safe)
    all_codes = extract_all_codes_from_text(safe)
    ok = expected is None and raw is None
    if expected is not None:
        ok = raw == expected or expected in all_codes or (raw and expected.split()[0] in raw)
    if not ok:
        failed += 1
        status = "FAIL"
    else:
        status = "ok"
    print(f"[{status}] {name}\n  raw={raw} expected={expected} all={all_codes}\n")

if failed:
    raise SystemExit(f"{failed} extraction case(s) failed")
print(f"all {len(CASES)} cases passed")
