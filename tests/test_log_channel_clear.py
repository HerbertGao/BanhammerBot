"""测试日志频道清除功能"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Chat, Message, Update, User
from telegram.ext import ContextTypes

from database.models import DatabaseManager
from handlers.blacklist_handler import BlacklistHandler


class TestLogChannelClear:
    """测试日志频道清除功能"""

    @pytest.fixture
    def db(self, tmp_path):
        """创建临时数据库"""
        db_path = tmp_path / "test_log_channel.db"
        db = DatabaseManager(str(db_path))
        return db

    @pytest.fixture
    def handler(self, db):
        """创建处理器实例"""
        handler = BlacklistHandler()
        handler.db = db  # 使用临时数据库
        return handler

    @pytest.fixture
    def sample_chat_id(self):
        """测试用群组ID"""
        return -1001234567890

    @pytest.fixture
    def update(self, sample_chat_id):
        """创建模拟的Update对象"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.chat = MagicMock(spec=Chat)
        update.message.chat.id = sample_chat_id
        update.message.chat.type = "supergroup"
        update.message.from_user = MagicMock(spec=User)
        update.message.from_user.id = 123456789
        update.message.from_user.username = "test_user"
        update.message.reply_to_message = None
        update.message.delete = AsyncMock()

        # Mock管理员权限检查
        admin_member = MagicMock()
        admin_member.status = "administrator"
        update.message.chat.get_member = AsyncMock(return_value=admin_member)

        return update

    @pytest.fixture
    def context(self):
        """创建模拟的Context对象"""
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()
        context.bot.delete_message = AsyncMock()
        context.bot.get_chat_member = AsyncMock()

        # 模拟管理员权限
        admin_member = MagicMock()
        admin_member.status = "administrator"
        context.bot.get_chat_member.return_value = admin_member

        return context

    @pytest.mark.asyncio
    async def test_clear_log_channel(self, handler, update, context, sample_chat_id):
        """测试清除日志频道设置"""
        # 先设置一个日志频道
        handler.db.set_group_log_channel(sample_chat_id, -1001111111111)

        # 验证设置成功
        settings = handler.db.get_group_settings(sample_chat_id)
        assert settings["log_channel_id"] == -1001111111111

        # 清除日志频道
        update.message.text = "/log_channel clear"

        await handler.handle_log_channel_command(update, context)

        # 验证已清除
        settings = handler.db.get_group_settings(sample_chat_id)
        assert settings["log_channel_id"] is None

    @pytest.mark.asyncio
    async def test_clear_log_channel_when_none(self, handler, update, context, sample_chat_id):
        """测试清除未设置的日志频道"""
        # 确保没有设置日志频道
        settings = handler.db.get_group_settings(sample_chat_id)
        assert settings["log_channel_id"] is None

        # 尝试清除
        update.message.text = "/log_channel clear"

        await handler.handle_log_channel_command(update, context)

        # 验证仍然为None
        settings = handler.db.get_group_settings(sample_chat_id)
        assert settings["log_channel_id"] is None

    @pytest.mark.asyncio
    async def test_set_clear_set_log_channel(self, handler, update, context, sample_chat_id):
        """测试设置-清除-再设置日志频道"""
        # 第一次设置
        handler.db.set_group_log_channel(sample_chat_id, -1001111111111)
        settings = handler.db.get_group_settings(sample_chat_id)
        assert settings["log_channel_id"] == -1001111111111

        # 清除
        update.message.text = "/log_channel clear"
        await handler.handle_log_channel_command(update, context)
        settings = handler.db.get_group_settings(sample_chat_id)
        assert settings["log_channel_id"] is None

        # 再次设置
        handler.db.set_group_log_channel(sample_chat_id, -1002222222222)
        settings = handler.db.get_group_settings(sample_chat_id)
        assert settings["log_channel_id"] == -1002222222222

    def test_update_group_settings_with_none(self, db, sample_chat_id):
        """测试使用None更新群组设置"""
        # 先设置一个值
        db.set_group_log_channel(sample_chat_id, -1001111111111)
        settings = db.get_group_settings(sample_chat_id)
        assert settings["log_channel_id"] == -1001111111111

        # 使用None更新（清除）
        db.update_group_settings(sample_chat_id, log_channel_id=None)
        settings = db.get_group_settings(sample_chat_id)
        assert settings["log_channel_id"] is None

    def test_update_group_settings_without_log_channel_param(self, db, sample_chat_id):
        """测试不传递log_channel_id参数时保持当前值"""
        # 先设置一个值
        db.set_group_log_channel(sample_chat_id, -1001111111111)
        settings = db.get_group_settings(sample_chat_id)
        assert settings["log_channel_id"] == -1001111111111

        # 不传递log_channel_id参数，只更新其他设置
        db.update_group_settings(sample_chat_id, contribute_to_global=True)
        settings = db.get_group_settings(sample_chat_id)

        # log_channel_id应该保持不变
        assert settings["log_channel_id"] == -1001111111111
        # contribute_to_global应该已更新
        assert settings["contribute_to_global"] is True

    def test_update_group_settings_mixed(self, db, sample_chat_id):
        """测试混合更新多个设置"""
        # 初始设置
        db.update_group_settings(
            sample_chat_id,
            contribute_to_global=True,
            use_global_blacklist=True,
            log_channel_id=-1001111111111,
        )

        # 验证初始设置
        settings = db.get_group_settings(sample_chat_id)
        assert settings["contribute_to_global"] is True
        assert settings["use_global_blacklist"] is True
        assert settings["log_channel_id"] == -1001111111111

        # 更新部分设置（保留log_channel_id，更新其他）
        db.update_group_settings(sample_chat_id, contribute_to_global=False)

        settings = db.get_group_settings(sample_chat_id)
        assert settings["contribute_to_global"] is False
        assert settings["use_global_blacklist"] is True
        assert settings["log_channel_id"] == -1001111111111

        # 清除log_channel_id，保留其他设置
        db.update_group_settings(sample_chat_id, log_channel_id=None)

        settings = db.get_group_settings(sample_chat_id)
        assert settings["contribute_to_global"] is False
        assert settings["use_global_blacklist"] is True
        assert settings["log_channel_id"] is None
