import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional, Any
from config import Config
from utils.logger import logger

class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self, db_path: str = "banhammer_bot.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """初始化数据库表"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 创建群组黑名单表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS group_blacklists (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        blacklist_type TEXT NOT NULL,  -- 'link', 'sticker', 'gif', 'bot'
                        blacklist_content TEXT NOT NULL,  -- 具体内容
                        created_by INTEGER NOT NULL,  -- 创建者用户ID
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(chat_id, blacklist_type, blacklist_content)
                    )
                ''')
                
                # 创建通用黑名单表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS global_blacklists (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        blacklist_type TEXT NOT NULL,  -- 'link', 'sticker', 'gif', 'bot'
                        blacklist_content TEXT NOT NULL,  -- 具体内容
                        contributed_by INTEGER NOT NULL,  -- 贡献群组ID
                        contributed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        usage_count INTEGER DEFAULT 0,  -- 使用次数
                        UNIQUE(blacklist_type, blacklist_content)
                    )
                ''')
                
                # 创建群组设置表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS group_settings (
                        chat_id INTEGER PRIMARY KEY,
                        contribute_to_global BOOLEAN DEFAULT 0,  -- 是否贡献到通用黑名单
                        use_global_blacklist BOOLEAN DEFAULT 1,  -- 是否使用通用黑名单
                        log_channel_id INTEGER NULL,  -- 群组记录频道ID
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # 创建封禁记录表
                cursor.execute('''
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
                ''')
                
                # 创建操作日志表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS action_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        action_type TEXT NOT NULL,  -- 'ban', 'unban', 'delete', 'spam_report', 'global_contribution'
                        user_id INTEGER NOT NULL,
                        target_content TEXT NULL,
                        reason TEXT NULL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # 创建文字消息举报计数表
                cursor.execute('''
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
                ''')
                
                conn.commit()
                logger.info("数据库初始化完成")
                
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")
            raise
    
    def add_to_blacklist(self, chat_id: int, blacklist_type: str, content: str, created_by: int) -> bool:
        """添加内容到群组黑名单"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO group_blacklists 
                    (chat_id, blacklist_type, blacklist_content, created_by)
                    VALUES (?, ?, ?, ?)
                ''', (chat_id, blacklist_type, content, created_by))
                conn.commit()
                logger.info(f"已添加黑名单项: {chat_id} - {blacklist_type} - {content}")
                return True
        except Exception as e:
            logger.error(f"添加黑名单失败: {e}")
            return False
    
    def add_to_global_blacklist(self, blacklist_type: str, content: str, contributed_by: int) -> bool:
        """添加内容到通用黑名单"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO global_blacklists 
                    (blacklist_type, blacklist_content, contributed_by)
                    VALUES (?, ?, ?)
                ''', (blacklist_type, content, contributed_by))
                conn.commit()
                logger.info(f"已添加通用黑名单项: {blacklist_type} - {content}")
                return True
        except Exception as e:
            logger.error(f"添加通用黑名单失败: {e}")
            return False
    
    def check_global_blacklist(self, blacklist_type: str, content: str) -> bool:
        """检查内容是否在通用黑名单中"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT 1 FROM global_blacklists 
                    WHERE blacklist_type = ? AND blacklist_content = ?
                ''', (blacklist_type, content))
                
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"检查通用黑名单失败: {e}")
            return False
    
    def increment_global_blacklist_usage(self, blacklist_type: str, content: str) -> bool:
        """增加通用黑名单使用次数"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE global_blacklists 
                    SET usage_count = usage_count + 1
                    WHERE blacklist_type = ? AND blacklist_content = ?
                ''', (blacklist_type, content))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新通用黑名单使用次数失败: {e}")
            return False
    
    def get_group_settings(self, chat_id: int) -> Dict:
        """获取群组设置"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT contribute_to_global, use_global_blacklist, log_channel_id
                    FROM group_settings 
                    WHERE chat_id = ?
                ''', (chat_id,))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'contribute_to_global': bool(row[0]),
                        'use_global_blacklist': bool(row[1]),
                        'log_channel_id': row[2]
                    }
                else:
                    # 如果不存在，创建默认设置
                    cursor.execute('''
                        INSERT INTO group_settings (chat_id, contribute_to_global, use_global_blacklist, log_channel_id)
                        VALUES (?, 0, 1, NULL)
                    ''', (chat_id,))
                    conn.commit()
                    return {
                        'contribute_to_global': False,
                        'use_global_blacklist': True,
                        'log_channel_id': None
                    }
        except Exception as e:
            logger.error(f"获取群组设置失败: {e}")
            return {
                'contribute_to_global': False,
                'use_global_blacklist': True,
                'log_channel_id': None
            }
    
    def update_group_settings(self, chat_id: int, contribute_to_global: bool = None, 
                            use_global_blacklist: bool = None, log_channel_id: int = None) -> bool:
        """更新群组设置"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 获取当前设置
                current_settings = self.get_group_settings(chat_id)
                
                # 更新设置
                new_contribute = contribute_to_global if contribute_to_global is not None else current_settings['contribute_to_global']
                new_use_global = use_global_blacklist if use_global_blacklist is not None else current_settings['use_global_blacklist']
                new_log_channel = log_channel_id if log_channel_id is not None else current_settings['log_channel_id']
                
                cursor.execute('''
                    INSERT OR REPLACE INTO group_settings 
                    (chat_id, contribute_to_global, use_global_blacklist, log_channel_id, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (chat_id, new_contribute, new_use_global, new_log_channel))
                conn.commit()
                
                logger.info(f"已更新群组设置: {chat_id} - 贡献: {new_contribute}, 使用: {new_use_global}, 记录频道: {new_log_channel}")
                return True
        except Exception as e:
            logger.error(f"更新群组设置失败: {e}")
            return False
    
    def get_group_log_channel(self, chat_id: int) -> Optional[int]:
        """获取群组的记录频道ID"""
        try:
            settings = self.get_group_settings(chat_id)
            return settings.get('log_channel_id')
        except Exception as e:
            logger.error(f"获取群组记录频道失败: {e}")
            return None
    
    def set_group_log_channel(self, chat_id: int, log_channel_id: int) -> bool:
        """设置群组的记录频道ID"""
        try:
            return self.update_group_settings(chat_id, log_channel_id=log_channel_id)
        except Exception as e:
            logger.error(f"设置群组记录频道失败: {e}")
            return False
    
    def get_global_blacklist_stats(self) -> Dict:
        """获取通用黑名单统计信息"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 总数量
                cursor.execute('SELECT COUNT(*) FROM global_blacklists')
                total_count = cursor.fetchone()[0]
                
                # 按类型统计
                cursor.execute('''
                    SELECT blacklist_type, COUNT(*) 
                    FROM global_blacklists 
                    GROUP BY blacklist_type
                ''')
                type_stats = dict(cursor.fetchall())
                
                # 总使用次数
                cursor.execute('SELECT SUM(usage_count) FROM global_blacklists')
                total_usage = cursor.fetchone()[0] or 0
                
                return {
                    'total_count': total_count,
                    'type_stats': type_stats,
                    'total_usage': total_usage
                }
        except Exception as e:
            logger.error(f"获取通用黑名单统计失败: {e}")
            return {
                'total_count': 0,
                'type_stats': {},
                'total_usage': 0
            }
    
    def remove_from_blacklist(self, chat_id: int, blacklist_type: str, content: str) -> bool:
        """从群组黑名单中移除内容"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    DELETE FROM group_blacklists 
                    WHERE chat_id = ? AND blacklist_type = ? AND blacklist_content = ?
                ''', (chat_id, blacklist_type, content))
                conn.commit()
                logger.info(f"已移除黑名单项: {chat_id} - {blacklist_type} - {content}")
                return True
        except Exception as e:
            logger.error(f"移除黑名单失败: {e}")
            return False
    
    def get_blacklist(self, chat_id: int) -> List[Dict]:
        """获取群组黑名单"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT blacklist_type, blacklist_content, created_by, created_at
                    FROM group_blacklists 
                    WHERE chat_id = ?
                    ORDER BY created_at DESC
                ''', (chat_id,))
                
                results = []
                for row in cursor.fetchall():
                    results.append({
                        'type': row[0],
                        'content': row[1],
                        'created_by': row[2],
                        'created_at': row[3]
                    })
                return results
        except Exception as e:
            logger.error(f"获取黑名单失败: {e}")
            return []
    
    def check_blacklist(self, chat_id: int, blacklist_type: str, content: str) -> bool:
        """检查内容是否在黑名单中"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT 1 FROM group_blacklists 
                    WHERE chat_id = ? AND blacklist_type = ? AND blacklist_content = ?
                ''', (chat_id, blacklist_type, content))
                
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"检查黑名单失败: {e}")
            return False
    
    def add_ban_record(self, chat_id: int, user_id: int, reason: str, banned_by: int) -> int:
        """添加封禁记录"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO ban_records (chat_id, user_id, reason, banned_by)
                    VALUES (?, ?, ?, ?)
                ''', (chat_id, user_id, reason, banned_by))
                conn.commit()
                ban_id = cursor.lastrowid
                logger.info(f"已添加封禁记录: {ban_id} - {user_id} - {reason}")
                return ban_id
        except Exception as e:
            logger.error(f"添加封禁记录失败: {e}")
            return 0
    
    def unban_user(self, chat_id: int, user_id: int, unbanned_by: int) -> bool:
        """解除用户封禁"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE ban_records 
                    SET unbanned_at = CURRENT_TIMESTAMP, unbanned_by = ?, is_active = 0
                    WHERE chat_id = ? AND user_id = ? AND is_active = 1
                ''', (unbanned_by, chat_id, user_id))
                conn.commit()
                logger.info(f"已解除封禁: {user_id}")
                return True
        except Exception as e:
            logger.error(f"解除封禁失败: {e}")
            return False
    
    def is_user_banned(self, chat_id: int, user_id: int) -> bool:
        """检查用户是否被封禁"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT 1 FROM ban_records 
                    WHERE chat_id = ? AND user_id = ? AND is_active = 1
                ''', (chat_id, user_id))
                
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"检查封禁状态失败: {e}")
            return False
    
    def add_action_log(self, chat_id: int, action_type: str, user_id: int, 
                      target_content: str = None, reason: str = None) -> bool:
        """添加操作日志"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO action_logs (chat_id, action_type, user_id, target_content, reason)
                    VALUES (?, ?, ?, ?, ?)
                ''', (chat_id, action_type, user_id, target_content, reason))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"添加操作日志失败: {e}")
            return False
    
    def get_action_logs(self, chat_id: int, limit: int = 50) -> List[Dict]:
        """获取操作日志"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT action_type, user_id, target_content, reason, timestamp
                    FROM action_logs 
                    WHERE chat_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (chat_id, limit))
                
                results = []
                for row in cursor.fetchall():
                    results.append({
                        'action_type': row[0],
                        'user_id': row[1],
                        'target_content': row[2],
                        'reason': row[3],
                        'timestamp': row[4]
                    })
                return results
        except Exception as e:
            logger.error(f"获取操作日志失败: {e}")
            return [] 
    
    def remove_group_contributions(self, chat_id: int) -> bool:
        """删除群组贡献的所有通用黑名单数据"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 获取该群组贡献的数据数量
                cursor.execute('''
                    SELECT COUNT(*) FROM global_blacklists 
                    WHERE contributed_by = ?
                ''', (chat_id,))
                count = cursor.fetchone()[0]
                
                # 删除该群组贡献的所有数据
                cursor.execute('''
                    DELETE FROM global_blacklists 
                    WHERE contributed_by = ?
                ''', (chat_id,))
                
                conn.commit()
                logger.info(f"已删除群组 {chat_id} 贡献的 {count} 条通用黑名单数据")
                return True
        except Exception as e:
            logger.error(f"删除群组贡献数据失败: {e}")
            return False
    
    def get_group_contribution_count(self, chat_id: int) -> int:
        """获取群组贡献的通用黑名单数据数量"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*) FROM global_blacklists 
                    WHERE contributed_by = ?
                ''', (chat_id,))
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"获取群组贡献数量失败: {e}")
            return 0
    
    def increment_text_report_count(self, chat_id: int, user_id: int, message_hash: str) -> Dict:
        """增加文字消息举报计数，返回举报信息"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 尝试插入新记录，如果已存在则更新计数
                cursor.execute('''
                    INSERT INTO text_report_counts 
                    (chat_id, user_id, message_hash, report_count, first_reported_at, last_reported_at)
                    VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(chat_id, user_id, message_hash) DO UPDATE SET
                    report_count = report_count + 1,
                    last_reported_at = CURRENT_TIMESTAMP
                    RETURNING report_count, is_blacklisted
                ''', (chat_id, user_id, message_hash))
                
                result = cursor.fetchone()
                if result:
                    report_count, is_blacklisted = result
                    conn.commit()
                    
                    # 如果举报次数达到3次且未加入黑名单，则标记为已加入黑名单
                    if report_count >= 3 and not is_blacklisted:
                        cursor.execute('''
                            UPDATE text_report_counts 
                            SET is_blacklisted = 1
                            WHERE chat_id = ? AND user_id = ? AND message_hash = ?
                        ''', (chat_id, user_id, message_hash))
                        conn.commit()
                        is_blacklisted = True
                    
                    return {
                        'report_count': report_count,
                        'is_blacklisted': bool(is_blacklisted),
                        'should_add_to_blacklist': report_count >= 3 and not is_blacklisted
                    }
                else:
                    return {
                        'report_count': 1,
                        'is_blacklisted': False,
                        'should_add_to_blacklist': False
                    }
        except Exception as e:
            logger.error(f"增加文字消息举报计数失败: {e}")
            return {
                'report_count': 0,
                'is_blacklisted': False,
                'should_add_to_blacklist': False
            }
    
    def get_text_report_info(self, chat_id: int, user_id: int, message_hash: str) -> Dict:
        """获取文字消息举报信息"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT report_count, is_blacklisted, first_reported_at, last_reported_at
                    FROM text_report_counts 
                    WHERE chat_id = ? AND user_id = ? AND message_hash = ?
                ''', (chat_id, user_id, message_hash))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'report_count': row[0],
                        'is_blacklisted': bool(row[1]),
                        'first_reported_at': row[2],
                        'last_reported_at': row[3]
                    }
                else:
                    return {
                        'report_count': 0,
                        'is_blacklisted': False,
                        'first_reported_at': None,
                        'last_reported_at': None
                    }
        except Exception as e:
            logger.error(f"获取文字消息举报信息失败: {e}")
            return {
                'report_count': 0,
                'is_blacklisted': False,
                'first_reported_at': None,
                'last_reported_at': None
            } 
    
    def cleanup_invalid_blacklist_items(self) -> Dict[str, int]:
        """清理无效的黑名单项"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 清理群组黑名单中的无效项
                cursor.execute('''
                    DELETE FROM group_blacklists 
                    WHERE blacklist_content IS NULL 
                       OR blacklist_content = '' 
                       OR trim(blacklist_content) = ''
                ''')
                group_deleted = cursor.rowcount
                
                # 清理通用黑名单中的无效项
                cursor.execute('''
                    DELETE FROM global_blacklists 
                    WHERE blacklist_content IS NULL 
                       OR blacklist_content = '' 
                       OR trim(blacklist_content) = ''
                ''')
                global_deleted = cursor.rowcount
                
                conn.commit()
                
                logger.info(f"已清理无效黑名单项: 群组黑名单 {group_deleted} 项, 通用黑名单 {global_deleted} 项")
                
                return {
                    'group_blacklist': group_deleted,
                    'global_blacklist': global_deleted
                }
        except Exception as e:
            logger.error(f"清理无效黑名单项失败: {e}")
            return {'group_blacklist': 0, 'global_blacklist': 0}
    
    def migrate_sticker_blacklist_to_file_unique_id(self) -> Dict[str, int]:
        """迁移Sticker黑名单从set_name到file_unique_id（需要手动处理）"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 获取所有基于set_name的Sticker黑名单项
                cursor.execute('''
                    SELECT id, chat_id, blacklist_content, created_by, created_at
                    FROM group_blacklists 
                    WHERE blacklist_type = 'sticker'
                ''')
                group_stickers = cursor.fetchall()
                
                cursor.execute('''
                    SELECT id, blacklist_content, contributed_by, contributed_at
                    FROM global_blacklists 
                    WHERE blacklist_type = 'sticker'
                ''')
                global_stickers = cursor.fetchall()
                
                logger.info(f"发现 {len(group_stickers)} 个群组Sticker黑名单项, {len(global_stickers)} 个通用Sticker黑名单项")
                logger.warning("注意：从set_name迁移到file_unique_id需要手动处理，因为无法自动映射")
                
                return {
                    'group_stickers': len(group_stickers),
                    'global_stickers': len(global_stickers),
                    'migration_required': True
                }
        except Exception as e:
            logger.error(f"检查Sticker黑名单迁移失败: {e}")
            return {'group_stickers': 0, 'global_stickers': 0, 'migration_required': False} 
    
    def get_contributing_groups(self) -> List[int]:
        """获取所有启用了通用黑名单贡献的群组ID列表"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT chat_id FROM group_settings 
                    WHERE contribute_to_global = 1
                ''')
                
                results = [row[0] for row in cursor.fetchall()]
                logger.info(f"获取到 {len(results)} 个贡献群组")
                return results
        except Exception as e:
            logger.error(f"获取贡献群组失败: {e}")
            return [] 