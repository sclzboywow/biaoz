#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NapCat OneBot v11 HTTP 客户端（用于需要响应的 API，如取文件、查消息）。"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

DEFAULT_NAPCAT_HTTP_URL = "http://127.0.0.1:3001"


class NapCatHttpError(RuntimeError):
    def __init__(self, action: str, payload: dict[str, Any]):
        self.action = action
        self.payload = payload
        retcode = payload.get("retcode")
        message = payload.get("message") or payload.get("wording") or payload
        super().__init__(f"NapCat API {action} failed: retcode={retcode} message={message}")


class NapCatHttpClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        access_token: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("NAPCAT_HTTP_URL") or DEFAULT_NAPCAT_HTTP_URL).rstrip("/")
        self.access_token = (access_token if access_token is not None else os.getenv("NAPCAT_HTTP_TOKEN", "")).strip()
        self.timeout_seconds = timeout_seconds

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _normalize_response(self, action: str, data: dict[str, Any]) -> dict[str, Any]:
        retcode = data.get("retcode")
        status = str(data.get("status") or "").lower()
        if status == "failed" or (retcode not in (0, "0", None)):
            raise NapCatHttpError(action, data)
        return data

    async def call_api(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = params or {}
        url = f"{self.base_url}/{action.lstrip('/')}"
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            resp = await client.post(
                url,
                headers=self._headers(),
                content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )
            resp.raise_for_status()
            data = resp.json()
        return self._normalize_response(action, data)

    def call_api_sync(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = params or {}
        url = f"{self.base_url}/{action.lstrip('/')}"
        with httpx.Client(timeout=self.timeout_seconds) as client:
            resp = client.post(
                url,
                headers=self._headers(),
                content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )
            resp.raise_for_status()
            data = resp.json()
        return self._normalize_response(action, data)

    async def ping(self) -> bool:
        try:
            await self.call_api("get_status")
            return True
        except Exception:
            return False
