import os

from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


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
