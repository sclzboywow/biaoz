from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import SystemSetting, TrustedSource


DEFAULT_SETTINGS: dict[str, dict[str, str]] = {
    "url_check_enabled": {
        "value": "true",
        "value_type": "bool",
        "label": "启用后台自动检查",
        "description": "开启后，后端定时检查非 manual 的 URL。",
    },
    "url_check_interval_seconds": {
        "value": "3600",
        "value_type": "int",
        "label": "自动检查间隔秒数",
        "description": "后台定时检查间隔，默认 3600 秒。",
    },
    "check_manual_in_batch": {
        "value": "false",
        "value_type": "bool",
        "label": "批量检查包含 manual URL",
        "description": "关闭时，全部检查不会处理 manual URL，避免大批量下载。",
    },
    "download_timeout_seconds": {
        "value": "30",
        "value_type": "int",
        "label": "下载超时秒数",
        "description": "单个 URL 请求和下载的超时时间。",
    },
    "default_import_frequency": {
        "value": "manual",
        "value_type": "string",
        "label": "CSV 导入默认频率",
        "description": "批量导入 URL 时默认使用 manual，避免立即自动采集。",
    },
    "storage_root": {
        "value": "./data/standard-docs",
        "value_type": "string",
        "label": "文件存储根目录",
        "description": "当前本地文件归档根目录。生产环境可改为挂载目录。",
    },
    "storage_auto_create": {
        "value": "true",
        "value_type": "bool",
        "label": "自动创建存储目录",
        "description": "开启后，存储根目录不存在时系统会尝试创建。移动盘场景可关闭，避免盘符错误时自动建错目录。",
    },
    "storage_pause_download_if_unavailable": {
        "value": "true",
        "value_type": "bool",
        "label": "存储不可用时暂停下载",
        "description": "开启后，移动盘未挂载或不可写时不下载文件，只记录检查日志并生成提醒。",
    },
    "storage_fallback_roots": {
        "value": "",
        "value_type": "string",
        "label": "存储兜底目录",
        "description": "主存储目录找不到归档文件时，按分号分隔的目录顺序尝试旧归档根目录，用于从移动盘过渡到本机存储。",
    },
    "wechat_webhook_url": {
        "value": "",
        "value_type": "secret",
        "label": "企业微信机器人 Webhook",
        "description": "V1.0 预留，后续用于更新提醒推送。",
    },
    "smtp_enabled": {
        "value": "false",
        "value_type": "bool",
        "label": "启用邮件提醒",
        "description": "V1.0 预留，后续用于邮件提醒。",
    },
}


def ensure_default_settings(db: Session) -> None:
    changed = False
    for key, data in DEFAULT_SETTINGS.items():
        existing = db.get(SystemSetting, key)
        if existing is None:
            db.add(SystemSetting(key=key, **data))
            changed = True
    if changed:
        db.commit()


def ensure_default_trusted_sources(db: Session) -> None:
    defaults = [
        {
            "source_name": "国标电子书库",
            "base_url": "https://ebook.chinabuilding.com.cn",
            "trust_level": "A",
            "trust_score": 100,
            "source_type": "标准规范可信目录源",
            "adapter_key": "guobiao_ebook",
            "capabilities": "list,detail,status,category,change",
            "is_status_authority": True,
            "crawl_mode": "目录页 + 详情页",
            "crawl_frequency": "weekly",
            "enabled": True,
            "remark": "V2.0 高可信标准状态源，优先采集公开元数据、状态、分类、目录和变更信息。",
        },
        {
            "source_name": "全国标准信息公共服务平台",
            "base_url": "https://std.samr.gov.cn",
            "trust_level": "A",
            "trust_score": 100,
            "source_type": "国家标准权威信息源",
            "adapter_key": "samr_std_public",
            "capabilities": "list,detail,status,category,online,download,change",
            "is_status_authority": True,
            "crawl_mode": "公开检索接口 + 详情接口 + 官方全文阅览入口",
            "crawl_frequency": "weekly",
            "enabled": True,
            "remark": "国家市场监督管理总局全国标准信息公共服务平台，采集国家标准元数据、状态、详情和官方全文在线阅览入口。",
        },
    ]
    changed = False
    for data in defaults:
        existing = db.query(TrustedSource).filter(TrustedSource.source_name == data["source_name"]).first()
        if existing is None:
            db.add(TrustedSource(**data))
            changed = True
            continue
        for field_name, value in data.items():
            if field_name in {"source_name", "enabled"}:
                continue
            if not getattr(existing, field_name):
                setattr(existing, field_name, value)
                changed = True
    if changed:
        db.commit()


def get_setting(db: Session, key: str, default: str | None = None) -> str | None:
    item = db.get(SystemSetting, key)
    return item.value if item else default


def get_bool_setting(db: Session, key: str, default: bool = False) -> bool:
    value = get_setting(db, key)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def get_int_setting(db: Session, key: str, default: int) -> int:
    value = get_setting(db, key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default
