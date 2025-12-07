"""测试全局黑名单切换功能"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Message, Update, User

from handlers.blacklist_handler import BlacklistHandler


class TestGlobalBlacklistToggle:
    """测试全局黑名单切换"""

    @pytest.fixture(autouse=True)
    def setup(self, temp_db_path):
        """每个测试前设置"""
        self.handler = BlacklistHandler()
        self.handler.db.db_path = temp_db_path
        self.handler.db.init_database()

    @pytest.mark.asyncio
    async def test_show_global_status(self, sample_chat_id):
        """测试显示全局黑名单状态"""
        self.handler.db.update_group_settings(
            sample_chat_id, contribute_to_global=True, use_global_blacklist=True
        )

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/global status"
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.message_id = 100

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_global_command(update, context)

            # 验证发送了状态消息
            context.bot.send_message.assert_called()
            call_args = context.bot.send_message.call_args
            assert "群组通用黑名单设置" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_show_global_stats(self, sample_chat_id):
        """测试显示全局黑名单统计"""
        # 添加一些全局黑名单数据
        self.handler.db.add_to_global_blacklist("link", "https://spam.com", sample_chat_id)

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/global stats"
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.message_id = 100

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_global_command(update, context)

            # 验证发送了统计消息
            context.bot.send_message.assert_called()
            call_args = context.bot.send_message.call_args
            assert "通用黑名单统计" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_join_global_blacklist(self, sample_chat_id):
        """测试加入通用黑名单"""
        # 确保初始都为关闭
        self.handler.db.update_group_settings(
            sample_chat_id, contribute_to_global=False, use_global_blacklist=False
        )

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/global y"
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.message_id = 100

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_global_command(update, context)

            # 验证设置已更新
            settings = self.handler.db.get_group_settings(sample_chat_id)
            assert settings["contribute_to_global"] is True
            assert settings["use_global_blacklist"] is True

            # 验证发送了成功消息
            context.bot.send_message.assert_called()
            call_args = context.bot.send_message.call_args
            assert "成功加入" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_join_global_blacklist_already_joined(self, sample_chat_id):
        """测试已加入时再次加入"""
        # 先加入
        self.handler.db.update_group_settings(
            sample_chat_id, contribute_to_global=True, use_global_blacklist=True
        )

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/global y"
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.message_id = 100

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_global_command(update, context)

            # 验证发送了错误消息
            context.bot.send_message.assert_called()
            call_args = context.bot.send_message.call_args
            assert "已加入" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_exit_global_blacklist_no_contributions(self, sample_chat_id):
        """测试退出通用黑名单（无贡献数据）"""
        # 先加入
        self.handler.db.update_group_settings(
            sample_chat_id, contribute_to_global=True, use_global_blacklist=True
        )

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/global n"
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.message_id = 100

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_global_command(update, context)

            # 验证设置已更新
            settings = self.handler.db.get_group_settings(sample_chat_id)
            assert settings["contribute_to_global"] is False
            assert settings["use_global_blacklist"] is False

            # 验证发送了成功消息
            context.bot.send_message.assert_called()
            call_args = context.bot.send_message.call_args
            assert "成功退出" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_exit_global_blacklist_with_contributions(self, sample_chat_id):
        """测试退出通用黑名单（有贡献数据时）"""
        # 先加入并添加贡献
        self.handler.db.update_group_settings(
            sample_chat_id, contribute_to_global=True, use_global_blacklist=True
        )
        self.handler.db.add_to_global_blacklist("link", "https://spam.com", sample_chat_id)

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/global n"
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.message_id = 100

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_global_command(update, context)

            # 应该发送确认消息
            context.bot.send_message.assert_called()
            call_args = context.bot.send_message.call_args
            assert "确认退出" in call_args.kwargs["text"]

            # 验证设置未更改
            settings = self.handler.db.get_group_settings(sample_chat_id)
            assert settings["contribute_to_global"] is True

    @pytest.mark.asyncio
    async def test_exit_global_blacklist_not_joined(self, sample_chat_id):
        """测试未加入时退出"""
        # 确保未加入
        self.handler.db.update_group_settings(
            sample_chat_id, contribute_to_global=False, use_global_blacklist=False
        )

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/global n"
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.message_id = 100

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_global_command(update, context)

            # 验证发送了错误消息
            context.bot.send_message.assert_called()
            call_args = context.bot.send_message.call_args
            assert "未加入" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_confirm_exit_contribution(self, sample_chat_id):
        """测试确认退出贡献"""
        # 先加入并添加贡献
        self.handler.db.update_group_settings(
            sample_chat_id, contribute_to_global=True, use_global_blacklist=True
        )
        self.handler.db.add_to_global_blacklist("link", "https://spam.com", sample_chat_id)

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/global confirm"
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.message_id = 100

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_global_command(update, context)

            # 验证设置已更新
            settings = self.handler.db.get_group_settings(sample_chat_id)
            assert settings["contribute_to_global"] is False
            assert settings["use_global_blacklist"] is False

            # 验证发送了确认消息
            context.bot.send_message.assert_called()
            call_args = context.bot.send_message.call_args
            assert "已确认退出" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_confirm_exit_contribution_not_enabled(self, sample_chat_id):
        """测试未开启贡献时确认退出"""
        # 确保未开启贡献
        self.handler.db.update_group_settings(sample_chat_id, contribute_to_global=False)

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/global confirm"
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.message_id = 100

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_global_command(update, context)

            # 验证发送了错误消息
            context.bot.send_message.assert_called()
            call_args = context.bot.send_message.call_args
            assert "未开启" in call_args.kwargs["text"]
