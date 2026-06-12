# 水利部水利技术标准查询系统

- adapter_key: `mwr_water_standard_public`
- base_url: http://gjkj.mwr.gov.cn/jsjd1/bzh/bzhfbgg/index.htm
- notes: SL/SL/T；HTML 列表 + 详情页。

## Probe results

- 列表页 HTTP 200，HTML 表格/链接结构
- 无公开 JSON API；使用 `parse_html_list_items` 解析

## Implementation strategy

- Phase 1: 单页列表同步 + 标准号从标题提取
- Phase 2: 本地索引搜索 + 外网标题过滤
