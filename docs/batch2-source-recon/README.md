# 第二批可信源（Batch-2）

## 正式库流水线口径

第二批源**要进正式库**，但进正式库的必须是**真实标准正文文件**（PDF/DOC/DOCX/XLS/XLSX 或官方在线阅读正文）。

公告、通知、征求意见、计划、报批、公示、目录、废止清单等材料：
- 只能做线索或 `StandardEvidence`
- **不得**创建 `DocumentVersion`

## 适配器分类

| 类型 | adapter_key | 文件策略 |
|------|-------------|----------|
| 标准正文 | `mot_transport_standard_public`, `nrs_natural_resource_standard_public`, `cnca_rb_standard_public` | 详情页发现 `official_file_url` → 校验 → 入库 |
| 公告线索 | `miit_standard_public`, `nea_energy_*`, `mem_*`, `mwr_water_standard_public` | `file_ingest_status=announcement_clue` |
| 资质索引 | `cnca_certification_portal_public` | 仅 `certification_records` |

## 状态字段（`standard_resources.file_ingest_status`）

- `announcement_clue` — 公告/公示类，不入正式库
- `file_missing` — 未在详情页找到真实正文文件
- `manual_review` — 需人工复核（下载失败、歧义链接等）
- `file_ready` — 已发现并通过元数据校验，待采集入库
- `admitted` — 已通过 admission 并写入 `Document`/`DocumentVersion`
- `evidence_only` — 有文件但未通过真实性校验，仅留证

## 流水线

1. `sync_batch2_trusted_sources.py` — 元数据同步 +（默认）详情页文件发现
2. `batch_ingest_batch2_files.py` / 决策后采集通道 `batch2_standard_body` — 下载、正文校验、正式入库
3. `batch2_admission.evaluate_batch2_file_admission` — 标准号/名称/类型/正文结构校验

实现：`backend/app/batch2_admission.py`、`batch2_file_discovery.py`、`batch2_file_ingest_service.py`
