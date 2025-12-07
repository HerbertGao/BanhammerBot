import sqlite3
import time
from functools import wraps
from typing import Callable, Dict, List, Optional, Tuple, TypedDict, Union

from config import Config
from utils.logger import logger


def retry_on_operational_error(
    max_retries: int = 3, base_delay: float = 0.1, max_delay: float = 2.0
) -> Callable:
    """装饰器：针对 SQLite OperationalError 进行重试

    OperationalError 通常是暂时性错误（如数据库锁定），使用指数退避策略重试可提高成功率。

    Args:
        max_retries: 最大重试次数（默认3次）
        base_delay: 基础延迟时间（秒，默认0.1）
        max_delay: 最大延迟时间（秒，默认2.0）

    Returns:
        装饰后的函数
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None

            for attempt in range(max_retries + 1):  # +1 因为第一次不是重试
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    last_error = e

                    # 如果是最后一次尝试，不再重试
                    if attempt >= max_retries:
                        logger.error(
                            f"{func.__name__} 失败（OperationalError，已重试 {max_retries} 次）: {e}",
                            exc_info=True,
                        )
                        raise

                    # 计算延迟时间（指数退避）
                    delay = min(base_delay * (2**attempt), max_delay)

                    logger.warning(
                        f"{func.__name__} 遇到 OperationalError（尝试 {attempt + 1}/{max_retries + 1}），"
                        f"{delay:.2f}s 后重试: {e}"
                    )

                    time.sleep(delay)

            # 不应该到这里，但为了类型安全
            raise last_error  # type: ignore

        return wrapper

    return decorator


# 哨兵值，用于区分"未提供参数"和"提供了None"
_UNSET = object()
_UnsetType = type(_UNSET)


# TypedDict 类型定义，提供更好的类型安全性
class GroupSettings(TypedDict):
    """群组设置"""

    contribute_to_global: bool
    use_global_blacklist: bool
    log_channel_id: Optional[int]


class GlobalBlacklistStats(TypedDict):
    """通用黑名单统计信息"""

    total_count: int
    type_stats: Dict[str, int]
    total_usage: int


class IncrementTextReportResult(TypedDict):
    """增加文字消息举报计数后的结果"""

    report_count: int
    is_blacklisted: bool
    should_add_to_blacklist: bool


class TextReportInfo(TypedDict):
    """文字消息举报信息（查询结果）"""

    report_count: int
    is_blacklisted: bool
    first_reported_at: Optional[str]
    last_reported_at: Optional[str]


class CleanupResult(TypedDict):
    """清理结果"""

    group_blacklist: int
    global_blacklist: int


class DatabaseManager:
    """数据库管理器

    线程安全说明:
    - SQLite 默认使用 SERIALIZED 模式，支持多线程并发访问
    - 此类为每个操作创建独立连接，避免连接共享导致的竞态条件
    - 每个数据库操作自动提交或回滚，保证事务原子性
    - 适合在异步环境(如 Telegram Bot)中安全使用
    """

    def __init__(self, db_path: str = "banhammer_bot.db"):
        """初始化数据库管理器

        注意：此类使用 sqlite3.connect() context manager 管理每次连接，
        每个数据库操作都创建并自动关闭连接，不维护持久连接。
        因此不需要 close() 方法或 __enter__/__exit__ 方法。
        """
        self.db_path = db_path
        # 避免循环导入，在初始化时延迟导入Config
        from config import Config

        self.text_spam_threshold = Config.BLACKLIST_CONFIG.get("text_spam_threshold", 3)

        # 群组设置缓存: {chat_id: (settings, expire_time)}
        # 默认缓存60秒，可减少50-80%的数据库查询
        self._settings_cache: Dict[int, Tuple[GroupSettings, float]] = {}
        self._cache_ttl = 60  # 缓存有效期（秒）

        self.init_database()

    def init_database(self):
        """初始化数据库表"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 创建群组黑名单表
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS group_blacklists (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        blacklist_type TEXT NOT NULL,  -- 'link', 'sticker', 'gif', 'bot'
                        blacklist_content TEXT NOT NULL,  -- 具体内容
                        created_by INTEGER NOT NULL,  -- 创建者用户ID
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(chat_id, blacklist_type, blacklist_content)
                    )
                """
                )

                # 创建通用黑名单表
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS global_blacklists (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        blacklist_type TEXT NOT NULL,  -- 'link', 'sticker', 'gif', 'bot'
                        blacklist_content TEXT NOT NULL,  -- 具体内容
                        contributed_by INTEGER NOT NULL,  -- 贡献群组ID
                        contributed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        usage_count INTEGER DEFAULT 0,  -- 使用次数
                        UNIQUE(blacklist_type, blacklist_content)
                    )
                """
                )

                # 创建群组设置表
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS group_settings (
                        chat_id INTEGER PRIMARY KEY,
                        contribute_to_global BOOLEAN DEFAULT 0,  -- 是否贡献到通用黑名单
                        use_global_blacklist BOOLEAN DEFAULT 1,  -- 是否使用通用黑名单
                        log_channel_id INTEGER NULL,  -- 群组记录频道ID
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """
                )

                # 创建封禁记录表
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ban_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        reason TEXT NOT NULL,
                        banned_by INTEGER NOT NULL,
                        banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        unbanned_at TIMESTAMP NULL,
                        unbanned_by INTEGER NULL,
                        is_active BOOLEAN DEFAULT 1
                    )
                """
                )

                # 创建操作日志表
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS action_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        action_type TEXT NOT NULL,  -- 'ban', 'unban', 'delete', 'spam_report', 'global_contribution'
                        user_id INTEGER NOT NULL,
                        target_content TEXT NULL,
                        reason TEXT NULL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """
                )

                # 创建文字消息举报计数表
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS text_report_counts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        message_hash TEXT NOT NULL,  -- 消息内容的哈希值
                        report_count INTEGER DEFAULT 1,  -- 举报次数
                        first_reported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_reported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_blacklisted BOOLEAN DEFAULT 0,  -- 是否已加入黑名单
                        UNIQUE(chat_id, user_id, message_hash)
                    )
                """
                )

                conn.commit()
                logger.info("数据库初始化完成")

        except Exception as e:
            logger.error(f"数据库初始化失败: {e}", exc_info=True)
            raise

    def add_to_blacklist(
        self, chat_id: int, blacklist_type: str, content: str, created_by: int
    ) -> bool:
        """添加内容到群组黑名单（带 OperationalError 重试）"""
        retry_config = Config.DATABASE_RETRY_CONFIG
        max_retries = retry_config.get("max_retries", 3)
        base_delay = retry_config.get("base_delay", 0.1)
        max_delay = retry_config.get("max_delay", 2.0)

        for attempt in range(max_retries + 1):
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO group_blacklists
                        (chat_id, blacklist_type, blacklist_content, created_by)
                        VALUES (?, ?, ?, ?)
                    """,
                        (chat_id, blacklist_type, content, created_by),
                    )
                    conn.commit()
                    logger.info(f"已添加黑名单项: {chat_id} - {blacklist_type} - {content}")
                    return True
            except sqlite3.IntegrityError as e:
                logger.warning(
                    f"黑名单项已存在或违反完整性约束: {chat_id} - {blacklist_type} - {content} | {e}"
                )
                return False
            except sqlite3.OperationalError as e:
                # OperationalError（如数据库锁定）可能是暂时性的，使用重试
                if attempt >= max_retries:
                    logger.error(
                        f"数据库操作错误（已重试 {max_retries} 次）: {e}",
                        exc_info=True,
                    )
                    return False

                # 指数退避
                delay = min(base_delay * (2**attempt), max_delay)
                logger.warning(
                    f"数据库操作错误（尝试 {attempt + 1}/{max_retries + 1}），"
                    f"{delay:.2f}s 后重试: {e}"
                )
                time.sleep(delay)
                continue  # 重试
            except sqlite3.DatabaseError as e:
                logger.error(f"数据库错误: {e}", exc_info=True)
                return False
            except Exception as e:
                logger.error(f"添加黑名单失败（未知错误）: {e}", exc_info=True)
                return False

        # 不应该到这里（所有重试都用尽会在上面的 if 块返回）
        return False

    def add_to_global_blacklist(
        self, blacklist_type: str, content: str, contributed_by: int
    ) -> bool:
        """添加内容到通用黑名单（带 OperationalError 重试）"""
        retry_config = Config.DATABASE_RETRY_CONFIG
        max_retries = retry_config.get("max_retries", 3)
        base_delay = retry_config.get("base_delay", 0.1)
        max_delay = retry_config.get("max_delay", 2.0)

        for attempt in range(max_retries + 1):
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO global_blacklists
                        (blacklist_type, blacklist_content, contributed_by)
                        VALUES (?, ?, ?)
                    """,
                        (blacklist_type, content, contributed_by),
                    )
                    conn.commit()
                    logger.info(f"已添加通用黑名单项: {blacklist_type} - {content}")
                    return True
            except sqlite3.IntegrityError as e:
                logger.warning(
                    f"通用黑名单项已存在或违反完整性约束: {blacklist_type} - {content} | {e}"
                )
                return False
            except sqlite3.OperationalError as e:
                # OperationalError（如数据库锁定）可能是暂时性的，使用重试
                if attempt >= max_retries:
                    logger.error(
                        f"数据库操作错误（已重试 {max_retries} 次）: {e}",
                        exc_info=True,
                    )
                    return False

                # 指数退避
                delay = min(base_delay * (2**attempt), max_delay)
                logger.warning(
                    f"数据库操作错误（尝试 {attempt + 1}/{max_retries + 1}），"
                    f"{delay:.2f}s 后重试: {e}"
                )
                time.sleep(delay)
                continue  # 重试
            except sqlite3.DatabaseError as e:
                logger.error(f"数据库错误: {e}", exc_info=True)
                return False
            except Exception as e:
                logger.error(f"添加通用黑名单失败（未知错误）: {e}", exc_info=True)
                return False

        # 不应该到这里（所有重试都用尽会在上面的 if 块返回）
        return False

    def check_global_blacklist(self, blacklist_type: str, content: str) -> bool:
        """检查内容是否在通用黑名单中"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT 1 FROM global_blacklists 
                    WHERE blacklist_type = ? AND blacklist_content = ?
                """,
                    (blacklist_type, content),
                )

                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"检查通用黑名单失败: {e}", exc_info=True)
            return False

    def increment_global_blacklist_usage(self, blacklist_type: str, content: str) -> bool:
        """增加通用黑名单使用次数"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE global_blacklists 
                    SET usage_count = usage_count + 1
                    WHERE blacklist_type = ? AND blacklist_content = ?
                """,
                    (blacklist_type, content),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新通用黑名单使用次数失败: {e}", exc_info=True)
            return False

    def get_group_settings(self, chat_id: int) -> GroupSettings:
        """获取群组设置（带60秒缓存）

        缓存策略:
        - 默认缓存60秒，可减少50-80%的数据库查询
        - 在 update_group_settings 时自动清除对应缓存
        - 适合高频调用场景（如每条消息都需要检查设置）
        """
        # 检查缓存
        current_time = time.time()
        if chat_id in self._settings_cache:
            settings, expire_time = self._settings_cache[chat_id]
            if current_time < expire_time:
                # 缓存未过期，直接返回
                return settings

        # 缓存过期或不存在，从数据库读取
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT contribute_to_global, use_global_blacklist, log_channel_id
                    FROM group_settings 
                    WHERE chat_id = ?
                """,
                    (chat_id,),
                )

                row = cursor.fetchone()
                if row:
                    settings: GroupSettings = {
                        "contribute_to_global": bool(row[0]),
                        "use_global_blacklist": bool(row[1]),
                        "log_channel_id": row[2],
                    }
                else:
                    # 如果不存在，创建默认设置
                    cursor.execute(
                        """
                        INSERT INTO group_settings (chat_id, contribute_to_global, use_global_blacklist, log_channel_id)
                        VALUES (?, 0, 1, NULL)
                    """,
                        (chat_id,),
                    )
                    conn.commit()
                    settings: GroupSettings = {
                        "contribute_to_global": False,
                        "use_global_blacklist": True,
                        "log_channel_id": None,
                    }

                # 更新缓存
                expire_time = time.time() + self._cache_ttl
                self._settings_cache[chat_id] = (settings, expire_time)
                return settings

        except Exception as e:
            logger.error(f"获取群组设置失败: {e}", exc_info=True)
            # 错误情况不缓存，直接返回默认值
            return {
                "contribute_to_global": False,
                "use_global_blacklist": True,
                "log_channel_id": None,
            }

    def update_group_settings(
        self,
        chat_id: int,
        contribute_to_global: Union[bool, _UnsetType] = _UNSET,
        use_global_blacklist: Union[bool, _UnsetType] = _UNSET,
        log_channel_id: Union[Optional[int], _UnsetType] = _UNSET,
    ) -> bool:
        """更新群组设置"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 获取当前设置
                current_settings = self.get_group_settings(chat_id)

                # 更新设置
                new_contribute = (
                    contribute_to_global
                    if contribute_to_global is not _UNSET
                    else current_settings["contribute_to_global"]
                )
                new_use_global = (
                    use_global_blacklist
                    if use_global_blacklist is not _UNSET
                    else current_settings["use_global_blacklist"]
                )
                new_log_channel = (
                    log_channel_id
                    if log_channel_id is not _UNSET
                    else current_settings["log_channel_id"]
                )

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO group_settings
                    (chat_id, contribute_to_global, use_global_blacklist, log_channel_id, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                    (chat_id, new_contribute, new_use_global, new_log_channel),
                )
                conn.commit()

                # 清除缓存，下次查询会重新从数据库读取
                if chat_id in self._settings_cache:
                    del self._settings_cache[chat_id]
                    logger.debug(f"已清除群组 {chat_id} 的设置缓存")

                logger.info(
                    f"已更新群组设置: {chat_id} - 贡献: {new_contribute}, 使用: {new_use_global}, 记录频道: {new_log_channel}"
                )
                return True
        except Exception as e:
            logger.error(f"更新群组设置失败: {e}", exc_info=True)
            return False

    def get_group_log_channel(self, chat_id: int) -> Optional[int]:
        """获取群组的记录频道ID"""
        try:
            settings = self.get_group_settings(chat_id)
            return settings.get("log_channel_id")
        except Exception as e:
            logger.error(f"获取群组记录频道失败: {e}", exc_info=True)
            return None

    def set_group_log_channel(self, chat_id: int, log_channel_id: Optional[int]) -> bool:
        """设置群组的记录频道ID（传入None表示清除设置）"""
        try:
            return self.update_group_settings(chat_id, log_channel_id=log_channel_id)
        except Exception as e:
            logger.error(f"设置群组记录频道失败: {e}", exc_info=True)
            return False

    def get_global_blacklist_stats(self) -> GlobalBlacklistStats:
        """获取通用黑名单统计信息"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 总数量
                cursor.execute("SELECT COUNT(*) FROM global_blacklists")
                total_count = cursor.fetchone()[0]

                # 按类型统计
                cursor.execute(
                    """
                    SELECT blacklist_type, COUNT(*) 
                    FROM global_blacklists 
                    GROUP BY blacklist_type
                """
                )
                type_stats = dict(cursor.fetchall())

                # 总使用次数
                cursor.execute("SELECT SUM(usage_count) FROM global_blacklists")
                total_usage = cursor.fetchone()[0] or 0

                return {
                    "total_count": total_count,
                    "type_stats": type_stats,
                    "total_usage": total_usage,
                }
        except Exception as e:
            logger.error(f"获取通用黑名单统计失败: {e}", exc_info=True)
            return {"total_count": 0, "type_stats": {}, "total_usage": 0}

    def remove_from_blacklist(self, chat_id: int, blacklist_type: str, content: str) -> bool:
        """从群组黑名单中移除内容"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    DELETE FROM group_blacklists 
                    WHERE chat_id = ? AND blacklist_type = ? AND blacklist_content = ?
                """,
                    (chat_id, blacklist_type, content),
                )
                conn.commit()
                logger.info(f"已移除黑名单项: {chat_id} - {blacklist_type} - {content}")
                return True
        except Exception as e:
            logger.error(f"移除黑名单失败: {e}", exc_info=True)
            return False

    def get_blacklist(self, chat_id: int) -> List[Dict]:
        """获取群组黑名单"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT blacklist_type, blacklist_content, created_by, created_at
                    FROM group_blacklists 
                    WHERE chat_id = ?
                    ORDER BY created_at DESC
                """,
                    (chat_id,),
                )

                results = []
                for row in cursor.fetchall():
                    results.append(
                        {
                            "type": row[0],
                            "content": row[1],
                            "created_by": row[2],
                            "created_at": row[3],
                        }
                    )
                return results
        except Exception as e:
            logger.error(f"获取黑名单失败: {e}", exc_info=True)
            return []

    def check_blacklist(self, chat_id: int, blacklist_type: str, content: str) -> bool:
        """检查内容是否在黑名单中"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT 1 FROM group_blacklists 
                    WHERE chat_id = ? AND blacklist_type = ? AND blacklist_content = ?
                """,
                    (chat_id, blacklist_type, content),
                )

                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"检查黑名单失败: {e}", exc_info=True)
            return False

    def add_ban_record(self, chat_id: int, user_id: int, reason: str, banned_by: int) -> int:
        """添加封禁记录"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO ban_records (chat_id, user_id, reason, banned_by)
                    VALUES (?, ?, ?, ?)
                """,
                    (chat_id, user_id, reason, banned_by),
                )
                conn.commit()
                ban_id = cursor.lastrowid
                logger.info(f"已添加封禁记录: {ban_id} - {user_id} - {reason}")
                return ban_id
        except Exception as e:
            logger.error(f"添加封禁记录失败: {e}", exc_info=True)
            return 0

    def unban_user(self, chat_id: int, user_id: int, unbanned_by: int) -> bool:
        """解除用户封禁"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE ban_records 
                    SET unbanned_at = CURRENT_TIMESTAMP, unbanned_by = ?, is_active = 0
                    WHERE chat_id = ? AND user_id = ? AND is_active = 1
                """,
                    (unbanned_by, chat_id, user_id),
                )
                conn.commit()
                logger.info(f"已解除封禁: {user_id}")
                return True
        except Exception as e:
            logger.error(f"解除封禁失败: {e}", exc_info=True)
            return False

    def is_user_banned(self, chat_id: int, user_id: int) -> bool:
        """检查用户是否被封禁"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT 1 FROM ban_records 
                    WHERE chat_id = ? AND user_id = ? AND is_active = 1
                """,
                    (chat_id, user_id),
                )

                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"检查封禁状态失败: {e}", exc_info=True)
            return False

    def add_action_log(
        self,
        chat_id: int,
        action_type: str,
        user_id: int,
        target_content: str = None,
        reason: str = None,
    ) -> int:
        """添加操作日志，返回日志ID"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO action_logs (chat_id, action_type, user_id, target_content, reason)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (chat_id, action_type, user_id, target_content, reason),
                )
                conn.commit()
                log_id = cursor.lastrowid
                logger.info(f"已添加操作日志: {log_id} - {action_type} - {user_id}")
                return log_id
        except Exception as e:
            logger.error(f"添加操作日志失败: {e}", exc_info=True)
            return 0

    def get_action_logs(self, chat_id: int, limit: int = 50) -> List[Dict]:
        """获取操作日志"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT action_type, user_id, target_content, reason, timestamp
                    FROM action_logs 
                    WHERE chat_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """,
                    (chat_id, limit),
                )

                results = []
                for row in cursor.fetchall():
                    results.append(
                        {
                            "action_type": row[0],
                            "user_id": row[1],
                            "target_content": row[2],
                            "reason": row[3],
                            "timestamp": row[4],
                        }
                    )
                return results
        except Exception as e:
            logger.error(f"获取操作日志失败: {e}", exc_info=True)
            return []

    def remove_group_contributions(self, chat_id: int) -> bool:
        """删除群组贡献的所有通用黑名单数据"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 获取该群组贡献的数据数量
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM global_blacklists 
                    WHERE contributed_by = ?
                """,
                    (chat_id,),
                )
                count = cursor.fetchone()[0]

                # 删除该群组贡献的所有数据
                cursor.execute(
                    """
                    DELETE FROM global_blacklists 
                    WHERE contributed_by = ?
                """,
                    (chat_id,),
                )

                conn.commit()
                logger.info(f"已删除群组 {chat_id} 贡献的 {count} 条通用黑名单数据")
                return True
        except Exception as e:
            logger.error(f"删除群组贡献数据失败: {e}", exc_info=True)
            return False

    def get_group_contribution_count(self, chat_id: int) -> int:
        """获取群组贡献的通用黑名单数据数量"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM global_blacklists 
                    WHERE contributed_by = ?
                """,
                    (chat_id,),
                )
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"获取群组贡献数量失败: {e}", exc_info=True)
            return 0

    def increment_text_report_count(
        self, chat_id: int, user_id: int, message_hash: str
    ) -> IncrementTextReportResult:
        """增加文字消息举报计数，返回举报信息

        使用 BEGIN IMMEDIATE 事务确保原子性，避免竞态条件
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 使用 BEGIN IMMEDIATE 获取排他锁，避免竞态条件
                conn.execute("BEGIN IMMEDIATE")
                try:
                    cursor = conn.cursor()

                    # 尝试插入新记录，如果已存在则更新计数
                    cursor.execute(
                        """
                        INSERT INTO text_report_counts
                        (chat_id, user_id, message_hash, report_count, first_reported_at, last_reported_at)
                        VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        ON CONFLICT(chat_id, user_id, message_hash) DO UPDATE SET
                        report_count = report_count + 1,
                        last_reported_at = CURRENT_TIMESTAMP
                        RETURNING report_count, is_blacklisted
                    """,
                        (chat_id, user_id, message_hash),
                    )

                    result = cursor.fetchone()
                    if result:
                        report_count, is_blacklisted = result

                        # 判断是否应该添加到黑名单
                        should_add = report_count >= self.text_spam_threshold and not is_blacklisted

                        # 如果举报次数达到阈值且未加入黑名单，则标记为已加入黑名单
                        if should_add:
                            cursor.execute(
                                """
                                UPDATE text_report_counts
                                SET is_blacklisted = 1
                                WHERE chat_id = ? AND user_id = ? AND message_hash = ?
                            """,
                                (chat_id, user_id, message_hash),
                            )
                            is_blacklisted = True

                        # 提交整个事务
                        conn.commit()

                        return {
                            "report_count": report_count,
                            "is_blacklisted": bool(is_blacklisted),
                            "should_add_to_blacklist": should_add,
                        }
                    else:
                        conn.commit()
                        return {
                            "report_count": 1,
                            "is_blacklisted": False,
                            "should_add_to_blacklist": False,
                        }
                except sqlite3.IntegrityError as e:
                    conn.rollback()
                    logger.warning(f"违反唯一性约束: chat_id={chat_id}, user_id={user_id} | {e}")
                    raise
                except sqlite3.OperationalError as e:
                    conn.rollback()
                    logger.error(f"数据库操作错误（可能被锁定）: {e}", exc_info=True)
                    raise
                except Exception:
                    conn.rollback()
                    raise
        except sqlite3.IntegrityError as e:
            logger.warning(f"增加文字消息举报计数失败（完整性约束）: {e}")
            return {"report_count": 0, "is_blacklisted": False, "should_add_to_blacklist": False}
        except sqlite3.OperationalError as e:
            logger.error(f"增加文字消息举报计数失败（操作错误）: {e}", exc_info=True)
            return {"report_count": 0, "is_blacklisted": False, "should_add_to_blacklist": False}
        except sqlite3.DatabaseError as e:
            logger.error(f"增加文字消息举报计数失败（数据库错误）: {e}", exc_info=True)
            return {"report_count": 0, "is_blacklisted": False, "should_add_to_blacklist": False}
        except Exception as e:
            logger.error(f"增加文字消息举报计数失败（未知错误）: {e}", exc_info=True)
            return {"report_count": 0, "is_blacklisted": False, "should_add_to_blacklist": False}

    def get_text_report_info(self, chat_id: int, user_id: int, message_hash: str) -> TextReportInfo:
        """获取文字消息举报信息"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT report_count, is_blacklisted, first_reported_at, last_reported_at
                    FROM text_report_counts 
                    WHERE chat_id = ? AND user_id = ? AND message_hash = ?
                """,
                    (chat_id, user_id, message_hash),
                )

                row = cursor.fetchone()
                if row:
                    return {
                        "report_count": row[0],
                        "is_blacklisted": bool(row[1]),
                        "first_reported_at": row[2],
                        "last_reported_at": row[3],
                    }
                else:
                    return {
                        "report_count": 0,
                        "is_blacklisted": False,
                        "first_reported_at": None,
                        "last_reported_at": None,
                    }
        except Exception as e:
            logger.error(f"获取文字消息举报信息失败: {e}", exc_info=True)
            return {
                "report_count": 0,
                "is_blacklisted": False,
                "first_reported_at": None,
                "last_reported_at": None,
            }

    def cleanup_invalid_blacklist_items(self) -> CleanupResult:
        """清理无效的黑名单项"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 清理群组黑名单中的无效项
                cursor.execute(
                    """
                    DELETE FROM group_blacklists 
                    WHERE blacklist_content IS NULL 
                       OR blacklist_content = '' 
                       OR trim(blacklist_content) = ''
                """
                )
                group_deleted = cursor.rowcount

                # 清理通用黑名单中的无效项
                cursor.execute(
                    """
                    DELETE FROM global_blacklists 
                    WHERE blacklist_content IS NULL 
                       OR blacklist_content = '' 
                       OR trim(blacklist_content) = ''
                """
                )
                global_deleted = cursor.rowcount

                conn.commit()

                logger.info(
                    f"已清理无效黑名单项: 群组黑名单 {group_deleted} 项, 通用黑名单 {global_deleted} 项"
                )

                return {"group_blacklist": group_deleted, "global_blacklist": global_deleted}
        except Exception as e:
            logger.error(f"清理无效黑名单项失败: {e}", exc_info=True)
            return {"group_blacklist": 0, "global_blacklist": 0}

    def migrate_sticker_blacklist_to_file_unique_id(self) -> Dict[str, int]:
        """迁移Sticker黑名单从set_name到file_unique_id（需要手动处理）"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 获取所有基于set_name的Sticker黑名单项
                cursor.execute(
                    """
                    SELECT id, chat_id, blacklist_content, created_by, created_at
                    FROM group_blacklists 
                    WHERE blacklist_type = 'sticker'
                """
                )
                group_stickers = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT id, blacklist_content, contributed_by, contributed_at
                    FROM global_blacklists 
                    WHERE blacklist_type = 'sticker'
                """
                )
                global_stickers = cursor.fetchall()

                logger.info(
                    f"发现 {len(group_stickers)} 个群组Sticker黑名单项, {len(global_stickers)} 个通用Sticker黑名单项"
                )
                logger.warning("注意：从set_name迁移到file_unique_id需要手动处理，因为无法自动映射")

                return {
                    "group_stickers": len(group_stickers),
                    "global_stickers": len(global_stickers),
                    "migration_required": True,
                }
        except Exception as e:
            logger.error(f"检查Sticker黑名单迁移失败: {e}", exc_info=True)
            return {"group_stickers": 0, "global_stickers": 0, "migration_required": False}

    def get_contributing_groups(self) -> List[int]:
        """获取所有启用了通用黑名单贡献的群组ID列表"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT chat_id FROM group_settings 
                    WHERE contribute_to_global = 1
                """
                )

                results = [row[0] for row in cursor.fetchall()]
                logger.info(f"获取到 {len(results)} 个贡献群组")
                return results
        except Exception as e:
            logger.error(f"获取贡献群组失败: {e}", exc_info=True)
            return []
