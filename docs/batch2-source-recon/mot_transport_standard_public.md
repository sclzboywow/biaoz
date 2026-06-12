# 交通运输标准化信息系统

- adapter_key: `mot_transport_standard_public`
- base_url: https://jtst.mot.gov.cn
- notes: JT/JTG 标准库；公开列表页为 `/search/stdPage?q=`（`/search/std?page=` 返回 400）

## Probe results

- `/search/stdPage?q=` → 200，表格含 GB/T、JT/T、JTG 标准行（约 5–10 条/关键词）
- `/search/std?page=N` → 400，不可用
- 原 POST JSON 候选（`/search/std/list` 等）→ 404
- 分页参数 `page`/`pageNum` 对 stdPage 无效；adapter 按关键词轮询（空、JTG、JT/T、GB/T 等）

## Implementation strategy

- Phase 1: `parse_mot_stdpage_items` 解析 stdPage 表格 → `standard_resources`
- Phase 2: `search_external` 走 `/search/stdPage?q={keyword}`
- Default `enabled=false` until validated
