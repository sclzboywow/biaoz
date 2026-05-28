# n8n 工作流设计

## 工作流 1：URL 定时检查

目标：定时读取 `url_sources`，访问 URL，下载文件或记录异常。

建议节点：

1. Schedule Trigger
2. Postgres：查询 `url_sources where status != '停用'`
3. HTTP Request：访问 URL
4. IF：判断状态码
5. HTTP Request：下载文件或网页内容
6. Code：计算文件 hash
7. HTTP Request：回调 FastAPI 写入版本或提醒

FastAPI 回调接口建议：

```text
POST /api/v1/documents/{document_id}/versions/upload
POST /api/v1/alerts
PATCH /api/v1/url-sources/{source_id}
```

## 工作流 2：文件入库解析

MVP 暂时保留为后端任务接口，第二步再做：

1. 新文件版本创建后触发
2. 提取 PDF/Word/Excel 文本
3. 调用 AI 提取元数据
4. 更新 `documents`
5. 设置 `review_status = 待复核`

## 工作流 3：更新提醒

触发条件：

- 文件 hash 变化
- URL 访问失败
- 下载失败
- AI 识别疑似废止/替代

提醒记录先写入 `alerts`，企业微信、邮箱、飞书机器人后续作为推送节点接入。
