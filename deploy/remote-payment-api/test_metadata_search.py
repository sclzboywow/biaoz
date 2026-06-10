#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke test metadata search on remote PostgreSQL."""

from library.metadata_search import search_metadata_documents

for q in ["GB50016", "GB/T 11798", "建筑设计防火"]:
    items = search_metadata_documents(q, limit=3)
    print("query=", q, "count=", len(items))
    for item in items:
        print(" ", item["code"], item["title"][:40], "has_file=", item.get("has_file"))
