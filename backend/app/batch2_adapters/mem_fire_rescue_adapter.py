"""国家消防救援局政策公告 adapter."""

from __future__ import annotations

from app.batch2_adapters.gov_announcement_adapter import AnnouncementSourceConfig, register_announcement_adapter

FIRE_BASE = "https://www.119.gov.cn"

register_announcement_adapter(
    AnnouncementSourceConfig(
        adapter_key="mem_fire_rescue_announcement_public",
        category_id="mem_fire_rescue_announcement",
        category_name="消防救援政策公告",
        category_path="国家消防救援局 / 政策法规与征求意见",
        base_url=FIRE_BASE,
        list_urls=(
            f"{FIRE_BASE}/",
            f"{FIRE_BASE}/zwgk/zcfg/",
            f"{FIRE_BASE}/zwgk/tzgg/",
            f"{FIRE_BASE}/zwgk/yjzj/",
        ),
        announce_types=("标准公告", "征求意见", "政策通知"),
    )
)
