"""数据库模型测试"""

import sqlite3
from unittest.mock import patch

import pytest

from database.models import DatabaseManager


class TestDatabaseManager:
    """数据库管理器测试"""

    @pytest.fixture(autouse=True)
    def setup(self, temp_db_path):
        """每个测试前设置数据库"""
        self.db = DatabaseManager(temp_db_path)

    def test_database_init(self):
        """测试数据库初始化"""
        assert self.db is not None
        assert self.db.db_path is not None

    def test_add_to_blacklist(self, sample_chat_id, sample_user_id):
        """测试添加黑名单"""
        success = self.db.add_to_blacklist(
            chat_id=sample_chat_id,
            blacklist_type="link",
            content="https://spam.com",
            created_by=sample_user_id,
        )
        assert success is True

    def test_check_blacklist(self, sample_chat_id, sample_user_id):
        """测试检查黑名单"""
        # 先添加黑名单项
        self.db.add_to_blacklist(
            chat_id=sample_chat_id,
            blacklist_type="link",
            content="https://spam.com",
            created_by=sample_user_id,
        )

        # 检查是否在黑名单中
        is_blacklisted = self.db.check_blacklist(
            chat_id=sample_chat_id, blacklist_type="link", content="https://spam.com"
        )
        assert is_blacklisted is True

        # 检查不在黑名单中的项
        is_blacklisted = self.db.check_blacklist(
            chat_id=sample_chat_id, blacklist_type="link", content="https://notspam.com"
        )
        assert is_blacklisted is False

    def test_add_to_global_blacklist(self, sample_chat_id):
        """测试添加全局黑名单"""
        success = self.db.add_to_global_blacklist(
            blacklist_type="sticker",
            content="AgADAgADmqcx",
            contributed_by=sample_chat_id,
        )
        assert success is True

    def test_check_global_blacklist(self, sample_chat_id):
        """测试检查全局黑名单"""
        # 先添加
        self.db.add_to_global_blacklist(
            blacklist_type="sticker",
            content="AgADAgADmqcx",
            contributed_by=sample_chat_id,
        )

        # 检查
        is_blacklisted = self.db.check_global_blacklist(
            blacklist_type="sticker", content="AgADAgADmqcx"
        )
        assert is_blacklisted is True

    def test_group_settings(self, sample_chat_id):
        """测试群组设置"""
        # 获取默认设置
        settings = self.db.get_group_settings(sample_chat_id)
        assert settings["contribute_to_global"] is False
        assert settings["use_global_blacklist"] is True

        # 更新设置
        success = self.db.update_group_settings(
            chat_id=sample_chat_id, contribute_to_global=True, use_global_blacklist=True
        )
        assert success is True

        # 验证更新
        updated_settings = self.db.get_group_settings(sample_chat_id)
        assert updated_settings["contribute_to_global"] is True

    def test_ban_record(self, sample_chat_id, sample_user_id):
        """测试封禁记录"""
        ban_id = self.db.add_ban_record(
            chat_id=sample_chat_id,
            user_id=sample_user_id,
            reason="测试封禁",
            banned_by=987654321,
        )
        assert ban_id is not None
        assert ban_id > 0

    def test_increment_text_report_count(self, sample_chat_id, sample_user_id):
        """测试文本举报计数"""
        message_hash = "test_hash_123"

        # 第一次举报
        result = self.db.increment_text_report_count(
            chat_id=sample_chat_id, user_id=sample_user_id, message_hash=message_hash
        )
        assert result["report_count"] == 1
        assert result["should_add_to_blacklist"] is False

        # 第二次举报
        result = self.db.increment_text_report_count(
            chat_id=sample_chat_id, user_id=sample_user_id, message_hash=message_hash
        )
        assert result["report_count"] == 2
        assert result["should_add_to_blacklist"] is False

        # 第三次举报（应该触发黑名单）
        result = self.db.increment_text_report_count(
            chat_id=sample_chat_id, user_id=sample_user_id, message_hash=message_hash
        )
        assert result["report_count"] == 3
        assert result["should_add_to_blacklist"] is True

    def test_get_blacklist(self, sample_chat_id):
        """测试获取黑名单列表"""
        # 添加几个黑名单项
        self.db.add_to_blacklist(
            chat_id=sample_chat_id,
            blacklist_type="link",
            content="https://spam.com",
            created_by=123,
        )
        self.db.add_to_blacklist(
            chat_id=sample_chat_id, blacklist_type="sticker", content="sticker123", created_by=123
        )

        # 获取黑名单
        blacklist = self.db.get_blacklist(sample_chat_id)
        assert len(blacklist) == 2
        assert blacklist[0]["type"] in ["link", "sticker"]

    def test_increment_global_blacklist_usage(self):
        """测试增加通用黑名单使用次数"""
        # 添加到通用黑名单
        link = "https://global-spam.com"
        self.db.add_to_global_blacklist(
            blacklist_type="link", content=link, contributed_by=-1001234567890
        )

        # 增加使用次数
        result = self.db.increment_global_blacklist_usage("link", link)
        assert result is True

    def test_get_global_blacklist_stats(self):
        """测试获取通用黑名单统计"""
        # 添加一些通用黑名单项
        self.db.add_to_global_blacklist(
            blacklist_type="link", content="https://spam1.com", contributed_by=-1001234567890
        )
        self.db.add_to_global_blacklist(
            blacklist_type="link", content="https://spam2.com", contributed_by=-1001234567890
        )

        # 获取统计
        stats = self.db.get_global_blacklist_stats()
        assert "total_count" in stats
        assert stats["total_count"] >= 2
        assert "type_stats" in stats

    def test_get_group_log_channel(self, sample_chat_id):
        """测试获取群组记录频道"""
        # 设置记录频道
        channel_id = -1001111111111
        self.db.set_group_log_channel(sample_chat_id, channel_id)

        # 获取记录频道
        result = self.db.get_group_log_channel(sample_chat_id)
        assert result == channel_id

    def test_get_group_log_channel_not_set(self, sample_chat_id):
        """测试获取未设置的群组记录频道"""
        result = self.db.get_group_log_channel(sample_chat_id)
        assert result is None

    def test_add_action_log(self, sample_chat_id, sample_user_id):
        """测试添加操作日志"""
        log_id = self.db.add_action_log(
            chat_id=sample_chat_id,
            action_type="spam_report",
            user_id=sample_user_id,
            target_content="test content",
            reason="test reason",
        )
        assert log_id is not None
        assert log_id > 0

    def test_get_action_logs(self, sample_chat_id, sample_user_id):
        """测试获取操作日志"""
        # 添加几条日志
        self.db.add_action_log(
            chat_id=sample_chat_id,
            action_type="spam_report",
            user_id=sample_user_id,
            target_content="content1",
            reason="reason1",
        )
        self.db.add_action_log(
            chat_id=sample_chat_id,
            action_type="ban",
            user_id=sample_user_id,
            target_content="content2",
            reason="reason2",
        )

        # 获取日志
        logs = self.db.get_action_logs(sample_chat_id, limit=10)
        assert len(logs) == 2
        assert logs[0]["action_type"] in ["spam_report", "ban"]

    def test_get_group_contribution_count(self, sample_chat_id):
        """测试获取群组贡献计数"""
        # 添加贡献到通用黑名单
        self.db.add_to_global_blacklist(
            blacklist_type="link", content="https://spam1.com", contributed_by=sample_chat_id
        )
        self.db.add_to_global_blacklist(
            blacklist_type="link", content="https://spam2.com", contributed_by=sample_chat_id
        )

        # 获取贡献计数
        count = self.db.get_group_contribution_count(sample_chat_id)
        assert count == 2

    def test_get_text_report_info(self, sample_chat_id, sample_user_id):
        """测试获取文本举报信息"""
        message_hash = "test_hash_456"

        # 添加举报
        self.db.increment_text_report_count(
            chat_id=sample_chat_id, user_id=sample_user_id, message_hash=message_hash
        )

        # 获取举报信息
        info = self.db.get_text_report_info(sample_chat_id, sample_user_id, message_hash)
        assert info["report_count"] == 1
        assert info["is_blacklisted"] is False

    def test_get_contributing_groups(self):
        """测试获取贡献群组列表"""
        # 启用两个群组的贡献
        chat_id1 = -1001111111111
        chat_id2 = -1002222222222

        self.db.update_group_settings(
            chat_id1, contribute_to_global=True, use_global_blacklist=False
        )
        self.db.update_group_settings(
            chat_id2, contribute_to_global=True, use_global_blacklist=False
        )

        # 获取贡献群组
        groups = self.db.get_contributing_groups()
        assert chat_id1 in groups
        assert chat_id2 in groups

    def test_update_group_settings(self, sample_chat_id):
        """测试更新群组设置"""
        # 更新设置
        self.db.update_group_settings(
            chat_id=sample_chat_id, contribute_to_global=True, use_global_blacklist=True
        )

        # 验证更新
        settings = self.db.get_group_settings(sample_chat_id)
        assert settings["contribute_to_global"] is True
        assert settings["use_global_blacklist"] is True

    def test_add_to_blacklist_operational_error(self, sample_chat_id):
        """测试添加黑名单时的OperationalError处理"""
        # 模拟数据库操作错误
        with patch("sqlite3.connect") as mock_connect:
            mock_connect.side_effect = sqlite3.OperationalError("database is locked")

            # 尝试添加黑名单应该返回False而不是抛出异常
            result = self.db.add_to_blacklist(
                chat_id=sample_chat_id, blacklist_type="link", content="https://test.com", created_by=999
            )
            assert result is False

    def test_add_to_global_blacklist_database_error(self):
        """测试添加全局黑名单时的DatabaseError处理"""
        # 模拟数据库错误
        with patch("sqlite3.connect") as mock_connect:
            mock_connect.side_effect = sqlite3.DatabaseError("database error")

            # 尝试添加全局黑名单应该返回False而不是抛出异常
            result = self.db.add_to_global_blacklist(
                blacklist_type="link", content="https://test.com", contributed_by=-1001234567890
            )
            assert result is False

    def test_increment_text_report_integrity_error(self, sample_chat_id, sample_user_id):
        """测试增加举报计数时的IntegrityError处理"""
        # 模拟完整性约束错误
        with patch("sqlite3.connect") as mock_connect:
            mock_connect.side_effect = sqlite3.IntegrityError("UNIQUE constraint failed")

            # 尝试增加举报计数应该返回默认值而不是抛出异常
            result = self.db.increment_text_report_count(
                chat_id=sample_chat_id, user_id=sample_user_id, message_hash="test_hash"
            )
            assert result["report_count"] == 0
            assert result["is_blacklisted"] is False
            assert result["should_add_to_blacklist"] is False
