#!/usr/bin/env python3
"""Smoke test for QQ file API modules."""
from __future__ import annotations

import json

from napcat_http import NapCatHttpClient
from qq_file_api import QQFileApi, extract_file_segments


def main() -> int:
    sample = [
        {
            "type": "file",
            "data": {
                "file": "16MG03+\u5730\u6c9f\u6784\u4ef6.pdf",
                "file_id": "/fd615d0f-bd00-4153-a8e2-252b8f62c508",
                "file_size": "26702904",
                "url": "https://example.com/file",
            },
        }
    ]
    segments = extract_file_segments(sample)
    assert len(segments) == 1
    assert segments[0].file_name.endswith(".pdf")
    assert segments[0].file_size == 26702904

    api = QQFileApi(NapCatHttpClient(base_url="http://127.0.0.1:3001"))
    print("extract_file_segments:", json.dumps([s.to_dict() for s in segments], ensure_ascii=False))
    print("napcat_http_url:", api.client.base_url)
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
