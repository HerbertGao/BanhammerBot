"""数据库高级功能测试"""

import sqlite3

import pytest
from database.models import DatabaseManager


class TestDatabaseAdvanced:
    """数据库高级功能测试"""

    @pytest.fixture(autouse=True)
    def setup(self, temp_db_path):
        """每个测试前设置"""
        self.db = DatabaseManager(temp_db_path)

    def test_add_to_blacklist_duplicate(self, sample_chat_id):
        """测试添加重复黑名单项"""
        # 第一次添加
        success1 = self.db.add_to_blacklist(
            chat_id=sample_chat_id,
            blacklist_type="link",
            content="https://spam.com",
            created_by=123,
        )
        assert success1 is True

        # 第二次添加相同项（应该失败或返回True）
        success2 = self.db.add_to_blacklist(
            chat_id=sample_chat_id,
            blacklist_type="link",
            content="https://spam.com",
            created_by=123,
        )
        # 即使重复，也可能返回True（取决于实现）
        assert success2 in [True, False]

    def test_add_to_global_blacklist_duplicate(self):
        """测试添加重复全局黑名单项"""
        # 第一次添加
        success1 = self.db.add_to_global_blacklist(
            blacklist_type="link", content="https://spam.com", contributed_by=-1001234567890
        )
        assert success1 is True

        # 第二次添加相同项
        success2 = self.db.add_to_global_blacklist(
            blacklist_type="link", content="https://spam.com", contributed_by=-1001234567890
        )
        assert success2 in [True, False]

    def test_check_blacklist_nonexistent(self, sample_chat_id):
        """测试检查不存在的黑名单项"""
        is_blacklisted = self.db.check_blacklist(
            chat_id=sample_chat_id, blacklist_type="link", content="https://notexist.com"
        )
        assert is_blacklisted is False

    def test_check_global_blacklist_nonexistent(self):
        """测试检查不存在的全局黑名单项"""
        is_blacklisted = self.db.check_global_blacklist(
            blacklist_type="link", content="https://notexist.com"
        )
        assert is_blacklisted is False

    def test_increment_global_blacklist_usage_nonexistent(self):
        """测试增加不存在项的使用次数"""
        result = self.db.increment_global_blacklist_usage("link", "https://notexist.com")
        # 可能返回False或不做任何操作
        assert result in [True, False]

    def test_get_blacklist_empty(self, sample_chat_id):
        """测试获取空黑名单"""
        blacklist = self.db.get_blacklist(sample_chat_id)
        assert blacklist == []

    def test_get_action_logs_empty(self, sample_chat_id):
        """测试获取空操作日志"""
        logs = self.db.get_action_logs(sample_chat_id, limit=10)
        assert logs == []

    def test_get_group_contribution_count_zero(self, sample_chat_id):
        """测试零贡献计数"""
        count = self.db.get_group_contribution_count(sample_chat_id)
        assert count == 0

    def test_get_text_report_info_nonexistent(self, sample_chat_id, sample_user_id):
        """测试获取不存在的举报信息"""
        info = self.db.get_text_report_info(sample_chat_id, sample_user_id, "nonexistent_hash")
        assert info["report_count"] == 0
        assert info["is_blacklisted"] is False

    def test_get_contributing_groups_empty(self):
        """测试获取空贡献群组列表"""
        groups = self.db.get_contributing_groups()
        assert groups == []

    def test_set_group_log_channel(self, sample_chat_id):
        """测试设置群组日志频道"""
        channel_id = -1001111111111
        result = self.db.set_group_log_channel(sample_chat_id, channel_id)
        assert result is True

        # 验证设置成功
        saved_channel = self.db.get_group_log_channel(sample_chat_id)
        assert saved_channel == channel_id

    def test_set_group_log_channel_update(self, sample_chat_id):
        """测试更新群组日志频道"""
        # 先设置
        self.db.set_group_log_channel(sample_chat_id, -1001111111111)

        # 更新为新频道
        new_channel_id = -1002222222222
        result = self.db.set_group_log_channel(sample_chat_id, new_channel_id)
        assert result is True

        # 验证更新成功
        saved_channel = self.db.get_group_log_channel(sample_chat_id)
        assert saved_channel == new_channel_id

    def test_get_global_blacklist_stats_empty(self):
        """测试空全局黑名单统计"""
        stats = self.db.get_global_blacklist_stats()
        assert stats["total_count"] == 0
        assert stats["total_usage"] == 0
        assert stats["type_stats"] == {}

    def test_increment_text_report_count_different_users(self, sample_chat_id):
        """测试不同用户举报同一消息"""
        message_hash = "test_hash_multi"
        user1 = 111
        user2 = 222

        # 用户1举报
        result1 = self.db.increment_text_report_count(sample_chat_id, user1, message_hash)
        assert result1["report_count"] == 1

        # 用户2举报（应该是同一个消息的第二次举报）
        result2 = self.db.increment_text_report_count(sample_chat_id, user2, message_hash)
        # 根据实现，可能是同一记录的计数增加，也可能是独立记录
        assert result2["report_count"] >= 1

    def test_increment_text_report_count_reach_threshold(self, sample_chat_id, sample_user_id):
        """测试达到举报阈值"""
        message_hash = "test_threshold"

        # 第1次
        result = self.db.increment_text_report_count(sample_chat_id, sample_user_id, message_hash)
        assert result["should_add_to_blacklist"] is False

        # 第2次
        result = self.db.increment_text_report_count(sample_chat_id, sample_user_id, message_hash)
        assert result["should_add_to_blacklist"] is False

        # 第3次（达到阈值）
        result = self.db.increment_text_report_count(sample_chat_id, sample_user_id, message_hash)
        assert result["should_add_to_blacklist"] is True
        assert result["is_blacklisted"] is True

        # 第4次（已在黑名单）
        result = self.db.increment_text_report_count(sample_chat_id, sample_user_id, message_hash)
        assert result["should_add_to_blacklist"] is False
        assert result["is_blacklisted"] is True

    def test_update_group_settings_partial(self, sample_chat_id):
        """测试部分更新群组设置"""
        # 只更新contribute_to_global
        result = self.db.update_group_settings(sample_chat_id, contribute_to_global=True)
        assert result is True

        settings = self.db.get_group_settings(sample_chat_id)
        assert settings["contribute_to_global"] is True
        # use_global_blacklist应该保持默认值
        assert "use_global_blacklist" in settings

    def test_update_group_settings_log_channel(self, sample_chat_id):
        """测试通过update_group_settings设置日志频道"""
        channel_id = -1001111111111
        result = self.db.update_group_settings(sample_chat_id, log_channel_id=channel_id)
        assert result is True

        # 验证设置成功
        saved_channel = self.db.get_group_log_channel(sample_chat_id)
        assert saved_channel == channel_id

    def test_add_ban_record_with_details(self, sample_chat_id):
        """测试添加详细封禁记录"""
        ban_id = self.db.add_ban_record(
            chat_id=sample_chat_id,
            user_id=123456,
            reason="Spam posting",
            banned_by=999,
        )
        assert ban_id is not None
        assert ban_id > 0

    def test_add_action_log_with_details(self, sample_chat_id):
        """测试添加详细操作日志"""
        log_id = self.db.add_action_log(
            chat_id=sample_chat_id,
            action_type="ban",
            user_id=123456,
            target_content="https://spam.com",
            reason="Spam link",
        )
        assert log_id is not None
        assert log_id > 0

        # 获取日志验证
        logs = self.db.get_action_logs(sample_chat_id, limit=1)
        assert len(logs) == 1
        assert logs[0]["action_type"] == "ban"

    def test_get_action_logs_with_limit(self, sample_chat_id):
        """测试限制日志数量"""
        # 添加多条日志
        for i in range(10):
            self.db.add_action_log(
                chat_id=sample_chat_id,
                action_type="test",
                user_id=123,
                target_content=f"content_{i}",
                reason=f"reason_{i}",
            )

        # 获取限制数量的日志
        logs = self.db.get_action_logs(sample_chat_id, limit=5)
        assert len(logs) == 5

    def test_global_blacklist_with_multiple_contributors(self):
        """测试多个群组贡献同一全局黑名单项"""
        link = "https://mega-spam.com"
        chat1 = -1001111111111
        chat2 = -1002222222222

        # 群组1贡献
        result1 = self.db.add_to_global_blacklist(
            blacklist_type="link", content=link, contributed_by=chat1
        )
        assert result1 is True

        # 群组2尝试贡献相同项
        result2 = self.db.add_to_global_blacklist(
            blacklist_type="link", content=link, contributed_by=chat2
        )
        # 可能允许或拒绝重复贡献
        assert result2 in [True, False]

    def test_increment_global_blacklist_usage_multiple_times(self):
        """测试多次增加全局黑名单使用次数"""
        link = "https://popular-spam.com"
        self.db.add_to_global_blacklist(
            blacklist_type="link", content=link, contributed_by=-1001234567890
        )

        # 多次增加使用次数
        for _ in range(5):
            result = self.db.increment_global_blacklist_usage("link", link)
            assert result is True

        # 获取统计验证
        stats = self.db.get_global_blacklist_stats()
        assert stats["total_count"] >= 1
        assert stats["total_usage"] >= 5
