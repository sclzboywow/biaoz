#!/usr/bin/env bash
set -euo pipefail
ROOT="/home/ubuntu/payment-api"
cd "$ROOT"

# 切换为当面付扫码（alipay.trade.precreate）
if grep -q '^ALIPAY_TRADE_METHOD=' .env; then
  sed -i 's/^ALIPAY_TRADE_METHOD=.*/ALIPAY_TRADE_METHOD=precreate/' .env
else
  echo 'ALIPAY_TRADE_METHOD=precreate' >> .env
fi
if ! grep -q '^ALIPAY_PRODUCT_CODE=' .env; then
  echo 'ALIPAY_PRODUCT_CODE=FACE_TO_FACE_PAYMENT' >> .env
else
  sed -i 's/^ALIPAY_PRODUCT_CODE=.*/ALIPAY_PRODUCT_CODE=FACE_TO_FACE_PAYMENT/' .env
fi
if ! grep -q '^ALIPAY_TIMEOUT_EXPRESS=' .env; then
  echo 'ALIPAY_TIMEOUT_EXPRESS=10m' >> .env
fi

# library/service.py 与 api/orders.py 改用 create_alipay_pay
sed -i 's/create_alipay_page_pay/create_alipay_pay/g' library/service.py api/orders.py

sudo systemctl restart payment-api.service
sleep 2
systemctl is-active payment-api.service

echo "ALIPAY_TRADE_METHOD=$(grep ^ALIPAY_TRADE_METHOD= .env)"
