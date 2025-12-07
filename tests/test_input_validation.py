"""测试输入验证"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Chat, Message, Update, User
from telegram.ext import ContextTypes

from handlers.blacklist_handler import BlacklistHandler


class TestInputValidation:
    """测试输入验证"""

    @pytest.fixture
    def handler(self):
        """创建处理器实例"""
        return BlacklistHandler()

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
        update.message.from_user.username = "test_admin"
        update.message.delete = AsyncMock()

        # Mock管理员权限
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
        context.bot.unban_chat_member = AsyncMock()
        context.bot.get_chat = AsyncMock()
        context.bot.get_chat_member = AsyncMock()
        context.bot.id = 987654321
        return context

    # ========== 用户ID验证测试 ==========

    @pytest.mark.asyncio
    async def test_unban_with_negative_user_id(self, handler, update, context):
        """测试负数用户ID被拒绝"""
        update.message.text = "/unban -12345"

        await handler.handle_unban_command(update, context)

        # 验证发送了错误消息
        context.bot.send_message.assert_called_once()
        args = context.bot.send_message.call_args[1]
        assert "必须是正整数" in args["text"]

    @pytest.mark.asyncio
    async def test_unban_with_zero_user_id(self, handler, update, context):
        """测试零用户ID被拒绝"""
        update.message.text = "/unban 0"

        await handler.handle_unban_command(update, context)

        # 验证发送了错误消息
        context.bot.send_message.assert_called_once()
        args = context.bot.send_message.call_args[1]
        assert "必须是正整数" in args["text"]

    @pytest.mark.asyncio
    async def test_unban_with_too_large_user_id(self, handler, update, context):
        """测试过大的用户ID被拒绝"""
        update.message.text = f"/unban {10**13}"  # 超过10^12的限制

        await handler.handle_unban_command(update, context)

        # 验证发送了错误消息
        context.bot.send_message.assert_called_once()
        args = context.bot.send_message.call_args[1]
        assert "超出有效范围" in args["text"]

    @pytest.mark.asyncio
    async def test_unban_with_invalid_user_id_format(self, handler, update, context):
        """测试无效格式的用户ID被拒绝"""
        update.message.text = "/unban abc123"

        await handler.handle_unban_command(update, context)

        # 验证发送了错误消息
        context.bot.send_message.assert_called_once()
        args = context.bot.send_message.call_args[1]
        assert "无效的用户ID格式" in args["text"]

    @pytest.mark.asyncio
    async def test_unban_with_valid_user_id(self, handler, update, context):
        """测试有效的用户ID被接受"""
        update.message.text = "/unban 123456789"

        await handler.handle_unban_command(update, context)

        # 验证调用了解除封禁
        context.bot.unban_chat_member.assert_called_once_with(
            chat_id=update.message.chat.id, user_id=123456789, only_if_banned=True
        )

    # ========== 频道ID验证测试 ==========

    @pytest.mark.asyncio
    async def test_log_channel_with_positive_channel_id(self, handler, update, context):
        """测试正数频道ID被拒绝"""
        update.message.text = "/log_channel 1234567890"

        await handler.handle_log_channel_command(update, context)

        # 验证发送了错误消息
        context.bot.send_message.assert_called_once()
        args = context.bot.send_message.call_args[1]
        assert "应该是负数" in args["text"]

    @pytest.mark.asyncio
    async def test_log_channel_with_zero_channel_id(self, handler, update, context):
        """测试零频道ID被拒绝"""
        update.message.text = "/log_channel 0"

        await handler.handle_log_channel_command(update, context)

        # 验证发送了错误消息
        context.bot.send_message.assert_called_once()
        args = context.bot.send_message.call_args[1]
        assert "应该是负数" in args["text"]

    @pytest.mark.asyncio
    async def test_log_channel_with_too_small_channel_id(self, handler, update, context):
        """测试过小的频道ID被拒绝"""
        update.message.text = f"/log_channel -{10**16}"

        await handler.handle_log_channel_command(update, context)

        # 验证发送了错误消息
        context.bot.send_message.assert_called_once()
        args = context.bot.send_message.call_args[1]
        assert "超出有效范围" in args["text"]

    @pytest.mark.asyncio
    async def test_log_channel_with_invalid_channel_id_format(self, handler, update, context):
        """测试无效格式的频道ID被拒绝"""
        update.message.text = "/log_channel -abc123"

        await handler.handle_log_channel_command(update, context)

        # 验证发送了错误消息
        context.bot.send_message.assert_called_once()
        args = context.bot.send_message.call_args[1]
        assert "无效的频道ID格式" in args["text"]

    @pytest.mark.asyncio
    async def test_log_channel_with_valid_channel_id(self, handler, update, context):
        """测试有效的频道ID被接受"""
        update.message.text = "/log_channel -1001234567890"

        # Mock频道验证成功
        channel_chat = MagicMock()
        channel_chat.type = "channel"
        channel_chat.title = "Test Channel"
        context.bot.get_chat.return_value = channel_chat

        bot_member = MagicMock()
        bot_member.status = "administrator"
        context.bot.get_chat_member.return_value = bot_member

        await handler.handle_log_channel_command(update, context)

        # 验证调用了get_chat验证频道
        context.bot.get_chat.assert_called_once_with(-1001234567890)

    # ========== 边界值测试 ==========

    @pytest.mark.asyncio
    async def test_unban_with_minimum_valid_user_id(self, handler, update, context):
        """测试最小有效用户ID (1)"""
        update.message.text = "/unban 1"

        await handler.handle_unban_command(update, context)

        # 应该成功调用unban
        context.bot.unban_chat_member.assert_called_once()

    @pytest.mark.asyncio
    async def test_unban_with_maximum_valid_user_id(self, handler, update, context):
        """测试最大有效用户ID (10^12)"""
        update.message.text = f"/unban {10**12}"

        await handler.handle_unban_command(update, context)

        # 应该成功调用unban
        context.bot.unban_chat_member.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_channel_with_typical_channel_id(self, handler, update, context):
        """测试典型的频道ID格式"""
        update.message.text = "/log_channel -1001234567890"

        # Mock频道验证
        channel_chat = MagicMock()
        channel_chat.type = "channel"
        channel_chat.title = "Test Channel"
        context.bot.get_chat.return_value = channel_chat

        bot_member = MagicMock()
        bot_member.status = "administrator"
        context.bot.get_chat_member.return_value = bot_member

        await handler.handle_log_channel_command(update, context)

        # 验证处理成功
        context.bot.get_chat.assert_called_once()
