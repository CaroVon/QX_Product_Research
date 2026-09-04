"""
============================================================
内容安全基线（W5-6）：生图 prompt 黑名单
============================================================

轻量词表拦截（provider 侧审核之外的本地第一道）；
命中即 422 并记录日志（敏感操作可审计）。
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# 命中即拒绝的模式（大小写不敏感；持续补充）
_BLACKLIST: tuple[str, ...] = (
    "裸体", " Nude", "naked", "porn", "色情", "成人电影", "情色",
    "未成年.*裸", "child.*nude", "nsfw",
    "血腥", "gore", "斩首", "beheading", "尸体特写",
    "枪械制造", "炸弹制作", "how to make a bomb", "爆炸装置",
    "习近平", "毛泽东.*恶搞", "天安门.*事件", "六四",
    "邪教", "法轮",
)

_COMPILED = tuple(re.compile(p, re.IGNORECASE) for p in _BLACKLIST)


def check_prompt(text: str | None) -> str | None:
    """返回命中的违规描述；None=通过。命中同时落审计日志。"""
    if not text:
        return None
    for pat in _COMPILED:
        m = pat.search(text)
        if m:
            logger.warning("[content-safety] prompt 拦截 | hit=%r | text=%.120s", m.group(0), text)
            return f"包含受限内容（{m.group(0).strip()}），请调整描述"
    return None
