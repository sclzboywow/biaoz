"""应急管理部政策公告 adapter."""

from __future__ import annotations

from app.batch2_adapters.gov_announcement_adapter import AnnouncementSourceConfig, register_announcement_adapter

MEM_BASE = "https://www.mem.gov.cn"

register_announcement_adapter(
    AnnouncementSourceConfig(
        adapter_key="mem_emergency_announcement_public",
        category_id="mem_emergency_announcement",
        category_name="应急管理政策公告",
        category_path="应急管理部 / 安全生产与标准征求意见",
        base_url=MEM_BASE,
        list_urls=(
            f"{MEM_BASE}/",
            f"{MEM_BASE}/gk/tzgg/",
            f"{MEM_BASE}/gk/zcjd/",
            f"{MEM_BASE}/gk/yjzj/",
        ),
        announce_types=("标准公告", "征求意见", "政策通知"),
    )
)
