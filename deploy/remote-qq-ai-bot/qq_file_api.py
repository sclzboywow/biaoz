#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QQ 群/私聊文件收发接口层。

- 入站：从 OneBot 消息事件解析 file 段，拉取字节并落盘
- 出站：向群/私聊发送聊天附件，或上传到群文件盘

依赖 NapCat HTTP API（NAPCAT_HTTP_URL，默认 http://127.0.0.1:3001）。
发送时若文件在宿主机，会先复制到 NAPCAT_FILE_STAGING_DIR，再使用容器路径引用。
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Union

import httpx

from napcat_http import NapCatHttpClient

SendMode = Literal["chat", "folder"]

DEFAULT_STAGING_DIR = "/home/ubuntu/napcat/config/outbound"
DEFAULT_CONTAINER_PREFIX = "/app/napcat/config/outbound"
DEFAULT_DOWNLOAD_DIR = "/home/ubuntu/qq-ai-bot/downloads"
DEFAULT_BASE64_MAX_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class QQFileSegment:
    file_name: str
    file_id: str
    file_size: int
    url: str | None = None
    busid: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QQDownloadedFile:
    file_name: str
    file_path: str
    file_size: int
    sha256: str
    source: str
    content_type: str = "application/octet-stream"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QQSendFileResult:
    ok: bool
    mode: SendMode
    target_type: Literal["group", "private"]
    target_id: int | str
    file_name: str
    message_id: int | None = None
    file_id: str | None = None
    detail: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (name or "file.bin").strip())
    return cleaned or "file.bin"


def extract_file_segments(message: Any) -> list[QQFileSegment]:
    if not isinstance(message, list):
        return []

    segments: list[QQFileSegment] = []
    for seg in message:
        if not isinstance(seg, dict) or seg.get("type") != "file":
            continue
        data = seg.get("data") or {}
        file_name = str(data.get("file") or data.get("name") or "").strip()
        file_id = str(data.get("file_id") or data.get("file") or "").strip()
        if not file_name and not file_id:
            continue
        size_raw = data.get("file_size") or data.get("size") or 0
        try:
            file_size = int(size_raw)
        except (TypeError, ValueError):
            file_size = 0
        busid_raw = data.get("busid")
        busid = int(busid_raw) if busid_raw not in (None, "") else None
        segments.append(
            QQFileSegment(
                file_name=_safe_filename(file_name or "file.bin"),
                file_id=file_id,
                file_size=file_size,
                url=(str(data.get("url")).strip() or None) if data.get("url") else None,
                busid=busid,
            )
        )
    return segments


def extract_file_segments_from_event(event: dict[str, Any]) -> list[QQFileSegment]:
    return extract_file_segments(event.get("message"))


