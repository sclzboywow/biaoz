# 交通运输标准化信息系统

- adapter_key: `mot_transport_standard_public`
- base_url: https://jtst.mot.gov.cn
- notes: 列表入口 `/search/std?q=&tid=gb` 与 `/search/std?tid=jjg&q=`；实际数据页为 `/search/stdPage?tid=gb|jjg&q=&pageNo=N`

## Probe results

- `/search/std?q=&tid=gb`、`/search/std?tid=jjg&q=` → 200，为检索壳页；结果在 `stdPage` 同名参数
- `/search/stdPage?tid=gb&q=` → GB/T、JT/T 等，`a[tid][pid]` 可拼详情
- `/search/stdPage?tid=jjg&q=` → JJG(交通) 等；`BV_JJG_JT_PLAN` 为计划线索，不入正文库
- 分页：`pageNo=2` 有效；`page`/`pageNum` 无效
- 详情：`BV_GB` → `/gb/search/gbDetailed?id=`；`BV_HB` → `/hb/search/stdHBDetailed?id=`；其余默认 gbDetailed
- 正文：`BV_GB` 详情页 openpdf → openstd `hcno`；`BV_HB`/`BV_JJG_JT` → `/hb/search/stdHBView` → `/kfs/file/downloadStd/{location_s}`（需验证码）

## Implementation strategy

- Sync：按 `tid=gb` / `tid=jjg` 两路 `stdPage` + `pageNo` 拉取；解析 `tid/pid` 构造详情 URL
- 文件发现：`batch2_mot_file_discovery` 从详情页提取 openstd 或 MOT kfs 下载链
- 正式入库：openstd 走 captcha 下载；MOT kfs 当前为验证码页，自动入库会落 `manual_review`
