#!/usr/bin/env python3
"""Install download delivery modules and patch payment-api."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path("/home/ubuntu/payment-api")
LIB = ROOT / "library"
FILES = Path(__file__).resolve().parent / "files" if (Path(__file__).resolve().parent / "files").exists() else Path(__file__).resolve().parent / "library"
# modules live next to this script under library/
SRC = Path(__file__).resolve().parent / "library"


def copy_modules() -> None:
    for name in ("download_delivery.py", "download_file.py", "group_deliver.py", "baidu_client.py", "metadata_integration.py"):
        src = SRC / name
        if src.exists():
            (LIB / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"copied {name}")


def patch_service() -> None:
    path = LIB / "service.py"
    text = path.read_text(encoding="utf-8", errors="replace")
    if "enrich_download_result" in text:
        print("service.py already patched")
        return
    old = '''        cur.execute("COMMIT")
        return {
            "success": True,
            "need_pay": False,
            "free_download": free_mode,
            "document": {
                "id": doc[0],
                "code": doc[1],
                "title": doc[2],
                "category": doc[3] or "",
            },
            "ticket_cost": 0 if free_mode else ticket_cost,
            "balance": new_balance,
            "pan_share_url": share["pan_share_url"],
            "pan_extract_code": share["pan_extract_code"],
        }'''
    new = '''        cur.execute("COMMIT")
        from .download_delivery import enrich_download_result

        share_meta = {
            "period_days": share.get("period_days"),
            "share_id": share.get("share_id"),
            "pan_short_url": share.get("pan_short_url"),
        }
        return enrich_download_result(
            {
                "success": True,
                "need_pay": False,
                "free_download": free_mode,
                "document": {
                    "id": doc[0],
                    "code": doc[1],
                    "title": doc[2],
                    "category": doc[3] or "",
                },
                "ticket_cost": 0 if free_mode else ticket_cost,
                "balance": new_balance,
                "pan_share_url": share["pan_share_url"],
                "pan_extract_code": share["pan_extract_code"],
            },
            share_meta,
        )'''
    if old not in text:
        raise SystemExit("service.py anchor not found")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("patched service.py")


def patch_resend() -> None:
    path = LIB / "service.py"
    text = path.read_text(encoding="utf-8", errors="replace")
    if "resend enrich_download_result" in text:
        return
    old = '''    return {
        "success": True,
        "document": {"code": doc_code, "title": title},
        "pan_share_url": url,
        "pan_extract_code": code or "",
    }'''
    new = '''    from .download_delivery import enrich_download_result, default_share_period_days

    return enrich_download_result(
        {
            "success": True,
            "document": {"code": doc_code, "title": title},
            "pan_share_url": url,
            "pan_extract_code": code or "",
            "ticket_cost": 0,
            "balance": 0,
            "free_download": False,
        },
        {"period_days": default_share_period_days()},
    )'''
    if old not in text:
        raise SystemExit("resend anchor not found")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("patched resend")


def patch_api() -> None:
    path = ROOT / "api" / "library.py"
    text = path.read_text(encoding="utf-8", errors="replace")
    if "api_internal_deliver_to_group" in text:
        print("api already patched")
        return
    if "from library.refund import refund_ticket_order" in text and "from library.group_deliver import deliver_download_to_group" not in text:
        text = text.replace(
            "from library.refund import refund_ticket_order",
            "from library.refund import refund_ticket_order\nfrom library.group_deliver import deliver_download_to_group",
        )
    addon = '''

@router.post("/api/internal/download/deliver-to-group")
async def api_internal_deliver_to_group(
    payload: Dict[str, Any],
    x_internal_secret: str = Header(default=None, alias="X-Internal-Secret"),
):
    """Select download and deliver formatted text + Chinese-named file to QQ group."""
    expected = (os.getenv("BOT_INTERNAL_SECRET") or "").strip()
    if expected and x_internal_secret != expected:
        raise HTTPException(status_code=403, detail="forbidden")
    qq_user_id = str(payload.get("qq_user_id") or "")
    group_id = str(payload.get("group_id") or "")
    index = payload.get("index")
    if not qq_user_id or not group_id or index is None:
        return JSONResponse({"success": False, "message": "missing parameters"}, status_code=400)
    send_text = payload.get("send_text", True)
    send_file = payload.get("send_file", True)
    result = deliver_download_to_group(
        qq_user_id,
        group_id,
        int(index),
        send_text=bool(send_text),
        send_file=bool(send_file),
    )
    if result.get("need_pay"):
        code = 200
    elif result.get("success"):
        code = 200
    else:
        code = 400
    return JSONResponse(result, status_code=code)
'''
    path.write_text(text.rstrip() + addon + "\n", encoding="utf-8")
    print("patched api/library.py")


def main() -> int:
    copy_modules()
    patch_service()
    patch_resend()
    patch_api()
    for rel in (
        "library/download_delivery.py",
        "library/download_file.py",
        "library/group_deliver.py",
        "library/service.py",
        "api/library.py",
    ):
        ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    print("syntax ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
