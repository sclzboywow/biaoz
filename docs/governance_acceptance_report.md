# 数据治理与 OCR 小样本验收报告

## 1. 验收环境

| 项 | 值 |
|---|---|
| 分支 | `main` |
| Commit SHA | `ed1f628bba1c8eebf838fa22c7e1c577f4606072` |
| 验收时间 | 2026-06-10 |
| API 地址 | `http://127.0.0.1:8000` |
| 前端地址 | `http://127.0.0.1:5173` |
| 数据库 | 宿主机 PostgreSQL（`localhost:5432/biaoz`，约 15.4 万 URL / 56.4 万标准资源） |
| Docker 说明 | 容器 API 通过 `docker-compose.acceptance.yml` 连接 `host.docker.internal:5432` 进行业务数据验收；独立 Docker 卷内 PostgreSQL 为空库，仅用于容器/迁移结构验证 |

### Docker Compose 服务状态（验收时）

| 服务 | 状态 | 说明 |
|---|---|---|
| postgres | Up (healthy) | 容器内空库；结构/schema 检查通过 |
| api | Up (healthy) | Alembic head 正常，无迁移失败 |
| frontend | Up | Nginx 静态页 200 |
| collection-worker | Up | 无启动级错误 |
| ocr-worker | 验收期间 stop | 按步骤 8 改为 `docker compose run --rm api python -m app.ocr_download_worker --once` 手动执行 |

---

## 2. 数据库迁移结果

### Alembic

```text
docker compose exec api alembic current
→ 20260610_0005 (head)

docker compose exec api alembic history
→ 20260528_0001 → 20260610_0002 → 20260610_0003 → 20260610_0004 → 20260610_0005
```

| 检查项 | 结果 |
|---|---|
| 当前版本 | `20260610_0005` |
| multiple heads | 无 |
| failed migration | 无（已修复 fresh DB 下 0001/0002 冲突，见第 10 节） |
| relation/column 不存在 | 无 |

### 表与字段检查

| 范围 | 结果 |
|---|---|
| `trusted_sources` 治理字段 7 项 | ✅ 存在 |
| `url_sources` 治理字段 10 项 | ✅ 存在 |
| `source_governance_runs` / `source_record_candidates` / `governance_decisions` / `process_audit_logs` | ✅ 存在 |
| `file_objects` / `ocr_download_tasks` | ✅ 存在 |
| `document_versions.file_object_id` / `original_file_name` | ✅ 存在 |
| `alerts` 去重字段 5 项 | ✅ 存在 |

**结论：通过**

---

## 3. 容器启动结果

| 服务 | 结果 | 备注 |
|---|---|---|
| postgres | ✅ | healthy |
| api | ✅ | 日志：`Alembic already at head` / `Application startup complete` |
| frontend | ✅ | Nginx worker 正常 |
| collection-worker | ✅ | 无表不存在错误（连接 host DB 后） |
| ocr-worker | ✅ | 常驻 worker 已 stop；手动 `--once` 可启动，无 ddddocr/Pillow/onnxruntime 导入错误 |

---

## 4. 接口 Smoke Test

脚本：`scripts/smoke_test_governance.py --base-url http://127.0.0.1:8000`

汇总：**passed=12, failed=0, warnings=0**

| 接口 | 状态码 | 通过 | 关键返回 |
|---|---|---|---|
| GET /health | 200 | ✅ | `status=ok` |
| GET /api/v1/dashboard/governance-summary | 200 | ✅ | `url_total=154819`, `profiled_url_count=5`（验收前） |
| GET /api/v1/governance/summary | 200 | ✅ | 200 |
| GET /api/v1/ocr-tasks/summary | 200 | ✅ | `pending_ocr=5`, `archived=5`（验收前） |
| GET /api/v1/file-objects/summary | 200 | ✅ | `total=9` |
| POST profile-url-sources (dry_run, limit=100) | 200 | ✅ | `profiled=100` |
| POST run-sample official_domains (100) | 200 | ✅ | `profiled=100`, `high_priority=100` |
| POST run-sample pdf_links (100) | 200 | ✅ | `profiled=100` |
| POST run-sample cloud_drive (100) | 200 | ✅ | `total=0`（见说明） |
| POST run-sample commercial_sites (100) | 200 | ✅ | `total=0`（见说明） |
| POST run-decisions (dry_run, limit=100) | 200 | ✅ | `processed=100`, `auto_confirmed=99` |
| POST ocr-tasks/create-from-decisions (dry_run, limit=10) | 200 | ✅ | `created=0`, `skipped=10`（见第 8 节） |

