#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect("/home/ubuntu/payment-api/library.db")
rows = conn.execute(
    "SELECT order_no, status, amount_cent, alipay_trade_no, paid_at FROM ticket_orders ORDER BY id DESC LIMIT 5"
).fetchall()
for r in rows:
    print(r)
conn.close()
