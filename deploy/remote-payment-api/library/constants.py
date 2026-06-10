#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

TICKET_PACKS = {
    "ticket_1": {
        "name": "单次下载券",
        "ticket_count": 1,
        "amount_cent": 199,
    },
    "ticket_10": {
        "name": "标准下载券包",
        "ticket_count": 10,
        "amount_cent": 990,
    },
    "ticket_25": {
        "name": "高频下载券包",
        "ticket_count": 25,
        "amount_cent": 1990,
    },
}

SEARCH_SESSION_TTL_SECONDS = 300
ORDER_EXPIRE_SECONDS = 600
RESEND_WINDOW_SECONDS = 86400


def free_download_enabled() -> bool:
    return os.getenv("LIBRARY_FREE_DOWNLOAD", "false").lower() in {"1", "true", "yes", "on"}
