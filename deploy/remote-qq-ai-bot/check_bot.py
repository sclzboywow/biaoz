#!/usr/bin/env python3
import asyncio
import sys

try:
    import app
    import ai.service
    print("import app: ok")
except Exception as e:
    print("import app: FAIL", e)
    sys.exit(1)

from bot_library import LibraryBotHandler


async def main():
    h = LibraryBotHandler()
    for msg in ["帮助", "GB50016", "大门"]:
        e = {
            "message_type": "private",
            "user_id": 5625523,
            "self_id": 2529213858,
            "message": msg,
        }
        r = await h.handle(e, "2529213858")
        print(msg, "OK" if r else "NONE")


asyncio.run(main())
