from __future__ import annotations

import os


def resolve_http_proxy(*env_keys: str) -> str | None:
    keys = env_keys or ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            return value
    return None


def resolve_ttbz_http_proxy() -> str | None:
    return resolve_http_proxy("TTBZ_HTTP_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY")
