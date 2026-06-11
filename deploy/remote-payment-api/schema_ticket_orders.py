import sqlite3
c = sqlite3.connect("/home/ubuntu/payment-api/library.db")
print(c.execute("PRAGMA table_info(ticket_orders)").fetchall())
