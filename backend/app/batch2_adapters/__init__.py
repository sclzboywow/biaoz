"""Batch-2 trusted source adapters (engineering/industry enhancement sources)."""

from . import (  # noqa: F401
    cnca_certification_adapter,
    cnca_rb_adapter,
    mem_emergency_adapter,
    mem_fire_rescue_adapter,
    miit_standard_adapter,
    mot_transport_adapter,
    mwr_water_adapter,
    nea_energy_adapter,
    nrs_natural_resource_adapter,
)

BATCH2_ADAPTER_KEYS = (
    "mot_transport_standard_public",
    "mwr_water_standard_public",
    "cnca_rb_standard_public",
    "miit_standard_public",
    "nea_energy_announcement_public",
    "nrs_natural_resource_standard_public",
    "mem_fire_rescue_announcement_public",
    "mem_emergency_announcement_public",
    "cnca_certification_portal_public",
)
