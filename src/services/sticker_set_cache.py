"""贴纸包标题的进程内缓存。

同一个 set_name 在 TTL 内只向 Telegram 请求一次 getStickerSet。
标题缓存是 LRU。请求失败或标题为空时不写入缓存，下一条消息会再试（fail-open）。
同一 set_name 的并发请求会合并成一次 API 调用。

只在同一个 asyncio 事件循环里使用：get/put 本身没有 await。
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any, Callable, Optional

from utils.logger import logger

# 贴纸包标题很少改。一小时足够挡住同一包的重复查询，过期后会再拉一次。
DEFAULT_STICKER_SET_TITLE_TTL = 3600.0
DEFAULT_STICKER_SET_TITLE_SIZE = 512


class StickerSetTitleCache:
    """set_name → title，带 TTL 的 LRU。"""

    def __init__(
        self,
        maxsize: int = DEFAULT_STICKER_SET_TITLE_SIZE,
        ttl_seconds: float = DEFAULT_STICKER_SET_TITLE_TTL,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.maxsize = maxsize
        self.ttl_seconds = ttl_seconds
        self._clock = clock or time.monotonic
        self._entries: OrderedDict[str, tuple[float, str]] = OrderedDict()

    def get(self, set_name: str) -> Optional[str]:
        item = self._entries.get(set_name)
        if item is None:
            return None
        expires_at, title = item
        if expires_at <= self._clock():
            self._entries.pop(set_name, None)
            return None
        self._entries.move_to_end(set_name)
        return title

    def put(self, set_name: str, title: str) -> None:
        cleaned = (title or "").strip()
        if not set_name or not cleaned:
            return
        self._entries[set_name] = (self._clock() + self.ttl_seconds, cleaned)
        self._entries.move_to_end(set_name)
        while len(self._entries) > self.maxsize:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()


sticker_set_title_cache = StickerSetTitleCache()
_inflight: dict[str, "asyncio.Future[Optional[str]]"] = {}


def clear_sticker_set_title_cache() -> None:
    """清空标题缓存和进行中的请求。测试隔离用。"""
    sticker_set_title_cache.clear()
    _inflight.clear()


async def lookup_sticker_set_title(bot: Any, set_name: str) -> Optional[str]:
    """按 set_name 取贴纸包标题。命中缓存则不再调用 API。"""
    name = (set_name or "").strip()
    if not name:
        return None

    cached = sticker_set_title_cache.get(name)
    if cached is not None:
        logger.debug(f"clef: 贴纸包标题缓存命中 set={name}")
        return cached

    pending = _inflight.get(name)
    if pending is not None:
        return await pending

    loop = asyncio.get_running_loop()
    future: asyncio.Future[Optional[str]] = loop.create_future()
    _inflight[name] = future
    title: Optional[str] = None
    try:
        title = await _fetch_sticker_set_title(bot, name)
        if title:
            sticker_set_title_cache.put(name, title)
        return title
    finally:
        if not future.done():
            future.set_result(title)
        _inflight.pop(name, None)


async def _fetch_sticker_set_title(bot: Any, set_name: str) -> Optional[str]:
    """调用 getStickerSet。失败或没有标题时返回 None，不抛给调用方。"""
    try:
        sticker_set = await bot.get_sticker_set(set_name)
    except Exception as exc:
        logger.warning(
            f"clef: get_sticker_set 失败（fail-open） set={set_name}: {type(exc).__name__}"
        )
        return None

    raw_title = getattr(sticker_set, "title", None)
    if not isinstance(raw_title, str):
        return None
    title = raw_title.strip()
    return title or None
