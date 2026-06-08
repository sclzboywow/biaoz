from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import httpx
from sqlalchemy.orm import Session

from app.settings_store import get_setting


BAIDU_PAN_SCHEME = "baidupan:"
DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024
DEFAULT_HTTP_RETRIES = 3
_KNOWN_REMOTE_DIRS: set[str] = set()
_KNOWN_REMOTE_DIRS_LOCK = threading.Lock()


class BaiduPanError(RuntimeError):
    pass


@dataclass(frozen=True)
class BaiduPanConfig:
    access_token: str | None
    refresh_token: str | None
    client_id: str | None
    client_secret: str | None
    root_path: str
    account_file: Path | None = None
    timeout_seconds: int = 120

    @property
    def configured(self) -> bool:
        return bool(self.access_token or (self.refresh_token and self.client_id and self.client_secret))


@dataclass(frozen=True)
class BaiduPanUploadResult:
    path: str
    fs_id: str | None
    md5: str | None
    size: int

    @property
    def uri(self) -> str:
        fs_fragment = f"#fs_id={quote(self.fs_id)}" if self.fs_id else ""
        return f"{BAIDU_PAN_SCHEME}{self.path}{fs_fragment}"


def is_baidu_pan_uri(value: str | None) -> bool:
    return bool(value and value.startswith(BAIDU_PAN_SCHEME))


