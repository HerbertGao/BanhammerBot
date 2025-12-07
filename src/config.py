import os
import re

from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


def _validate_bot_token(token: str | None) -> list[str]:
    """验证 Bot Token 格式

    Args:
        token: Bot Token 字符串

    Returns:
        list[str]: 验证错误列表（空列表表示验证通过）
    """
    errors = []

    if not token:
        errors.append("环境变量 BOT_TOKEN 未设置")
        return errors

    # Telegram Bot Token 格式: <bot_id>:<hash>
    # 示例: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890
    token_pattern = r"^\d+:[A-Za-z0-9_-]{35,}$"

    if not re.match(token_pattern, token):
        errors.append(
            f"BOT_TOKEN 格式无效。正确格式: <bot_id>:<hash> "
            f"(示例: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890)"
        )
        return errors

    # 检查长度
    if len(token) < 45:
        errors.append(
            f"BOT_TOKEN 长度可疑 ({len(token)} 字符)，"
            f"正常的 Telegram Bot Token 应该至少 45 字符"
        )

    return errors


def _parse_admin_user_ids():
    """解析管理员用户ID列表，提供清晰的错误消息

    Returns:
        list[int]: 管理员用户ID列表

    Raises:
        ValueError: 如果环境变量包含无效的用户ID
    """
    admin_ids_str = os.getenv("ADMIN_USER_IDS", "")
    if not admin_ids_str.strip():
        return []

    admin_ids = []
    for uid in admin_ids_str.split(","):
        uid = uid.strip()
        if not uid:
            continue
        try:
            admin_ids.append(int(uid))
        except ValueError as e:
            raise ValueError(
                f"环境变量 ADMIN_USER_IDS 包含无效的用户ID: '{uid}'. "
                f"请确保所有ID都是数字，使用逗号分隔。示例: ADMIN_USER_IDS=123456,789012"
            ) from e
    return admin_ids


class Config:
    """Bot 配置类"""

    # Bot Token
    BOT_TOKEN = os.getenv("BOT_TOKEN")

    # 日志配置
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    # 数据库配置
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///banhammer_bot.db")

    # 删除消息配置
    DELETE_CONFIG = {
        "auto_delete_spam": True,  # 自动删除垃圾消息
        "warn_before_delete": True,  # 删除前警告
        "warn_timeout": 30,  # 警告超时时间(秒)
        "delete_timeout": 60,  # 删除超时时间(秒)
    }

    # 权限配置
    PERMISSIONS = {
        "admin_only_commands": ["/ban", "/unban", "/config", "/spam"],  # 仅管理员可用命令
        "moderator_commands": ["/warn", "/delete"],  # 版主可用命令
    }

    # 黑名单配置
    BLACKLIST_CONFIG = {
        "auto_ban_on_blacklist": True,  # 在黑名单中自动封禁
        "ban_duration": 0,  # 封禁时长(0为永久封禁)
        "log_actions": True,  # 记录操作到频道
        "auto_delete_confirmation_delay": 10,  # 自动删除确认消息的延迟(秒)
        "text_spam_threshold": 3,  # 文本消息被举报多少次后自动加入黑名单
    }

    # 私聊转发配置
    PRIVATE_FORWARD_CONFIG = {
        "enabled": True,  # 是否启用私聊转发功能
        "admin_user_ids": _parse_admin_user_ids(),  # 解析管理员用户ID列表
        "auto_add_to_contributing_groups": True,  # 自动添加到所有贡献群组
        "auto_add_to_global": True,  # 自动添加到通用黑名单
    }

    # 网络配置
    NETWORK_CONFIG = {
        "use_proxy": False,  # 是否使用代理
        "proxy_url": None,  # 代理URL (例如: http://127.0.0.1:7890)
        "timeout": 30,  # 连接超时时间(秒)
        "retry_count": 3,  # 重试次数
    }

    # 速率限制配置
    RATE_LIMIT_CONFIG = {
        "enabled": True,  # 是否启用速率限制
        "max_entries": 10000,  # 速率限制器最大记录数（防止内存无限增长）
        "spam_report": {
            "max_calls": 5,  # 最大调用次数
            "window_seconds": 60,  # 时间窗口（秒）
        },
        "blacklist_add": {
            "max_calls": 10,  # 最大调用次数
            "window_seconds": 60,  # 时间窗口（秒）
        },
        "private_forward": {
            "max_calls": 20,  # 最大调用次数
            "window_seconds": 300,  # 时间窗口（秒），5分钟
        },
        "cleanup": {
            "interval_seconds": 3600,  # 清理任务执行间隔（秒），默认1小时
            "retention_seconds": 3600,  # 保留记录的时间窗口（秒），默认1小时
        },
    }

    # 数据库清理配置
    DATABASE_CLEANUP_CONFIG = {
        "enabled": True,  # 是否启用定期数据库清理
        "hour": 3,  # 每日清理时间（小时，0-23）
        "minute": 0,  # 每日清理时间（分钟，0-59）
    }

    # 数据库重试配置
    DATABASE_RETRY_CONFIG = {
        "max_retries": 3,  # 最大重试次数
        "base_delay": 0.1,  # 基础延迟时间（秒）
        "max_delay": 2.0,  # 最大延迟时间（秒）
    }


def validate_config() -> tuple[bool, list[str]]:
    """验证配置完整性

    检查所有必需的环境变量是否正确设置

    Returns:
        tuple[bool, list[str]]: (验证是否通过, 错误/警告消息列表)
    """
    errors = []
    warnings = []

    # 验证 BOT_TOKEN（必需）
    token_errors = _validate_bot_token(Config.BOT_TOKEN)
    errors.extend(token_errors)

    # 验证 LOG_LEVEL（可选，但检查有效性）
    valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if Config.LOG_LEVEL.upper() not in valid_log_levels:
        warnings.append(
            f"LOG_LEVEL 值 '{Config.LOG_LEVEL}' 可能无效。" f"有效值: {', '.join(valid_log_levels)}"
        )

    # 验证 DATABASE_URL 格式（可选，但检查基本格式）
    if Config.DATABASE_URL and not (
        Config.DATABASE_URL.startswith("sqlite:")
        or Config.DATABASE_URL.startswith("postgresql:")
        or Config.DATABASE_URL.startswith("mysql:")
    ):
        warnings.append(
            f"DATABASE_URL 格式可能无效: {Config.DATABASE_URL}。"
            f"应以 sqlite:, postgresql:, 或 mysql: 开头"
        )

    # 验证 ADMIN_USER_IDS（可选，如果启用私聊转发功能则建议设置）
    if Config.PRIVATE_FORWARD_CONFIG.get("enabled") and not Config.PRIVATE_FORWARD_CONFIG.get(
        "admin_user_ids"
    ):
        warnings.append(
            "私聊转发功能已启用，但 ADMIN_USER_IDS 未设置。" "建议设置管理员ID以接收转发消息"
        )

    # 合并错误和警告
    all_messages = []
    if errors:
        all_messages.extend([f"❌ 错误: {err}" for err in errors])
    if warnings:
        all_messages.extend([f"⚠️  警告: {warn}" for warn in warnings])

    # 如果有错误则验证失败，仅有警告则通过
    is_valid = len(errors) == 0

    return is_valid, all_messages