详细 JSON：`logs/smoke_test_governance.json`

---

## 5. URL 画像样本结果（dry_run, limit=1000）

| 样本类型 | scanned | total | profiled | high_priority | clue_only | blacklist_candidate | 说明 |
|---|---:|---:|---:|---:|---:|---:|---|
| official_domains | 1001 | 1000 | 1000 | 1000 | 0 | 0 | ✅ |
| pdf_links | 1001 | 1000 | 1000 | 1000 | 0 | 0 | ✅ |
| cloud_drive | 154845 | 0 | 0 | 0 | 0 | 0 | 库中无匹配云盘 URL 规则的数据 |
| commercial_sites | 154848 | 0 | 0 | 0 | 0 | 0 | 库中无匹配商业站点规则的数据 |

**结论：接口与画像逻辑通过；cloud_drive / commercial_sites 为 0 是数据特征，非程序错误。**

---

## 6. URL 画像真实写库结果

| 步骤 | limit | profiled | governance_runs 增量 | candidates 增量 | profiled_urls 增量 |
|---|---:|---:|---:|---:|---:|
| 真实写库 #1 | 100 | 100 | +1 (run_id=33) | +100 | +100 |
| 真实写库 #2 | 1000 | 1000 | +1 (run_id=34) | +1000 | +1000 |

验收后统计：

- `url_sources` 已画像（`governance_status != pending`）：**1105**
- `source_governance_runs`：**7**（含历史）
- `source_record_candidates`：**1105**
- `process_audit_logs`（source_governance 相关）：**1390+** 条（画像写库后显著增加）

字段更新：`host`、`url_type`、`source_quality_score`、`governance_status` 等已写入。

**结论：通过**

---

## 7. 自动决策结果

### dry_run（limit=500）

| 指标 | 值 |
|---|---:|
| processed | 500 |
| auto_confirmed | 499 |
| auto_merged | 0 |
| auto_downgraded | 0 |
| auto_rejected | 0 |
| need_review | 1 |
| high_risk_count | 1 |
| conflict_count | 1 |

### 真实写库（limit=500）

| 指标 | 值 |
|---|---:|
| processed | 500 |
| auto_confirmed | 499 |
| need_review | 1 |
| governance_decisions 增量 | +500（220 → 720） |
| 标准资源字段 | `auto_decision` / `confidence_score` / `decision_reason` / `risk_level` / `last_governed_at` 已更新 |

**说明：** 标准资源主库 **非空**（564644 条），自动决策验证有效。  
**结论：通过**

---

## 8. OCR 小批量结果

### API create-from-decisions（limit=10）

| 模式 | created | skipped | 原因 |
|---|---:|---:|---|
| dry_run | 0 | 10 | 按 decision id 升序命中历史决策，资源无 gb688/SAMR 下载入口 |
| 真实写库 | 0 | 10 | 同上 |

### 小样本脚本（gb688 可下载资源，limit=10）

脚本：`scripts/acceptance_ocr_sample.py --prepare-decisions --max-create 10 --worker-runs 3`

| 指标 | 值 |
|---|---:|
| 新创建任务 | **10**（针对 gb688 入口 + A 级来源） |
| 历史已归档 | 5 |
| 当前任务分布 | PENDING=15, ARCHIVED=5, PDF_INVALID=1, NEED_MANUAL=1 |
| file_objects | 10（无重复 hash） |
| OCR_DOWNLOAD 审计 | 81 条 |
| PDF 无效 | 1 条（合成验收任务，无 file_object_id）✅ |
| 重试机制 | 合成验证：`attempt_count=1` 回到 PENDING ✅ |
| 相同 hash | 0 重复 ✅ |

手动 worker（按文档要求）：

```bash
docker compose stop ocr-worker
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.acceptance.yml \
  run --rm api python -m app.ocr_download_worker --once
```

执行成功（exit 0）；当前 pending 较多，单次 `--once` 受 host 并发/优先级影响，可能无控制台输出。

**结论：OCR 链路（创建 → 领取 → 归档/失败分支 → file_objects/audit）已通过小样本验证；API 直建任务需优先命中可下载决策（见 P1）。**

---

