from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "标准规范与项目依据动态管理系统"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://biaoz:biaoz@localhost:5432/biaoz"
    allow_sqlite: bool = False
    storage_root: Path = Path("./data/standard-docs")
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    url_check_interval_seconds: int = 3600
    url_check_on_startup: bool = False
    collection_task_inline_worker: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
