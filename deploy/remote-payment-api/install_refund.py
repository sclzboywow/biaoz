#!/usr/bin/env python3
"""Idempotent installer for Alipay refund API on payment-api server."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path("/home/ubuntu/payment-api")
FILES = Path(__file__).resolve().parent / "files"


def ensure_db_columns() -> None:
    db_path = ROOT / "library.db"
    if not db_path.exists():
        return
    conn = sqlite3.connect(db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(ticket_orders)")}
    if "refund_reason" not in cols:
        conn.execute("ALTER TABLE ticket_orders ADD COLUMN refund_reason TEXT")
    if "refund_request_no" not in cols:
        conn.execute("ALTER TABLE ticket_orders ADD COLUMN refund_request_no TEXT")
    conn.commit()
    conn.close()


def patch_payment_service() -> None:
    from files.services.payment_service_refund import REFUND_FUNCTIONS

    path = ROOT / "services" / "payment_service.py"
    text = path.read_text(encoding="utf-8", errors="replace")
    if "def refund_alipay_trade(" not in text:
        text = text.rstrip() + "\n\n" + REFUND_FUNCTIONS.strip() + "\n"
        path.write_text(text, encoding="utf-8")
        print("appended refund functions to payment_service.py")


def patch_imports_and_routes(module: str, marker: str, addon: str, import_patches: list[tuple[str, str]]) -> None:
    path = ROOT / "api" / module
    text = path.read_text(encoding="utf-8", errors="replace")
    if marker in text:
        text = text.split(marker)[0].rstrip() + "\n"
    for old, new in import_patches:
        if new not in text and old in text:
            text = text.replace(old, new)
    handler_name = marker.split('"')[1] if '"' in marker else marker
    if handler_name not in text:
        text = text.rstrip() + addon + "\n"
    path.write_text(text, encoding="utf-8")
    print(f"patched api/{module}")


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    refund_py = FILES / "library" / "refund.py"
    target = ROOT / "library" / "refund.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(refund_py.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"wrote {target}")

    ensure_db_columns()
    patch_payment_service()

    from files.routes.payments_refund_routes import PAYMENTS_REFUND_ROUTES
    from files.routes.library_refund_route import LIBRARY_REFUND_ROUTE

    patch_imports_and_routes(
        "payments.py",
        '@router.post("/alipay/refund")',
        PAYMENTS_REFUND_ROUTES,
        [
            (
                "from services.payment_service import query_alipay_trade, process_alipay_async_notify",
                "from services.payment_service import query_alipay_trade, process_alipay_async_notify, refund_alipay_trade, query_alipay_refund",
            ),
        ],
    )
    patch_imports_and_routes(
        "library.py",
        '@router.post("/api/internal/ticket-order/refund")',
        LIBRARY_REFUND_ROUTE,
        [
            (
                "from library.constants import TICKET_PACKS",
                "import os\nfrom library.constants import TICKET_PACKS\nfrom library.refund import refund_ticket_order",
            ),
            (
                "from fastapi import APIRouter, Query, Request",
                "from fastapi import APIRouter, Query, Request, Header, HTTPException",
            ),
        ],
    )

    import ast

    for rel in ("library/refund.py", "api/payments.py", "api/library.py", "services/payment_service.py"):
        ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    print("syntax ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