def parse_baidu_pan_uri(value: str) -> tuple[str, str | None]:
    if not is_baidu_pan_uri(value):
        raise ValueError("not a baidu pan uri")
    parsed = urlparse(value)
    fs_id = None
    if parsed.fragment:
        match = re.search(r"(?:^|&)fs_id=([^&]+)", parsed.fragment)
        if match:
            fs_id = unquote(match.group(1))
    path = value.removeprefix(BAIDU_PAN_SCHEME).split("#", 1)[0]
    return path, fs_id


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_text_best_effort(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(errors="ignore")


def _parse_account_file(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}
    result: dict[str, str] = {}
    key_map = {
        "appkey": "client_id",
        "client_id": "client_id",
        "apikey": "client_id",
        "secretkey": "client_secret",
        "client_secret": "client_secret",
        "access_token": "access_token",
        "accesstoken": "access_token",
        "refresh_token": "refresh_token",
        "refreshtoken": "refresh_token",
    }
    for raw_line in _read_text_best_effort(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([^:=：\s]+)\s*[:=：]\s*(.+)$", line)
        if not match:
            continue
        key = re.sub(r"[^0-9A-Za-z_]+", "", match.group(1)).lower()
        mapped = key_map.get(key)
        if mapped:
            result[mapped] = match.group(2).strip().strip('"').strip("'")
    return result


def _default_account_file() -> Path | None:
    candidates = sorted((_repo_root() / "openxpanapi").glob("*.txt"))
    return candidates[0] if candidates else None


def load_baidu_pan_config(db: Session | None = None) -> BaiduPanConfig:
    account_file_value = (
        os.getenv("BAIDU_PAN_ACCOUNT_FILE")
        or (get_setting(db, "baidu_pan_account_file", "") if db is not None else "")
        or ""
    )
    account_file = Path(account_file_value).expanduser() if account_file_value else _default_account_file()
    if account_file and not account_file.is_absolute():
        account_file = (_repo_root() / account_file).resolve()
    account_values = _parse_account_file(account_file) if account_file else {}

    def setting(name: str, default: str = "") -> str:
        return (get_setting(db, name, default) if db is not None else default) or default

    return BaiduPanConfig(
        access_token=os.getenv("BAIDU_PAN_ACCESS_TOKEN") or setting("baidu_pan_access_token") or account_values.get("access_token"),
        refresh_token=os.getenv("BAIDU_PAN_REFRESH_TOKEN") or setting("baidu_pan_refresh_token") or account_values.get("refresh_token"),
        client_id=os.getenv("BAIDU_PAN_CLIENT_ID") or setting("baidu_pan_client_id") or account_values.get("client_id"),
        client_secret=os.getenv("BAIDU_PAN_CLIENT_SECRET") or setting("baidu_pan_client_secret") or account_values.get("client_secret"),
        root_path=(os.getenv("BAIDU_PAN_ROOT") or setting("baidu_pan_root", "/apps/standard-docs")).rstrip("/") or "/apps/standard-docs",
        account_file=account_file,
        timeout_seconds=int(os.getenv("BAIDU_PAN_TIMEOUT_SECONDS") or setting("baidu_pan_timeout_seconds", "120")),
    )


class BaiduPanClient:
    def __init__(self, config: BaiduPanConfig):
        if not config.configured:
            raise BaiduPanError("Baidu Pan is not configured: access_token or refresh_token/app key is missing")
        self.config = config
        self._access_token = config.access_token

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        if not (self.config.refresh_token and self.config.client_id and self.config.client_secret):
            raise BaiduPanError("Baidu Pan access token is missing")
        response = httpx.post(
            "https://openapi.baidu.com/oauth/2.0/token",
            params={"grant_type": "refresh_token", "openapi": "xpansdk"},
            data={
                "refresh_token": self.config.refresh_token,
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            },
            timeout=self.config.timeout_seconds,
        )
        data = _json_response(response)
        token = data.get("access_token")
        if not token:
            raise BaiduPanError(f"Baidu Pan refresh token response missing access_token: {_safe_error(data)}")
        self._access_token = token
        return token

    def upload_bytes(self, content: bytes, relative_path: str, rtype: int = 3) -> BaiduPanUploadResult:
        remote_path = self._remote_path(relative_path)
        self.ensure_parent_dirs(remote_path)
        block_md5 = _block_md5s(content)
        block_list = json.dumps(block_md5, separators=(",", ":"))
        content_md5 = hashlib.md5(content).hexdigest()
        slice_md5 = hashlib.md5(content[: 256 * 1024]).hexdigest()

        precreate = self._post_pan(
            "https://pan.baidu.com/rest/2.0/xpan/file",
            params={"method": "precreate", "openapi": "xpansdk"},
            data={
                "path": remote_path,
                "isdir": 0,
                "size": len(content),
                "autoinit": 1,
                "block_list": block_list,
                "rtype": rtype,
                "content-md5": content_md5,
                "slice-md5": slice_md5,
            },
        )
        if int(precreate.get("errno") or 0) != 0:
            raise BaiduPanError(f"Baidu Pan precreate failed: {_safe_error(precreate)}")

        upload_id = precreate.get("uploadid")
        return_type = int(precreate.get("return_type") or 0)
        if upload_id and return_type != 2:
            for index, chunk in enumerate(_chunks(content)):
                self._upload_part(remote_path, str(upload_id), index, chunk)

        created = self._post_pan(
            "https://pan.baidu.com/rest/2.0/xpan/file",
            params={"method": "create", "openapi": "xpansdk"},
            data={
                "path": remote_path,
                "isdir": 0,
                "size": len(content),
                "uploadid": upload_id or "",
                "block_list": block_list,
                "rtype": rtype,
            },
        )
        if int(created.get("errno") or 0) != 0:
            raise BaiduPanError(f"Baidu Pan create failed: {_safe_error(created)}")
        return BaiduPanUploadResult(
            path=str(created.get("path") or remote_path),
            fs_id=str(created.get("fs_id")) if created.get("fs_id") is not None else None,
            md5=created.get("md5"),
            size=int(created.get("size") or len(content)),
        )

    def download_uri(self, uri: str) -> tuple[bytes, str | None]:
        meta = self.file_meta_uri(uri, dlink=True)
        path, _fs_id = parse_baidu_pan_uri(uri)
        dlink = meta.get("dlink")
        if not dlink:
            raise BaiduPanError(f"Baidu Pan dlink missing for: {path}")
        separator = "&" if "?" in dlink else "?"
        response = httpx.get(
            f"{dlink}{separator}access_token={quote(self._token(), safe='')}",
            headers={"User-Agent": "pan.baidu.com"},
            follow_redirects=True,
            timeout=self.config.timeout_seconds,
        )
        if response.status_code >= 400:
            raise BaiduPanError(f"Baidu Pan dlink download failed: status={response.status_code} body={response.text[:200]!r}")
        return response.content, response.headers.get("content-type")

    def file_meta_uri(self, uri: str, *, dlink: bool = False) -> dict[str, Any]:
        path, fs_id = parse_baidu_pan_uri(uri)
        if not fs_id:
            fs_id = self._find_fs_id(path)
        try:
            return self.file_meta_fs_id(fs_id, dlink=dlink)
        except BaiduPanError as exc:
            if "file meta not found" not in str(exc):
                raise
            return self.file_meta_fs_id(self._find_fs_id(path), dlink=dlink)

    def file_meta_fs_id(self, fs_id: str | int, *, dlink: bool = False) -> dict[str, Any]:
        meta = self._post_pan(
            "https://pan.baidu.com/rest/2.0/xpan/multimedia",
            params={"method": "filemetas", "openapi": "xpansdk"},
            data={"fsids": json.dumps([int(fs_id)]), "dlink": 1 if dlink else 0},
        )
        items = meta.get("list") or []
        if not items:
            raise BaiduPanError(f"Baidu Pan file meta not found: fs_id={fs_id}")
        return dict(items[0])

    def quota(self) -> dict[str, Any]:
        response = httpx.get(
            "https://pan.baidu.com/api/quota",
            params={"access_token": self._token(), "openapi": "xpansdk", "checkexpire": 1, "checkfree": 1},
            timeout=self.config.timeout_seconds,
        )
        return _json_response(response)

    def ensure_parent_dirs(self, path: str) -> None:
        parent = str(Path(path).parent).replace("\\", "/")
        if parent in {"", "/", "."}:
            return
        current = ""
        for part in [item for item in parent.split("/") if item]:
            current += "/" + part
            with _KNOWN_REMOTE_DIRS_LOCK:
                if current in _KNOWN_REMOTE_DIRS:
                    continue
            self.mkdir(current)
            with _KNOWN_REMOTE_DIRS_LOCK:
                _KNOWN_REMOTE_DIRS.add(current)

    def mkdir(self, path: str) -> None:
        response = _request_with_retries(
            "POST",
            "https://pan.baidu.com/rest/2.0/xpan/file",
            params={"method": "create", "openapi": "xpansdk", "access_token": self._token()},
            data={"path": path, "isdir": 1, "size": 0, "uploadid": "", "block_list": "[]", "rtype": 3},
            timeout=self.config.timeout_seconds,
        )
        data = _json_response(response, allow_api_error=True)
        errno = data.get("errno")
        if errno not in (None, 0, 102, -8, 31034):
            raise BaiduPanError(f"Baidu Pan mkdir failed: {_safe_error(data)}")

    def _remote_path(self, relative_path: str) -> str:
        parts = []
        for part in Path(relative_path).as_posix().split("/"):
            clean = part.strip().replace("\\", "-").replace("/", "-")
            if clean and clean not in {".", ".."}:
                parts.append(clean)
        return self.config.root_path.rstrip("/") + "/" + "/".join(parts)

    def _post_pan(self, url: str, *, params: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        response = _request_with_retries(
            "POST",
            url,
            params={**params, "access_token": self._token()},
            data=data,
            timeout=self.config.timeout_seconds,
        )
        return _json_response(response)

    def _upload_part(self, path: str, upload_id: str, partseq: int, chunk: bytes) -> None:
        response = _request_with_retries(
            "POST",
            "https://d.pcs.baidu.com/rest/2.0/pcs/superfile2",
            params={
                "method": "upload",
                "openapi": "xpansdk",
                "access_token": self._token(),
                "path": path,
                "type": "tmpfile",
                "uploadid": upload_id,
                "partseq": str(partseq),
            },
            files={"file": ("blob", chunk, "application/octet-stream")},
            timeout=self.config.timeout_seconds,
        )
        data = _json_response(response)
        if data.get("error_code") or data.get("errno"):
            raise BaiduPanError(f"Baidu Pan part upload failed: {_safe_error(data)}")

    def _find_fs_id(self, path: str) -> str:
        parent = str(Path(path).parent).replace("\\", "/")
        name = Path(path).name
        response = _request_with_retries(
            "GET",
            "https://pan.baidu.com/rest/2.0/xpan/file",
            params={
                "method": "list",
                "openapi": "xpansdk",
                "access_token": self._token(),
                "dir": parent,
                "web": 1,
                "showempty": 0,
            },
            timeout=self.config.timeout_seconds,
        )
        data = _json_response(response)
        for item in data.get("list") or []:
            if item.get("server_filename") == name or item.get("path") == path:
                return str(item["fs_id"])
        raise BaiduPanError(f"Baidu Pan file not found: {path}")


def _request_with_retries(method: str, url: str, **kwargs: Any) -> httpx.Response:
    last_error: httpx.HTTPError | None = None
    for attempt in range(DEFAULT_HTTP_RETRIES + 1):
        try:
            return httpx.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt >= DEFAULT_HTTP_RETRIES:
                break
            time.sleep(min(5.0, 0.5 * (2**attempt)))
    raise BaiduPanError(f"Baidu Pan HTTP request failed after retries: {last_error}") from last_error


def _chunks(content: bytes, size: int = DEFAULT_CHUNK_SIZE):
    for start in range(0, len(content), size):
        yield content[start : start + size]


def _block_md5s(content: bytes) -> list[str]:
    if not content:
        return [hashlib.md5(b"").hexdigest()]
    return [hashlib.md5(chunk).hexdigest() for chunk in _chunks(content)]


def _json_response(response: httpx.Response, *, allow_api_error: bool = False) -> dict[str, Any]:
    try:
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        raise BaiduPanError(f"Baidu Pan HTTP response error: {exc}") from exc
    if not isinstance(data, dict):
        raise BaiduPanError("Baidu Pan response is not an object")
    if data.get("error_code") and not allow_api_error:
        raise BaiduPanError(f"Baidu Pan API error: {_safe_error(data)}")
    return data


def _safe_error(data: dict[str, Any]) -> str:
    safe = {key: value for key, value in data.items() if key not in {"access_token", "refresh_token"}}
    return json.dumps(safe, ensure_ascii=False)[:500]


def baidu_pan_health(db: Session | None = None) -> dict[str, Any]:
    config = load_baidu_pan_config(db)
    result: dict[str, Any] = {
        "configured": config.configured,
        "account_file": str(config.account_file) if config.account_file else None,
        "root_path": config.root_path,
        "has_access_token": bool(config.access_token),
        "has_refresh_token": bool(config.refresh_token),
        "has_client_id": bool(config.client_id),
        "has_client_secret": bool(config.client_secret),
    }
    if config.configured:
        started = time.time()
        quota = BaiduPanClient(config).quota()
        result["quota"] = {key: quota.get(key) for key in ("total", "used", "free", "expire")}
        result["latency_ms"] = round((time.time() - started) * 1000)
    return result
