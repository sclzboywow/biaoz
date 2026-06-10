#!/usr/bin/env python3
from pathlib import Path

ROOT = Path("/home/ubuntu/qq-ai-bot/ai")

# templates.py
p = ROOT / "templates.py"
text = p.read_text(encoding="utf-8")
marker = 'FALLBACK_REPLY = "我主要负责群内资料查询。请直接 @我 + 编号或名称，例如：GB50016。"'
if "FALLBACK_REPLY_PRIVATE" not in text:
    text = text.replace(
        marker,
        marker
        + '\n\nFALLBACK_REPLY_PRIVATE = "我主要负责资料查询。私聊直接发送标准号或名称即可，例如：GB50016。"',
        1,
    )
    p.write_text(text, encoding="utf-8")
    print("updated templates.py")

# prompts.py
p = ROOT / "prompts.py"
text = p.read_text(encoding="utf-8")
if "SMALLTALK_SYSTEM_PROMPT_PRIVATE" not in text:
    private = '''
SMALLTALK_SYSTEM_PROMPT_PRIVATE = """你是标准库助手的 QQ 私聊回复模块。
引导用户直接发送标准号或名称查询（私聊无需 @）。
不要引导去群聊、加微信或打开外链。不要编造网盘链接。
回复不超过 80 字。查资料发 GB50016；买券回复买1/买10/买25；余额回复余额。"""

'''
    text = text.replace("INTENT_SYSTEM_PROMPT", private + "INTENT_SYSTEM_PROMPT", 1)
    p.write_text(text, encoding="utf-8")
    print("updated prompts.py")

# service.py
p = ROOT / "service.py"
text = p.read_text(encoding="utf-8")
if "def is_private_scope" not in text:
    text = text.replace(
        "from ai.prompts import INTENT_SYSTEM_PROMPT, SMALLTALK_SYSTEM_PROMPT",
        "from ai.prompts import INTENT_SYSTEM_PROMPT, SMALLTALK_SYSTEM_PROMPT, SMALLTALK_SYSTEM_PROMPT_PRIVATE",
    )
    text = text.replace(
        "    FALLBACK_REPLY,\n",
        "    FALLBACK_REPLY,\n    FALLBACK_REPLY_PRIVATE,\n",
    )
    text = text.replace(
        "_repeat_cache: Dict[str, Tuple[str, str, float]] = {}\n",
        "_repeat_cache: Dict[str, Tuple[str, str, float]] = {}\n\n\n"
        "def is_private_scope(scope_id: str) -> bool:\n"
        '    return str(scope_id or "").startswith("private:")\n\n\n'
        "def fallback_reply(scope_id: str) -> str:\n"
        "    return FALLBACK_REPLY_PRIVATE if is_private_scope(scope_id) else FALLBACK_REPLY\n",
    )
    text = text.replace("return FALLBACK_REPLY, False", "return fallback_reply(group_id), False")
    text = text.replace(
        "            content, usage = await self._chat(\n                SMALLTALK_SYSTEM_PROMPT,",
        "            prompt = SMALLTALK_SYSTEM_PROMPT_PRIVATE if is_private_scope(group_id) else SMALLTALK_SYSTEM_PROMPT\n"
        "            content, usage = await self._chat(\n                prompt,",
    )
    p.write_text(text, encoding="utf-8")
    print("updated service.py")
else:
    print("service.py already ok")

print("done")
