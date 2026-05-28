# 标准规范文件动态管理系统

V1.0 定位：一个会自动维护的标准规范文件库。

V1.0 只解决标准规范电子文件的自动采集、归档、版本维护、状态复核和更新提醒。不包含项目管理、项目依据绑定、项目影响分析、AI 问答和全文知识库。

## 当前功能

- URL 来源管理：新增、查询、分页、筛选、手动检查、非手动 URL 批量检查
- 文件采集管理：访问 URL、下载文件、记录失败、识别无变化
- 文件库管理：文件列表、分页查询、状态筛选、基础元数据维护
- 版本管理：SHA-256 查重、当前版本、历史版本、来源 URL、下载时间
- 状态复核：待复核、确认现行、疑似废止、确认废止
- 更新提醒：新增文件、文件变化、URL 失效、下载失败、提醒处理和忽略
- 检查日志：记录每次 URL 检查结果
- 系统设置：控制自动检查、批量检查、下载超时、默认导入频率和提醒渠道占位配置

## 大批量 URL 导入

`2025.1.3.csv` 已导入：

- CSV 总行数：107145
- 有下载地址：107091
- 去重后新增 URL：89730
- 文件内重复 URL：17361
- 缺少 URL：54

这些 URL 已统一设为 `check_frequency = manual`，不会被后台定时任务自动下载。

重新导入命令：

```powershell
.\backend\.venv\Scripts\python.exe scripts\import_url_sources.py 2025.1.3.csv
```

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 自动化流程 | n8n |
| 数据库 | PostgreSQL；本地开发可用 SQLite |
| 后端 | Python FastAPI |
| 前端 | Vue 3 + Element Plus |
| 文件存储 | 本地磁盘，后期可切 MinIO |

## 本地开发

启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

停止：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop-local.ps1
```

当前访问地址：

- 前端：http://127.0.0.1:5173
- API 文档：http://127.0.0.1:8000/api/v1/docs
- n8n：http://127.0.0.1:5678

## Docker 部署

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

启动：

```powershell
docker compose up --build
```

## 主要目录

```text
backend/       FastAPI 后端
frontend/      Vue 管理界面
scripts/       本地启动、停止、导入脚本
docs/          工作流与设计文档
```

## V1.0 最小闭环

```text
录入 URL
↓
系统定时检查或人工触发检查
↓
自动下载文件
↓
计算哈希
↓
判断是否更新
↓
保存当前版本或历史版本
↓
生成提醒
↓
人工复核状态
↓
进入标准规范文件库
```

## 系统设置

前端“系统设置”页面当前支持：

- `url_check_enabled`：启用或关闭后台自动检查
- `url_check_interval_seconds`：后台自动检查间隔
- `check_manual_in_batch`：批量检查是否包含 manual URL
- `download_timeout_seconds`：单个 URL 下载超时时间
- `default_import_frequency`：CSV 导入默认频率
- `storage_root`：文件归档根目录展示/配置
- `wechat_webhook_url`：企业微信机器人 Webhook 占位
- `smtp_enabled`：邮件提醒开关占位

## 暂缓内容

- 项目管理
- 项目依据绑定
- 项目影响分析
- AI 问答
- Dify / Qdrant / RAG
- 复杂权限和审批
