import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class Config:
    """Bot 配置类"""
    
    # Bot Token
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    
    # 日志配置
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    
    # 数据库配置
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///banhammer_bot.db')
    
    # 垃圾消息检测配置
    SPAM_DETECTION = {
        'max_links_per_message': 3,  # 单条消息最大链接数
        'max_caps_percentage': 70,   # 大写字母最大百分比
        'min_message_length': 5,     # 最小消息长度
        'max_repetitive_chars': 5,   # 最大重复字符数
        'forbidden_words': [         # 禁止词汇列表
            'spam', 'scam', 'hack', 'free money', 'earn money fast'
        ]
    }
    
    # 删除消息配置
    DELETE_CONFIG = {
        'auto_delete_spam': True,    # 自动删除垃圾消息
        'warn_before_delete': True,  # 删除前警告
        'warn_timeout': 30,          # 警告超时时间(秒)
        'delete_timeout': 60,        # 删除超时时间(秒)
    }
    
    # 权限配置
    PERMISSIONS = {
        'admin_only_commands': ['/ban', '/unban', '/config', '/spam'],  # 仅管理员可用命令
        'moderator_commands': ['/warn', '/delete'],            # 版主可用命令
    }
    
    # 黑名单配置
    BLACKLIST_CONFIG = {
        'auto_ban_on_blacklist': True,  # 在黑名单中自动封禁
        'auto_ban_on_spam': True,       # 对垃圾消息自动封禁
        'ban_duration': 0,              # 封禁时长(0为永久封禁)
        'log_actions': True,            # 记录操作到频道
    }
    
    # 私聊转发配置
    PRIVATE_FORWARD_CONFIG = {
        'enabled': True,                # 是否启用私聊转发功能
        'admin_user_ids': [
            int(uid.strip()) for uid in os.getenv('ADMIN_USER_IDS', '').split(',') if uid.strip()
        ],
        'auto_add_to_contributing_groups': True,  # 自动添加到所有贡献群组
        'auto_add_to_global': True,     # 自动添加到通用黑名单
    }
    
    # 网络配置
    NETWORK_CONFIG = {
        'use_proxy': False,             # 是否使用代理
        'proxy_url': None,              # 代理URL (例如: http://127.0.0.1:7890)
        'timeout': 30,                  # 连接超时时间(秒)
        'retry_count': 3,               # 重试次数
    } 