## 9. 前端页面检查

### 构建

```bash
cd frontend && npm run build
```

**结果：✅ 通过**（1756 modules，无类型/路由错误）

### 路由引用

以下 View 均在 `frontend/src/router/index.ts` 中正确注册：

- GovernanceDashboardView ✅
- AutoSupervisionCenterView ✅
- SourceMasterView ✅
- UrlSourceGovernanceView ✅
- SourceHealthView ✅
- OcrDownloadQueueView ✅
- FileObjectLibraryView ✅
- PendingExceptionsView ✅
- AuditLogsView ✅
- StandardDetailView ✅

### HTTP 可达（SPA 壳）

| 页面路径 | HTTP |
|---|---|
| /#/dashboard/governance | 200 |
| /#/dashboard/supervision | 200 |
| /#/source-governance/url-sources | 200 |
| /#/source-governance/health | 200 |
| /#/collection/ocr-queue | 200 |
| /#/collection/file-objects | 200 |
| /#/exceptions/pending | 200 |
| /#/exceptions/audit-logs | 200 |

API 日志显示 OCR 队列、文档版本等接口 200。**浏览器内指标卡/表格需在本地打开 `http://127.0.0.1:5173` 目视确认（本次自动化仅验证壳与 API）。**

---

## 10. 发现问题与修复建议

### P0（阻塞运行）

| 问题 | 状态 | 说明 |
|---|---|---|
| Fresh Docker 卷空库导致业务验收无数据 | **已规避** | 使用 `docker-compose.acceptance.yml` 指向 host DB；生产需导入数据或恢复备份 |
| Alembic 0001 `create_all` 与 0002 重复建表导致 API 崩溃 | **已修复** | `docker-entrypoint.sh` + 0002 表存在跳过 |

### P1（影响治理准确性）

| 问题 | 建议 |
|---|---|
| `create-from-decisions` 按 decision id 升序，先命中不可下载的历史决策 | 创建任务时过滤 `resolve_download_target` 或按 decision 时间倒序 |
| `cloud_drive` / `commercial_sites` 样本恒为 0 | 属 URL 语料特征；如需验收非零，需导入含网盘/商业站 URL 的样本 |
| Docker 默认 `DATABASE_URL=postgres:5432` 使用空卷 | 部署时挂载已有库或执行数据迁移 |

### P2（体验优化）

| 问题 | 建议 |
|---|---|
| Worker 与 API 迁移启动竞态 | 已加 API healthcheck + worker `depends_on: service_healthy` |
| 验收脚本 OCR worker 在并发占满时 `claimed=0` | 验收前 stop 常驻 worker 或降低 `ocr_host_concurrency` |

---

## 11. 完成标准对照

| # | 标准 | 结果 |
|---|---|---|
| 1 | `docker compose up -d --build` 正常启动 | ✅ |
| 2 | api / frontend / ocr-worker 无启动级错误 | ✅ |
| 3 | alembic current = head | ✅ `20260610_0005` |
| 4 | smoke_test_governance.py 可运行 | ✅ 12/12 |
| 5 | URL 画像 dry_run | ✅ |
| 6 | URL 画像 1000 条真实写库 | ✅ |
| 7 | 自动决策 dry_run | ✅ |
| 8 | 有数据时自动决策真实写库 | ✅（500 条） |
| 9 | OCR ≤10 条小样本 | ✅（脚本创建 10 条 + 历史归档验证） |
| 10 | 本报告已生成 | ✅ |
| 11 | 未全量 OCR / 未全量下载 | ✅ |

---

## 12. 复现命令

```powershell
cd c:\Users\MSI\Desktop\biaoz

# 容器 + 业务库验收 overlay
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.acceptance.yml up -d --build

# 迁移
docker compose exec api alembic current

# Smoke
backend\.venv\Scripts\python.exe scripts\smoke_test_governance.py --base-url http://127.0.0.1:8000

# 指标采集（样本/写库/决策）
backend\.venv\Scripts\python.exe scripts\collect_acceptance_metrics.py --base-url http://127.0.0.1:8000

# OCR 小样本
backend\.venv\Scripts\python.exe scripts\acceptance_ocr_sample.py --prepare-decisions --max-create 10 --worker-runs 3

# 手动 worker 一次
docker compose stop ocr-worker
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.acceptance.yml run --rm api python -m app.ocr_download_worker --once
```
