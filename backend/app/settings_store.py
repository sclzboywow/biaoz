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
    "storage_backend": {
        "value": "local",
        "value_type": "string",
        "label": "文件库后端",
        "description": "文件归档后端：local=本地磁盘，baidu_pan=百度网盘，dual=本地和百度网盘双写。",
    },
    "baidu_pan_account_file": {
        "value": "./openxpanapi/账户信息.txt",
        "value_type": "string",
        "label": "百度网盘账号配置文件",
        "description": "本地账号配置文件路径。支持 AppKey/SecretKey/access_token/refresh_token 字段。",
    },
    "baidu_pan_root": {
        "value": "/apps/standard-docs",
        "value_type": "string",
        "label": "百度网盘归档根目录",
        "description": "百度网盘远端归档目录。普通第三方应用通常应位于 /apps/应用名/ 下。",
    },
    "baidu_pan_timeout_seconds": {
        "value": "120",
        "value_type": "int",
        "label": "百度网盘请求超时秒数",
        "description": "百度网盘上传、查询、下载接口超时时间。",
    },
    "baidu_pan_access_token": {
        "value": "",
        "value_type": "secret",
        "label": "百度网盘 Access Token",
        "description": "用户授权 access_token。可用环境变量 BAIDU_PAN_ACCESS_TOKEN 覆盖。",
    },
    "baidu_pan_refresh_token": {
        "value": "",
        "value_type": "secret",
        "label": "百度网盘 Refresh Token",
        "description": "用户授权 refresh_token。可用环境变量 BAIDU_PAN_REFRESH_TOKEN 覆盖。",
    },
    "baidu_pan_client_id": {
        "value": "",
        "value_type": "secret",
        "label": "百度网盘 Client ID",
        "description": "开放平台 AppKey。可用环境变量 BAIDU_PAN_CLIENT_ID 覆盖。",
    },
    "baidu_pan_client_secret": {
        "value": "",
        "value_type": "secret",
        "label": "百度网盘 Client Secret",
        "description": "开放平台 SecretKey。可用环境变量 BAIDU_PAN_CLIENT_SECRET 覆盖。",
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
    "ingest_enabled": {
        "value": "false",
        "value_type": "bool",
        "label": "启用文件入库",
        "description": "关闭后暂停新文件归档入库（含下载归档与批量 ingest），用于数据治理阶段。",
    },
    "governance_mode_enabled": {
        "value": "true",
        "value_type": "bool",
        "label": "数据治理模式",
        "description": "开启后优先执行来源画像与治理流程，默认配合关闭文件入库。",
    },
    "ocr_download_enabled": {
        "value": "true",
        "value_type": "bool",
        "label": "启用 OCR 受控下载",
        "description": "开启后允许 OCR worker 执行高价值标准资源的受控验证码下载。",
    },
    "ocr_max_attempts": {
        "value": "3",
        "value_type": "int",
        "label": "OCR 单任务最大尝试次数",
        "description": "单个 OCR 下载任务允许的最大验证码/OCR 尝试次数。",
    },
    "ocr_host_concurrency": {
        "value": "2",
        "value_type": "int",
        "label": "OCR 同 host 并发上限",
        "description": "同一下载 host 同时运行的 OCR 任务数上限。",
    },
    "ocr_source_hourly_limit": {
        "value": "20",
        "value_type": "int",
        "label": "OCR 单来源每小时上限",
        "description": "同一 trusted source 每小时最多创建的 OCR 任务数。",
    },
    "ocr_retry_delay_seconds": {
        "value": "300",
        "value_type": "int",
        "label": "OCR 失败重试间隔秒数",
        "description": "OCR/验证码失败后延迟重试的基础秒数，会乘以 attempt_count。",
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
        {
            "source_name": "行业标准信息服务平台",
            "base_url": "https://hbba.sacinfo.org.cn",
            "trust_level": "A",
            "trust_score": 100,
            "source_type": "行业标准权威备案信息源",
            "adapter_key": "samr_industry_standard_public",
            "capabilities": "list,status,category,change",
            "is_status_authority": True,
            "crawl_mode": "独立备案平台列表接口",
            "crawl_frequency": "weekly",
            "enabled": True,
            "remark": "全国标准信息公共服务平台导航的行业标准信息服务平台，作为独立可信源采集，使用独立限速和游标。",
        },
        {
            "source_name": "地方标准信息服务平台",
            "base_url": "https://dbba.sacinfo.org.cn",
            "trust_level": "A",
            "trust_score": 100,
            "source_type": "地方标准权威备案信息源",
            "adapter_key": "samr_local_standard_public",
            "capabilities": "list,status,category,change",
            "is_status_authority": True,
            "crawl_mode": "独立备案平台列表接口",
            "crawl_frequency": "weekly",
            "enabled": True,
            "remark": "全国标准信息公共服务平台导航的地方标准信息服务平台，作为独立可信源采集，使用独立限速和游标。",
        },
        {
            "source_name": "全国团体标准信息平台",
            "base_url": "https://www.ttbz.org.cn",
            "trust_level": "A",
            "trust_score": 95,
            "source_type": "团体标准公开信息源",
            "adapter_key": "samr_group_standard_public",
            "capabilities": "list,status,category,change",
            "is_status_authority": True,
            "crawl_mode": "独立平台公开查询接口",
            "crawl_frequency": "weekly",
            "enabled": False,
            "remark": "全国标准信息公共服务平台导航的团体标准信息平台；正文采集已停用（会员账户锁定）。",
        },
        {
            "source_name": "企业标准信息公共服务平台",
            "base_url": "https://www.qybz.org.cn",
            "trust_level": "A",
            "trust_score": 90,
            "source_type": "企业标准自我声明公开信息源",
            "adapter_key": "samr_enterprise_standard_public",
            "capabilities": "list,status,category",
            "is_status_authority": True,
            "crawl_mode": "独立平台公开 HTML 列表 + 详情页",
            "crawl_frequency": "weekly",
            "enabled": True,
            "remark": "全国标准信息公共服务平台导航的企业标准信息公共服务平台，作为独立可信源采集；该站宽泛搜索受限，当前使用首页公开列表和详情页结构化入库。",
        },
        {
            "source_name": "中国标准在线服务网",
            "base_url": "https://www.spc.org.cn",
            "trust_level": "A",
            "trust_score": 95,
            "source_type": "标准在线阅读与元数据可信补充源",
            "adapter_key": "spc_standard_online",
            "capabilities": "list,detail,status,category,online_reading,evidence",
            "is_status_authority": False,
            "crawl_mode": "独立慢速HTML列表 + 详情页 + 官方在线阅读入口验证；排除国际国外标准",
            "crawl_frequency": "weekly",
            "enabled": True,
            "remark": "SPC中国标准在线服务网作为独立补充可信源，采集国内国家、行业、地方、团体、企业、计量技术规范的列表和详情；在线阅读文件流需要会员登录态，默认不批量保存阅读流文件。",
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
        if existing.domain is None or existing.governance_status == "pending":
            from app.governance_service import derive_trusted_source_governance

            derive_trusted_source_governance(existing)
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
