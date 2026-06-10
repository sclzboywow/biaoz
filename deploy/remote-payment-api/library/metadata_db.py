#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

import psycopg

DEFAULT_METADATA_DATABASE_URL = "postgresql://biaoz:biaoz@127.0.0.1:5432/biaoz"


@lru_cache(maxsize=1)
def get_metadata_database_url() -> str:
    return (
        os.getenv("METADATA_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or DEFAULT_METADATA_DATABASE_URL
    ).strip()


def metadata_search_enabled() -> bool:
    flag = os.getenv("METADATA_SEARCH_ENABLED", "true").strip().lower()
    return flag not in {"0", "false", "no", "off"}


@contextmanager
def metadata_connection() -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(get_metadata_database_url())
    try:
        yield conn
    finally:
        conn.close()
