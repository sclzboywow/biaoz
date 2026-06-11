# 当面付退款接口

支付宝当面付（`precreate`）原路退款 API，部署于 `111.231.22.77` 的 `payment-api` 服务。

## 部署

```bash
# Linux / Git Bash
bash deploy/remote-payment-api/deploy_refund.sh

# Windows PowerShell（先 scp 再 ssh 执行 install_refund.py）
scp -i $env:USERPROFILE\.ssh\id_ed25519 -r deploy/remote-payment-api/files deploy/remote-payment-api/install_refund.py ubuntu@111.231.22.77:/tmp/refund-deploy/
ssh -i $env:USERPROFILE\.ssh\id_ed25519 ubuntu@111.231.22.77 "/home/ubuntu/payment-api/.venv/bin/python /tmp/refund-deploy/install_refund.py"
```

## 鉴权

所有退款接口需请求头：

```
X-Internal-Secret: <BOT_INTERNAL_SECRET>
```

与 `.env` 中 `BOT_INTERNAL_SECRET` 一致。

---

## 1. 下载券订单退款（推荐）

**POST** `/api/internal/ticket-order/refund`

对已支付的下载券订单发起**全额原路退款**，并自动扣回已发放的下载券。

### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `order_no` | string | 是 | 订单号，如 `T1781142147462` |
| `reason` | string | 否 | 退款原因，默认 `admin refund` |
| `operator` | string | 否 | 操作人，默认 `admin` |
| `refund_amount_yuan` | float | 否 | 退款金额（元），默认订单全额 |

### 成功响应示例

```json
{
  "status": "success",
  "message": "refund completed",
  "order_no": "T1781142147462",
  "out_request_no": "RFT1781142147462187",
  "refund_amount_yuan": 1.99,
  "tickets_deducted": 1,
  "balance_after": 0,
  "qq_user_id": "215836668",
  "alipay": {
    "status": "success",
    "fund_change": "Y",
    "refund_fee": "1.99"
  }
}
```

### 调用示例

```bash
curl -X POST http://127.0.0.1:8000/api/internal/ticket-order/refund \
  -H "Content-Type: application/json" \
  -H "X-Internal-Secret: qq-payment-internal-2026" \
  -d '{"order_no":"T1781142147462","reason":"user request"}'
```

---

## 2. 通用支付宝退款

**POST** `/api/payment/alipay/refund`

直接调用 `alipay.trade.refund`，适用于任意已支付商户订单号。

### 请求体

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `out_trade_no` | string | 是* | 商户订单号（也可用 `order_no`） |
| `refund_amount` | float | 是* | 退款金额（元） |
| `refund_amount_cents` | int | 是* | 退款金额（分），与 `refund_amount` 二选一 |
| `out_request_no` | string | 否 | 退款请求号，默认 `RF{out_trade_no}` |
| `trade_no` | string | 否 | 支付宝交易号 |
| `reason` | string | 否 | 退款原因 |

### 示例

```bash
curl -X POST http://127.0.0.1:8000/api/payment/alipay/refund \
  -H "Content-Type: application/json" \
  -H "X-Internal-Secret: qq-payment-internal-2026" \
  -d '{"out_trade_no":"T1781142147462","refund_amount":1.99,"reason":"refund"}'
```

---

## 3. 退款查询

**GET** `/api/payment/alipay/refund/query`

| 参数 | 必填 | 说明 |
|------|------|------|
| `out_request_no` | 是 | 退款请求号 |
| `out_trade_no` | 否 | 商户订单号 |
| `trade_no` | 否 | 支付宝交易号 |

```bash
curl "http://127.0.0.1:8000/api/payment/alipay/refund/query?out_request_no=RFT1781142147462187" \
  -H "X-Internal-Secret: qq-payment-internal-2026"
```

---

## 常见错误

| 支付宝 sub_code | 含义 | 处理 |
|-----------------|------|------|
| `ACQ.SELLER_BALANCE_NOT_ENOUGH` | 商户可用余额不足 | 充值后再退；全额退 1.99 元时账户需能划出 1.99（手续费约 0.01 元差额） |
| 订单 `status != paid` | 订单不可退 | 仅 `paid` 状态可退；已 `refunded` 返回 success |

## 文件结构

```
deploy/remote-payment-api/
  files/library/refund.py          # 订单退款 + 扣券逻辑
  files/services/payment_service_refund.py
  files/routes/payments_refund_routes.py
  files/routes/library_refund_route.py
  install_refund.py                # 幂等安装脚本
  deploy_refund.sh                 # 一键部署
  test_refund.py                   # 本地测试脚本（拷到服务器执行）
```
