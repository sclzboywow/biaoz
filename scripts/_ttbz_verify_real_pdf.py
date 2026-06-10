"""Verify TTBZ logged-in download returns real standard PDF (not announcement)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

import httpx

from app.http_proxy import resolve_ttbz_http_proxy
from app.ttbz_browser_session import apply_ttbz_browser_cookies, check_ttbz_browser_login, resolve_ttbz_cdp_url
from app.ttbz_download import (
    TTBZ_API,
    TTBZ_ORIGIN,
    TtbzDownloadUnavailableError,
    build_ttbz_archive_file_stem,
    download_ttbz_pdf,
    fetch_portal_standard_detail,
    resolve_portal_body_pdf_path,
    _is_announcement_file,
    _only_announcement_files,
)

ANNOUNCEMENT_HINTS = ("公告", "关于发布", "关于批准", "关于印发")


def build_client() -> httpx.Client:
    proxy = resolve_ttbz_http_proxy()
    kwargs: dict = {"follow_redirects": True, "timeout": 60, "headers": {"User-Agent": "Mozilla/5.0", "Referer": f"{TTBZ_ORIGIN}/standard.html"}}
    if proxy:
        kwargs["proxy"] = proxy
    client = httpx.Client(**kwargs)
    apply_ttbz_browser_cookies(client, cdp_url=resolve_ttbz_cdp_url())
    return client


def pdf_meta(content: bytes) -> dict:
    head = content[:512].decode("latin-1", errors="ignore")
    return {
        "size": len(content),
        "is_pdf": content.startswith(b"%PDF"),
        "pages_hint": head.count("/Type /Page"),
        "announcement_hint": any(h in head for h in ANNOUNCEMENT_HINTS),
    }


def probe_detail(client: httpx.Client, uid: str) -> dict:
    detail = fetch_portal_standard_detail(uid, client=client)
    files = detail.get("files") or []
    return {
        "standardNo": detail.get("standardNo"),
        "standardPdfUrl": detail.get("standardPdfUrl"),
        "hasCnPdf": detail.get("hasCnPdf"),
        "only_announcement": _only_announcement_files(detail),
        "body_path": resolve_portal_body_pdf_path(detail),
        "files": [
            {
                "fileType": f.get("fileType"),
                "fileTypeName": f.get("fileTypeName"),
                "originalFileName": f.get("originalFileName"),
                "fileUrl": f.get("fileUrl"),
                "announcement": _is_announcement_file(f),
            }
            for f in files
            if isinstance(f, dict)
        ],
    }


def main() -> int:
    login = check_ttbz_browser_login()
    print("login", json.dumps(login, ensure_ascii=False))

    with build_client() as client:
        rows = client.post(
            f"{TTBZ_API}/getPortalStandardList",
            data={"pageNo": 1, "pageSize": 30, "isOpen": "1"},
        ).json()["data"]["rows"]

        tested = 0
        ok_real = 0
        for row in rows:
            uid = row["standardUniqueId"]
            standard_no = row.get("standardNo") or ""
            standard_name = row.get("standardTitleCn") or ""
            meta = probe_detail(client, uid)
            if meta["only_announcement"] and not meta["standardPdfUrl"] and not meta["body_path"]:
                continue

            tested += 1
            print("candidate", json.dumps({"uid": uid, "standardNo": standard_no, **meta}, ensure_ascii=False))

            try:
                downloaded = download_ttbz_pdf(
                    uid,
                    standard_no=standard_no,
                    standard_name=standard_name,
                    client=client,
                )
                info = pdf_meta(downloaded.content)
                info["url"] = downloaded.url
                info["file_name"] = build_ttbz_archive_file_stem(standard_no=standard_no, standard_name=standard_name) + ".pdf"
                print("download_ok", json.dumps(info, ensure_ascii=False))
                if info["is_pdf"] and info["size"] > 50000 and not info["announcement_hint"]:
                    ok_real += 1
                    if ok_real >= 3:
                        break
            except TtbzDownloadUnavailableError as exc:
                print("download_unavailable", json.dumps({"standardNo": standard_no, "error": str(exc)}, ensure_ascii=False))
            except Exception as exc:
                print("download_error", json.dumps({"standardNo": standard_no, "error": repr(exc)}, ensure_ascii=False))
            time.sleep(1.5)

        # direct downLoadStandard probe on first open row
        uid = rows[0]["standardUniqueId"]
        ref = f"{TTBZ_ORIGIN}/standardDetail/{uid}.html"
        dl = client.post(
            f"{TTBZ_API}/downLoadStandard",
            data={"standardUniqueId": uid},
            headers={"Accept": "application/pdf,*/*", "Referer": ref},
        )
        print(
            "downLoadStandard_direct",
            json.dumps(
                {
                    "standardNo": rows[0].get("standardNo"),
                    "status": dl.status_code,
                    "meta": pdf_meta(dl.content) if dl.content else {},
                    "text_head": (dl.text or "")[:100],
                },
                ensure_ascii=False,
            ),
        )

        print("summary", json.dumps({"tested": tested, "ok_real_pdf": ok_real}, ensure_ascii=False))
    return 0 if ok_real > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