class QQFileApi:
    def __init__(self, client: NapCatHttpClient | None = None) -> None:
        self.client = client or NapCatHttpClient()
        self.staging_dir = Path(
            os.getenv("NAPCAT_FILE_STAGING_DIR", DEFAULT_STAGING_DIR)
        ).expanduser()
        self.container_prefix = (
            os.getenv("NAPCAT_CONTAINER_FILE_PREFIX", DEFAULT_CONTAINER_PREFIX).rstrip("/")
        )
        self.download_dir = Path(os.getenv("QQ_FILE_DOWNLOAD_DIR", DEFAULT_DOWNLOAD_DIR)).expanduser()
        self.base64_max_bytes = int(os.getenv("QQ_FILE_BASE64_MAX_BYTES", str(DEFAULT_BASE64_MAX_BYTES)))

    def ensure_dirs(self) -> None:
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def stage_host_file(self, host_path: str | Path) -> tuple[str, str]:
        """
        将宿主机文件复制到 NapCat 可访问目录。
        返回 (host_staged_path, container_path)。
        """
        self.ensure_dirs()
        src = Path(host_path).expanduser().resolve()
        if not src.is_file():
            raise FileNotFoundError(f"file not found: {src}")

        staged_name = _safe_filename(src.name)
        staged_host = self.staging_dir / staged_name
        if staged_host.resolve() != src:
            shutil.copy2(src, staged_host)
        container_path = f"{self.container_prefix}/{staged_name}"
        return str(staged_host), container_path

    def _file_reference(self, host_path: str | Path) -> tuple[str, str]:
        src = Path(host_path).expanduser().resolve()
        if not src.is_file():
            raise FileNotFoundError(f"file not found: {src}")
        if src.stat().st_size <= self.base64_max_bytes:
            encoded = base64.b64encode(src.read_bytes()).decode("ascii")
            return "base64", f"base64://{encoded}"
        _, container_path = self.stage_host_file(src)
        return "container", container_path

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    async def get_message(self, message_id: int | str) -> dict[str, Any]:
        resp = await self.client.call_api("get_msg", {"message_id": int(message_id)})
        return resp.get("data") or {}

    async def get_group_file_url(
        self,
        *,
        group_id: int | str,
        file_id: str,
        busid: int | None = None,
    ) -> str:
        params: dict[str, Any] = {"group_id": int(group_id), "file_id": file_id}
        if busid is not None:
            params["busid"] = int(busid)
        resp = await self.client.call_api("get_group_file_url", params)
        url = str((resp.get("data") or {}).get("url") or "").strip()
        if not url:
            raise RuntimeError("get_group_file_url returned empty url")
        return url

    async def resolve_napcat_cached_file(self, file_id: str) -> QQDownloadedFile | None:
        resp = await self.client.call_api("get_file", {"file_id": file_id})
        data = resp.get("data") or {}
        cached = str(data.get("file") or data.get("url") or "").strip()
        if not cached:
            return None
        host_cached = cached
        if cached.startswith("/app/"):
            mapped = cached.replace("/app/napcat/config", str(self.staging_dir.parent), 1)
            if Path(mapped).is_file():
                host_cached = mapped
        path = Path(host_cached)
        if not path.is_file():
            return None
        content = path.read_bytes()
        return QQDownloadedFile(
            file_name=_safe_filename(str(data.get("file_name") or path.name)),
            file_path=str(path),
            file_size=len(content),
            sha256=self._sha256(content),
            source="napcat_cache",
            content_type="application/pdf" if path.suffix.lower() == ".pdf" else "application/octet-stream",
        )

    async def download_url_bytes(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=self.client.timeout_seconds, follow_redirects=True) as http:
            resp = await http.get(url, headers={"User-Agent": "QQFileApi/1.0"})
            resp.raise_for_status()
            return resp.content

    async def download_segment(
        self,
        segment: QQFileSegment,
        *,
        group_id: int | str | None = None,
        save_dir: str | Path | None = None,
    ) -> QQDownloadedFile:
        self.ensure_dirs()
        target_dir = Path(save_dir or self.download_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        content: bytes | None = None
        source = "unknown"

        if segment.url:
            content = await self.download_url_bytes(segment.url)
            source = "segment_url"
        elif group_id and segment.file_id:
            url = await self.get_group_file_url(
                group_id=group_id,
                file_id=segment.file_id,
                busid=segment.busid,
            )
            content = await self.download_url_bytes(url)
            source = "group_file_url"
        elif segment.file_id:
            cached = await self.resolve_napcat_cached_file(segment.file_id)
            if cached is not None:
                return cached

        if content is None:
            raise RuntimeError("unable to resolve downloadable content for file segment")

        file_name = _safe_filename(segment.file_name)
        out_path = target_dir / file_name
        if out_path.exists():
            stem, suffix = out_path.stem, out_path.suffix
            out_path = target_dir / f"{stem}_{segment.file_id.strip('/').replace('/', '_')[:16]}{suffix}"
        out_path.write_bytes(content)

        content_type = "application/pdf" if out_path.suffix.lower() == ".pdf" else "application/octet-stream"
        return QQDownloadedFile(
            file_name=file_name,
            file_path=str(out_path),
            file_size=len(content),
            sha256=self._sha256(content),
            source=source,
            content_type=content_type,
        )

    async def download_from_event(
        self,
        event: dict[str, Any],
        *,
        save_dir: str | Path | None = None,
        segment_index: int = 0,
    ) -> QQDownloadedFile:
        segments = extract_file_segments_from_event(event)
        if not segments:
            raise ValueError("event has no file segment")
        if segment_index < 0 or segment_index >= len(segments):
            raise IndexError(f"segment_index out of range: {segment_index}")
        group_id = event.get("group_id")
        return await self.download_segment(
            segments[segment_index],
            group_id=group_id,
            save_dir=save_dir,
        )

    async def download_from_message_id(
        self,
        message_id: int | str,
        *,
        group_id: int | str | None = None,
        save_dir: str | Path | None = None,
        segment_index: int = 0,
    ) -> QQDownloadedFile:
        msg = await self.get_message(message_id)
        segments = extract_file_segments(msg.get("message"))
        if not segments:
            raise ValueError(f"message {message_id} has no file segment")
        resolved_group_id = group_id or msg.get("group_id")
        return await self.download_segment(
            segments[segment_index],
            group_id=resolved_group_id,
            save_dir=save_dir,
        )

    async def send_group_file(
        self,
        *,
        group_id: int | str,
        file_path: str | Path,
        intro_text: str | None = None,
        mode: SendMode = "chat",
        file_name: str | None = None,
    ) -> QQSendFileResult:
        src = Path(file_path).expanduser().resolve()
        display_name = _safe_filename(file_name or src.name)

        if mode == "folder":
            _, container_path = self.stage_host_file(src)
            resp = await self.client.call_api(
                "upload_group_file",
                {
                    "group_id": int(group_id),
                    "file": container_path,
                    "name": display_name,
                },
            )
            data = resp.get("data") or {}
            if intro_text:
                await self.client.call_api(
                    "send_group_msg",
                    {"group_id": int(group_id), "message": intro_text},
                )
            return QQSendFileResult(
                ok=True,
                mode="folder",
                target_type="group",
                target_id=int(group_id),
                file_name=display_name,
                file_id=str(data.get("file_id") or "") or None,
                detail=data,
            )

        ref_kind, ref = self._file_reference(src)
        message: Union[str, list[dict[str, Any]]]
        if intro_text:
            message = [
                {"type": "text", "data": {"text": intro_text}},
                {"type": "file", "data": {"file": ref, "name": display_name}},
            ]
        else:
            message = [{"type": "file", "data": {"file": ref, "name": display_name}}]

        resp = await self.client.call_api(
            "send_group_msg",
            {"group_id": int(group_id), "message": message},
        )
        data = resp.get("data") or {}
        return QQSendFileResult(
            ok=True,
            mode="chat",
            target_type="group",
            target_id=int(group_id),
            file_name=display_name,
            message_id=int(data.get("message_id")) if data.get("message_id") else None,
            detail={"ref_kind": ref_kind, **data},
        )

    async def send_private_file(
        self,
        *,
        user_id: int | str,
        file_path: str | Path,
        intro_text: str | None = None,
        file_name: str | None = None,
    ) -> QQSendFileResult:
        src = Path(file_path).expanduser().resolve()
        display_name = _safe_filename(file_name or src.name)
        _, container_path = self.stage_host_file(src)

        if intro_text:
            await self.client.call_api(
                "send_private_msg",
                {"user_id": int(user_id), "message": intro_text},
            )

        resp = await self.client.call_api(
            "upload_private_file",
            {
                "user_id": int(user_id),
                "file": container_path,
                "name": display_name,
            },
        )
        data = resp.get("data") or {}
        return QQSendFileResult(
            ok=True,
            mode="chat",
            target_type="private",
            target_id=int(user_id),
            file_name=display_name,
            file_id=str(data.get("file_id") or "") or None,
            detail=data,
        )


_default_api: QQFileApi | None = None


def get_qq_file_api() -> QQFileApi:
    global _default_api
    if _default_api is None:
        _default_api = QQFileApi()
    return _default_api
