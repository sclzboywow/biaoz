# 认证认可标准化信息服务平台

- adapter_key: `cnca_rb_standard_public`
- base_url: https://rbtest.cnca.cn/portal/xxcx/std
- notes: RB/T 标准查询；SUI 前端。

## Probe results

- 页面 HTTP 200，约 18KB HTML
- 使用 jQuery/SUI；adapter 探测 `/portal/xxcx/std/list|query|page` POST 接口
- 失败时降级 HTML 列表解析

## Implementation strategy

- Phase 1: RB/T 标准资源写入 `standard_resources`
- Phase 2: `search_external` 标题/编号过滤
