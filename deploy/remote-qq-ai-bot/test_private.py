#!/usr/bin/env python3
import asyncio
from bot_library import LibraryBotHandler


async def main():
    h = LibraryBotHandler()
    event = {
        "message_type": "private",
        "user_id": 123456,
        "self_id": 2529213858,
        "message": "GB50016",
        "group_id": None,
    }
    r = await h.handle(event, "2529213858")
    if r:
        print("OK:", r[0][:300])
    else:
        print("NONE")


if __name__ == "__main__":
    asyncio.run(main())
