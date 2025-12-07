"""速率限制工具"""

import asyncio
import time
from collections import defaultdict
from typing import Dict, Tuple

from utils.logger import logger


class RateLimiter:
    """基于时间窗口的速率限制器

    使用asyncio.Lock保护临界区，防止并发访问时的竞态条件
    """

    # 最大记录条目数（防止内存无限增长）
    MAX_ENTRIES = 10000

    def __init__(self):
        # 存储格式: {(user_id, action): [(timestamp1, timestamp2, ...)]}
        self._records: Dict[Tuple[int, str], list] = defaultdict(list)
        # 异步锁，保护_records的并发访问
        self._lock = asyncio.Lock()

    async def is_rate_limited(
        self, user_id: int, action: str, max_calls: int, window_seconds: int
    ) -> bool:
        """
        检查用户是否达到速率限制（异步方法，使用锁保护临界区）

        Args:
            user_id: 用户ID
            action: 操作类型（如 "spam_report", "blacklist_add"）
            max_calls: 时间窗口内最大调用次数
            window_seconds: 时间窗口大小（秒）

        Returns:
            True 如果超过限制，False 如果未超过
        """
        async with self._lock:
            current_time = time.time()
            key = (user_id, action)

            # 防止内存无限增长：如果总条目数超过限制，清理所有过期记录
            if len(self._records) >= self.MAX_ENTRIES:
                logger.warning(
                    f"速率限制器记录数达到 {len(self._records)}，执行全局清理"
                )
                await self.cleanup_expired(window_seconds)

            # 清理过期记录
            self._records[key] = [
                ts for ts in self._records[key] if current_time - ts < window_seconds
            ]

            # 检查是否超过限制
            if len(self._records[key]) >= max_calls:
                logger.warning(
                    f"用户 {user_id} 对操作 '{action}' 达到速率限制: "
                    f"{len(self._records[key])}/{max_calls} 次/{window_seconds}秒"
                )
                return True

            # 记录本次调用
            self._records[key].append(current_time)
            return False

    async def get_remaining_time(self, user_id: int, action: str, window_seconds: int) -> int:
        """
        获取距离速率限制解除的剩余时间（异步方法，使用锁保护）

        Args:
            user_id: 用户ID
            action: 操作类型
            window_seconds: 时间窗口大小（秒）

        Returns:
            剩余秒数，如果未被限制则返回0
        """
        async with self._lock:
            current_time = time.time()
            key = (user_id, action)

            # 清理过期记录
            self._records[key] = [
                ts for ts in self._records[key] if current_time - ts < window_seconds
            ]

            if not self._records[key]:
                return 0

            # 最早的记录时间
            oldest_record = min(self._records[key])
            elapsed = current_time - oldest_record
            remaining = window_seconds - elapsed

            return max(0, int(remaining))

    def reset(self, user_id: int, action: str = None):
        """
        重置用户的速率限制记录

        Args:
            user_id: 用户ID
            action: 操作类型，None则重置该用户的所有操作
        """
        if action is None:
            # 重置用户的所有操作
            keys_to_remove = [key for key in self._records if key[0] == user_id]
            for key in keys_to_remove:
                del self._records[key]
            logger.info(f"已重置用户 {user_id} 的所有速率限制记录")
        else:
            # 重置特定操作
            key = (user_id, action)
            if key in self._records:
                del self._records[key]
                logger.info(f"已重置用户 {user_id} 的操作 '{action}' 速率限制记录")

    async def cleanup_expired(self, window_seconds: int = 3600):
        """
        清理所有过期记录（异步方法，已被is_rate_limited调用，无需额外加锁）

        Args:
            window_seconds: 保留记录的时间窗口（秒），默认1小时
        """
        # 注意：此方法仅从is_rate_limited内部调用，锁已在外层获取
        current_time = time.time()
        keys_to_remove = []

        for key, timestamps in self._records.items():
            # 清理过期时间戳
            self._records[key] = [ts for ts in timestamps if current_time - ts < window_seconds]

            # 如果记录为空，标记删除
            if not self._records[key]:
                keys_to_remove.append(key)

        # 删除空记录
        for key in keys_to_remove:
            del self._records[key]

        if keys_to_remove:
            logger.info(f"清理了 {len(keys_to_remove)} 个过期的速率限制记录")


# 全局速率限制器实例
rate_limiter = RateLimiter()
