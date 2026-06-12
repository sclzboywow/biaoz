# 自然资源标准化信息服务平台

- adapter_key: `nrs_natural_resource_standard_public`
- base_url: https://www.nrsis.org.cn/
- notes: TD/CH 标准公开。

## Probe results

- HTTPS 偶发 SSL EOF；adapter 同时尝试 http/https
- 路径候选：`/std/stdPublicity`、`/std/stdQuery`、`/portal/std`

## Implementation strategy

- 多路径 HTML 聚合后 upsert
- Phase 2: 本地索引 + 外网过滤
