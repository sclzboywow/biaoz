# 全国认证认可信息公共服务平台

- adapter_key: `cnca_certification_portal_public`
- base_url: https://www.cnca.gov.cn（主站；cx.cnca.cn 常 521）
- notes: 资质/证书数据，独立 `certification_records` 表

## Probe results

- `https://cx.cnca.cn/` → HTTP 521，不可用
- **可用**：
  - `https://www.cnca.gov.cn/zwxx/gg/index.html`（公告，130+ 链接）
  - `https://www.cnca.gov.cn/zwxx/tz/index.html`（通知，140+ 链接）
  - `http://rzjg.cnca.cn/jgsp/base/tBaNotice/publicResultLists`（认证机构审批公示，表格结构可用，当前可能 0 条）
- adapter 多 URL 回退，521/失败时跳过 cx 主站

## Implementation strategy

- **不写** `standard_resources`，仅写 `certification_records`
- API: `GET /api/v1/certification-records/page`
- Default `enabled=false` until validated
