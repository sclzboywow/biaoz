import asyncio
import contextlib
import logging
from pathlib import Path

from sqlalchemy import select

from app import models
from app.database import SessionLocal
from app.settings_store import get_bool_setting, get_int_setting
from app.url_checker import check_url_source

logger = logging.getLogger(__name__)


async def run_url_check_loop(interval_seconds: int, storage_root: Path, run_on_startup: bool = False) -> None:
    if interval_seconds <= 0:
        return

    if not run_on_startup:
        await asyncio.sleep(interval_seconds)

    while True:
        try:
            await asyncio.to_thread(check_all_sources_once, storage_root)
        except Exception:
            logger.exception("Scheduled URL check failed")
        await asyncio.sleep(interval_seconds)


def check_all_sources_once(storage_root: Path) -> None:
    with SessionLocal() as db:
        if not get_bool_setting(db, "url_check_enabled", True):
            return
        timeout_seconds = get_int_setting(db, "download_timeout_seconds", 30)
        sources = list(
            db.scalars(
                select(models.UrlSource)
                .where(models.UrlSource.check_frequency != "manual")
                .order_by(models.UrlSource.id)
            )
        )
        for source in sources:
            with contextlib.suppress(Exception):
                check_url_source(db, source, storage_root, timeout_seconds)
