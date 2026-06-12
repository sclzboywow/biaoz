# 国家能源局能源标准

- adapter_key: `nea_energy_announcement_public`
- base_url: https://www.nea.gov.cn/ztzl/nybz/bzgl/index.htm
- notes: 公告型：计划/目录/废止/征求意见，不抓正文。

## Probe results

- 专题栏目 HTML 列表页
- 路径：`bzgl`、`bzjh`、`bzgg`

## Implementation strategy

- 仅公告索引，不重复 NB/DL 行业标准库正文
- `is_status_authority=true` 用于废止/目录状态校准
