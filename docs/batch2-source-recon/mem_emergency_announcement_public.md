# 应急管理部

- adapter_key: `mem_emergency_announcement_public`
- base_url: https://www.mem.gov.cn/
- notes: 安全生产/危化/标准征求意见。

## Probe results

- 栏目：`gk/tzgg`、`gk/zcjd`、`gk/yjzj`

## Implementation strategy

- 公告型同步，标准号可从标题提取
- 治理阶段预期 `NEED_REVIEW` 比例较高
