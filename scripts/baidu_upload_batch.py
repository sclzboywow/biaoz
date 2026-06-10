from __future__ import annotations

import argparse
import json

from app.baidu_upload_queue import flush_baidu_upload_queue, get_baidu_upload_queue, reset_baidu_upload_queue


def add_baidu_upload_args(parser: argparse.ArgumentParser, *, default_defer: bool = True) -> None:
    parser.add_argument("--defer-baidu-upload", action=argparse.BooleanOptionalAction, default=default_defer)
    parser.add_argument("--baidu-upload-workers", type=int, default=4)


def init_baidu_upload_workers(args: argparse.Namespace) -> None:
    if not args.defer_baidu_upload:
        return
    reset_baidu_upload_queue()
    get_baidu_upload_queue(workers=max(args.baidu_upload_workers, 1))


def log_baidu_upload_summary(prefix: str, args: argparse.Namespace) -> None:
    if not args.defer_baidu_upload:
        return
    summary = flush_baidu_upload_queue()
    print(f"{prefix}_baidu_upload_summary " + json.dumps(summary, ensure_ascii=False), flush=True)
