# 资料下载发放接口

## 1. 选择下载（增强响应）

**POST** `/api/download/select`

原有参数不变。成功时额外返回：

```json
{
  "success": true,
  "document": { "id": 77716, "code": "GB50016-2014", "title": "建筑设计防火规范" },
  "pan_share_url": "https://pan.baidu.com/netdisk/share?surl=...",
  "pan_extract_code": "7rvb",
  "share": {
    "pan_share_url": "...",
    "pan_extract_code": "7rvb",
    "period_days": 7,
    "period_label": "7天"
  },
  "file": {
    "display_name": "GB50016-2014 建筑设计防火规范.pdf"
  },
  "message": "资料下载成功\n\n名称：...\n链接：...\n提取码：...\n有效期：7天\n..."
}
```

Bot 优先使用 `message` 字段发群消息。

## 2. 一键发放到 QQ 群（内部接口）

**POST** `/api/internal/download/deliver-to-group`

Header: `X-Internal-Secret`

```json
{
  "qq_user_id": "215836668",
  "group_id": "808238349",
  "index": 1,
  "send_text": true,
  "send_file": true
}
```

流程：
1. 创建搜索会话上下文后选择编号（需先 `/api/search-sessions`）
2. 生成百度分享链接
3. 发送优化后的文字到群
4. 从网盘下载 PDF，以**中文文件名**发到群

### 示例

```bash
# 1) 搜索
curl -X POST http://127.0.0.1:8000/api/search-sessions \
  -H 'Content-Type: application/json' \
  -d '{"qq_user_id":"215836668","group_id":"808238349","query_text":"GB50016"}'

# 2) 发放到群
curl -X POST http://127.0.0.1:8000/api/internal/download/deliver-to-group \
  -H 'Content-Type: application/json' \
  -H 'X-Internal-Secret: qq-payment-internal-2026' \
  -d '{"qq_user_id":"215836668","group_id":"808238349","index":1}'
```

## 配置

| 变量 | 说明 | 默认 |
|------|------|------|
| `BAIDU_SHARE_PERIOD_DAYS` | 分享有效期（天） | 7 |
| `LIBRARY_DOWNLOAD_DIR` | 服务器暂存下载目录 | `/home/ubuntu/qq-ai-bot/downloads/delivery` |
| `LOCAL_CACHE_MAX_AGE_DAYS` | 本地缓存最长保留天数 | `7` |

文件始终通过 **聊天窗口** 发送（`mode=chat`），不使用群文件盘。

## 缓存清理

自动删除超过 `LOCAL_CACHE_MAX_AGE_DAYS`（默认 7 天）的本地文件，目录包括：

- `/home/ubuntu/qq-ai-bot/downloads/`
- `/home/ubuntu/napcat/config/outbound/`（NapCat 发文件 staging）

触发时机：每次发放完成后轻量清理 + 每天 03:17 cron 全量清扫。
| `BOT_API_BASE` | qq-ai-bot 地址 | `http://127.0.0.1:8765` |

## 部署

```bash
scp -r deploy/remote-payment-api/library/*.py deploy/remote-payment-api/install_download_delivery.py ubuntu@SERVER:/tmp/
python3 /tmp/install_download_delivery.py
sudo systemctl restart payment-api.service qq-ai-bot.service
```
