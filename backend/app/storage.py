import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.settings_store import get_bool_setting, get_setting

_WINDOWS_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[/\\]")


@dataclass
class StorageStatus:
    root: Path
    available: bool
    exists: bool
    is_dir: bool
    writable: bool
    auto_create: bool
    pause_download_if_unavailable: bool
    message: str


def is_windows_drive_path(value: str | None) -> bool:
    return bool(value and _WINDOWS_DRIVE_PATH_RE.match(value.strip()))


def configured_storage_root(db: Session, fallback: Path) -> Path:
    raw_value = get_setting(db, "storage_root", str(fallback)) or str(fallback)
    if is_windows_drive_path(raw_value) and os.name != "nt":
        return fallback.expanduser().resolve()
    root = Path(raw_value).expanduser()
    if root.is_absolute():
        return root.resolve()
    return (Path.cwd() / root).resolve()


def iter_storage_roots(db: Session, fallback: Path) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            resolved = path.expanduser()
        key = str(resolved)
        if key in seen:
            return
        seen.add(key)
        roots.append(resolved)

    add(configured_storage_root(db, fallback))
    add(fallback.expanduser())
    raw_fallbacks = get_setting(db, "storage_fallback_roots", "") or ""
    for item in raw_fallbacks.split(";"):
        item = item.strip()
        if item:
            add(Path(item))
    return roots


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_storage_root(db: Session, fallback: Path) -> StorageStatus:
    root = configured_storage_root(db, fallback)
    auto_create = get_bool_setting(db, "storage_auto_create", True)
    pause_download = get_bool_setting(db, "storage_pause_download_if_unavailable", True)

    try:
        if not root.exists() and auto_create:
            root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return StorageStatus(root, False, root.exists(), root.is_dir(), False, auto_create, pause_download, f"存储目录不可创建：{exc}")

    exists = root.exists()
    is_dir = root.is_dir()
    writable = False
    message = "存储目录可用"

    if not exists:
        message = "存储目录不存在"
    elif not is_dir:
        message = "存储路径不是目录"
    else:
        probe = root / ".storage_write_test"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            writable = True
        except OSError as exc:
            message = f"存储目录不可写：{exc}"

    available = exists and is_dir and writable
    return StorageStatus(root, available, exists, is_dir, writable, auto_create, pause_download, message)


def relative_storage_path(storage_root: Path, file_path: Path) -> str:
    try:
        return file_path.resolve().relative_to(storage_root.resolve()).as_posix()
    except ValueError:
        return str(file_path)


async def save_upload(upload: UploadFile, storage_root: Path, document_id: int) -> tuple[Path, int, str]:
    safe_name = Path(upload.filename or "upload.bin").name
    target_dir = storage_root / str(document_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{uuid4().hex}_{safe_name}"

    size = 0
    with target_path.open("wb") as file_obj:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            file_obj.write(chunk)

    return target_path, size, sha256_file(target_path)
