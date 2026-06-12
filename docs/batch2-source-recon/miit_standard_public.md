# 工业和信息化标准信息服务平台

- adapter_key: `miit_standard_public`
- base_url: https://std.miit.gov.cn（列表数据来自 www.miit.gov.cn 政策搜索）
- notes: 增强型：计划/公示/报批/复审/TC，不全量正文

## Probe results

- `std.miit.gov.cn` SPA 内 API（如 `queryPublicityByPage`）→ `code:10005` 需登录
- **可用**：`GET https://www.miit.gov.cn/search-front-server/api/search/info`
  - 参数：`websiteid=110000000000000&pg=10&p={page}&tpl=14&category=18&q={关键词}`
  - 推荐关键词：`行业标准`、`报批`、`标准公告`、`征求意见`
- 降级：`www.miit.gov.cn/`、`/zwgk/index.html` HTML 解析

## Implementation strategy

- 公告型 adapter：写入 `resource_type=标准公告/征求意见/标准计划`
- 按标准号去重，变更写 `standard_change_logs`
- Default `enabled=false` until validated
