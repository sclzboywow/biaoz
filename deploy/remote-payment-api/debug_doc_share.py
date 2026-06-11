#!/usr/bin/env python3
import sys
sys.path.insert(0, "/home/ubuntu/payment-api")
from library.metadata_search import lookup_metadata_document
from library.baidu_remark import resolve_baidu_fs_id
from library.baidu_client import create_share_link

doc_id = int(sys.argv[1]) if len(sys.argv) > 1 else 77716
d = lookup_metadata_document(doc_id)
print("code", d.get("code") if d else None)
print("has_file", d.get("has_file") if d else None)
print("file_path", (d.get("file_path") or "")[:120] if d else None)
fs = resolve_baidu_fs_id(file_path=d.get("file_path"), remark=d.get("remark")) if d else None
print("fs_id", fs)
print("share", create_share_link(fs) if fs else None)
