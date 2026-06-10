#!/usr/bin/env bash
set -euo pipefail
cd /home/ubuntu/payment-api
/home/ubuntu/payment-api/.venv/bin/pip install -q 'psycopg[binary]>=3.1'
if ! grep -q '^METADATA_DATABASE_URL=' .env 2>/dev/null; then
  echo 'METADATA_DATABASE_URL=postgresql://biaoz:biaoz@127.0.0.1:5432/biaoz' >> .env
fi
if ! grep -q '^METADATA_SEARCH_ENABLED=' .env 2>/dev/null; then
  echo 'METADATA_SEARCH_ENABLED=true' >> .env
fi
/home/ubuntu/payment-api/.venv/bin/python test_metadata_search.py
sudo systemctl restart payment-api.service
sleep 2
systemctl is-active payment-api.service
curl -s 'http://127.0.0.1:8000/api/documents/search?q=GB50016&limit=3' | head -c 500
echo
