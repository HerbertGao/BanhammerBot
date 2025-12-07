"""测试黑名单命令处理"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Chat, ChatMember, Message, Update, User
from telegram.constants import ChatMemberStatus

from handlers.blacklist_handler import BlacklistHandler


class TestBlacklistCommands:
    """测试黑名单命令"""

    @pytest.fixture(autouse=True)
    def setup(self, temp_db_path):
        """每个测试前设置"""
        self.handler = BlacklistHandler()
        self.handler.db.db_path = temp_db_path
        self.handler.db.init_database()

    @pytest.mark.asyncio
    async def test_handle_unban_command_success(self, sample_chat_id):
        """测试成功解封用户"""
        # 先封禁一个用户
        user_id = 123456
        self.handler.db.add_ban_record(
            chat_id=sample_chat_id, user_id=user_id, reason="test", banned_by=999
        )

        # 创建管理员消息
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = f"/unban {user_id}"
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.chat.type = "supergroup"
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)

        # Mock is_admin_or_creator to return True
        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.unban_chat_member = AsyncMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_unban_command(update, context)

            context.bot.unban_chat_member.assert_called_once()
            context.bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_handle_unban_command_not_admin(self, sample_chat_id):
        """测试非管理员解封"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/unban 123456"
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.from_user = User(id=888, first_name="User", is_bot=False)

        with patch.object(self.handler, "_is_admin_or_creator", return_value=False):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_unban_command(update, context)

            # 应该发送错误消息
            context.bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_handle_unban_command_invalid_user_id(self, sample_chat_id):
        """测试无效用户ID"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/unban abc"  # 无效ID
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_unban_command(update, context)

            # 应该发送错误消息
            context.bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_handle_blacklist_command(self, sample_chat_id):
        """测试查看黑名单命令"""
        # 添加一些黑名单项
        self.handler.db.add_to_blacklist(
            chat_id=sample_chat_id,
            blacklist_type="link",
            content="https://spam.com",
            created_by=999,
        )

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_blacklist_command(update, context)

            context.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_blacklist_command_empty(self, sample_chat_id):
        """测试空黑名单"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_blacklist_command(update, context)

            context.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_global_command_help(self, sample_chat_id):
        """测试全局命令帮助"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/global"
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_global_command(update, context)

            context.bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_handle_global_command_status(self, sample_chat_id):
        """测试查看全局黑名单状态"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/global status"
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_global_command(update, context)

            context.bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_handle_log_channel_command_status(self, sample_chat_id):
        """测试查看日志频道状态"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/log_channel"
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_log_channel_command(update, context)

            context.bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_handle_log_channel_command_set(self, sample_chat_id):
        """测试设置日志频道"""
        channel_id = -1001111111111

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = f"/log_channel {channel_id}"
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            with patch.object(self.handler, "_is_bot_admin", return_value=True):
                context = MagicMock()
                context.bot.send_message = AsyncMock()
                context.bot.id = 987654321

                await self.handler.handle_log_channel_command(update, context)

                context.bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_handle_log_channel_command_clear(self, sample_chat_id):
        """测试清除日志频道"""
        # 先设置频道
        self.handler.db.set_group_log_channel(sample_chat_id, -1001111111111)

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/log_channel clear"
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_log_channel_command(update, context)

            context.bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_handle_cleanup_command(self, sample_chat_id):
        """测试清理命令"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_cleanup_command(update, context)

            context.bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_is_admin_or_creator_admin(self):
        """测试检查管理员权限"""
        message = MagicMock(spec=Message)
        message.chat = MagicMock()
        message.chat.get_member = AsyncMock()

        admin_member = MagicMock(spec=ChatMember)
        admin_member.status = ChatMemberStatus.ADMINISTRATOR
        message.chat.get_member.return_value = admin_member
        message.from_user = MagicMock()
        message.from_user.id = 123

        result = await self.handler._is_admin_or_creator(message)
        assert result is True

    @pytest.mark.asyncio
    async def test_is_admin_or_creator_creator(self):
        """测试检查群主权限"""
        message = MagicMock(spec=Message)
        message.chat = MagicMock()
        message.chat.get_member = AsyncMock()

        creator_member = MagicMock(spec=ChatMember)
        creator_member.status = ChatMemberStatus.OWNER
        message.chat.get_member.return_value = creator_member
        message.from_user = MagicMock()
        message.from_user.id = 123

        result = await self.handler._is_admin_or_creator(message)
        assert result is True

    @pytest.mark.asyncio
    async def test_is_admin_or_creator_member(self):
        """测试普通成员"""
        message = MagicMock(spec=Message)
        message.chat = MagicMock()
        message.chat.get_member = AsyncMock()

        member = MagicMock(spec=ChatMember)
        member.status = ChatMemberStatus.MEMBER
        message.chat.get_member.return_value = member
        message.from_user = MagicMock()
        message.from_user.id = 123

        result = await self.handler._is_admin_or_creator(message)
        assert result is False

    @pytest.mark.asyncio
    async def test_is_admin_or_creator_none_from_user(self):
        """测试from_user为None的情况（频道消息）"""
        message = MagicMock(spec=Message)
        message.chat = MagicMock()
        message.from_user = None  # 频道消息没有from_user

        result = await self.handler._is_admin_or_creator(message)
        # 应该返回False而不是崩溃
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success_message(self, sample_chat_id):
        """测试发送成功消息"""
        message = MagicMock(spec=Message)
        message.chat = MagicMock()
        message.chat.id = sample_chat_id

        context = MagicMock()
        sent_message = MagicMock()
        context.bot.send_message = AsyncMock(return_value=sent_message)

        result = await self.handler._send_success_message(message, context, "Success!")

        context.bot.send_message.assert_called_once()
        assert result == sent_message

    @pytest.mark.asyncio
    async def test_send_error_message(self, sample_chat_id):
        """测试发送错误消息"""
        message = MagicMock(spec=Message)
        message.chat = MagicMock()
        message.chat.id = sample_chat_id

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await self.handler._send_error_message(message, context, "Error!")

        context.bot.send_message.assert_called_once()
