#!/usr/bin/env python3
import time

from services.payment_service import create_alipay_pay

order_no = f"TTEST{int(time.time())}"
result = create_alipay_pay("下载券-测试", 0.01, order_no)
print("status=", result.get("status"))
print("trade_method=", result.get("trade_method"))
print("message=", result.get("message"))
pay_url = result.get("pay_url") or ""
print("pay_url_prefix=", pay_url[:80])
