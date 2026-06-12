"""国家能源局能源标准公告 adapter."""

from __future__ import annotations

from app.batch2_adapters.gov_announcement_adapter import AnnouncementSourceConfig, register_announcement_adapter

NEA_BASE = "https://www.nea.gov.cn"

register_announcement_adapter(
    AnnouncementSourceConfig(
        adapter_key="nea_energy_announcement_public",
        category_id="nea_energy_announcement",
        category_name="能源标准公告",
        category_path="国家能源局 / 能源标准管理",
        base_url=NEA_BASE,
        list_urls=(
            f"{NEA_BASE}/ztzl/nybz/bzgl/index.htm",
            f"{NEA_BASE}/ztzl/nybz/bzjh/index.htm",
            f"{NEA_BASE}/ztzl/nybz/bzgg/index.htm",
        ),
        announce_types=("标准公告", "标准计划", "废止目录"),
    )
)
