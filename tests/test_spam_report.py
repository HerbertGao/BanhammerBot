"""测试垃圾消息举报功能"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from handlers.blacklist_handler import BlacklistHandler
from telegram import Chat, Message, Update, User


class TestSpamReport:
    """测试垃圾消息举报"""

    @pytest.fixture(autouse=True)
    def setup(self, temp_db_path):
        """每个测试前设置"""
        self.handler = BlacklistHandler()
        self.handler.db.db_path = temp_db_path
        self.handler.db.init_database()

    @pytest.mark.asyncio
    async def test_handle_spam_report_link(self, sample_chat_id):
        """测试举报链接"""
        # 创建包含链接的消息
        target_message = MagicMock(spec=Message)
        target_message.text = "https://spam.com"
        target_message.via_bot = None
        target_message.sticker = None
        target_message.animation = None
        target_message.from_user = User(id=888, first_name="Spammer", is_bot=False)
        target_message.message_id = 999
        target_message.delete = AsyncMock()

        # 创建举报消息
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/spam"
        update.message.reply_to_message = target_message
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)
        update.message.message_id = 1000
        update.message.delete = AsyncMock()

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.ban_chat_member = AsyncMock()
            context.bot.send_message = AsyncMock(return_value=MagicMock())

            await self.handler.handle_spam_report(update, context)

            # 验证删除和封禁
            target_message.delete.assert_called_once()
            context.bot.ban_chat_member.assert_called_once()

            # 验证添加到黑名单
            is_blacklisted = self.handler.db.check_blacklist(
                sample_chat_id, "link", "https://spam.com"
            )
            assert is_blacklisted is True

    @pytest.mark.asyncio
    async def test_handle_spam_report_sticker(self, sample_chat_id):
        """测试举报贴纸"""
        target_message = MagicMock(spec=Message)
        target_message.text = None
        target_message.via_bot = None
        target_message.sticker = MagicMock()
        target_message.sticker.file_unique_id = "StickerID123"
        target_message.animation = None
        target_message.from_user = User(id=888, first_name="Spammer", is_bot=False)
        target_message.message_id = 999
        target_message.delete = AsyncMock()

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/spam"
        update.message.reply_to_message = target_message
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)
        update.message.message_id = 1000
        update.message.delete = AsyncMock()

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.ban_chat_member = AsyncMock()
            context.bot.send_message = AsyncMock(return_value=MagicMock())

            await self.handler.handle_spam_report(update, context)

            # 验证添加到黑名单
            is_blacklisted = self.handler.db.check_blacklist(
                sample_chat_id, "sticker", "StickerID123"
            )
            assert is_blacklisted is True

    @pytest.mark.asyncio
    async def test_handle_spam_report_via_bot(self, sample_chat_id):
        """测试举报内联Bot消息"""
        bot_user = User(id=123456, first_name="SpamBot", is_bot=True)

        target_message = MagicMock(spec=Message)
        target_message.via_bot = bot_user
        target_message.text = "spam content"
        target_message.sticker = None
        target_message.animation = None
        target_message.from_user = User(id=888, first_name="User", is_bot=False)
        target_message.message_id = 999
        target_message.delete = AsyncMock()

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/spam"
        update.message.reply_to_message = target_message
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)
        update.message.message_id = 1000
        update.message.delete = AsyncMock()

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.ban_chat_member = AsyncMock()
            context.bot.send_message = AsyncMock(return_value=MagicMock())

            await self.handler.handle_spam_report(update, context)

            # 验证添加到黑名单
            is_blacklisted = self.handler.db.check_blacklist(sample_chat_id, "bot", "123456")
            assert is_blacklisted is True

    @pytest.mark.asyncio
    async def test_handle_spam_report_not_admin(self, sample_chat_id):
        """测试非管理员举报"""
        target_message = MagicMock(spec=Message)
        target_message.text = "spam"

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/spam"
        update.message.reply_to_message = target_message
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.from_user = User(id=888, first_name="User", is_bot=False)

        with patch.object(self.handler, "_is_admin_or_creator", return_value=False):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_spam_report(update, context)

            # 应该发送错误消息
            context.bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_handle_spam_report_no_reply(self, sample_chat_id):
        """测试没有回复消息的举报"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/spam"
        update.message.reply_to_message = None
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await self.handler.handle_spam_report(update, context)

        # 应该发送错误消息
        context.bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_handle_spam_report_unrecognized_type(self, sample_chat_id):
        """测试无法识别的消息类型"""
        target_message = MagicMock(spec=Message)
        target_message.text = None
        target_message.via_bot = None
        target_message.sticker = None
        target_message.animation = None

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/spam"
        update.message.reply_to_message = target_message
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_spam_report(update, context)

            # 应该发送错误消息
            context.bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_handle_spam_report_with_global_contribution(self, sample_chat_id):
        """测试启用全局贡献的举报"""
        # 启用全局贡献
        self.handler.db.update_group_settings(
            sample_chat_id, contribute_to_global=True, use_global_blacklist=True
        )

        target_message = MagicMock(spec=Message)
        target_message.text = "https://global-spam.com"
        target_message.via_bot = None
        target_message.sticker = None
        target_message.animation = None
        target_message.from_user = User(id=888, first_name="Spammer", is_bot=False)
        target_message.message_id = 999
        target_message.delete = AsyncMock()

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "/spam"
        update.message.reply_to_message = target_message
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)
        update.message.message_id = 1000
        update.message.delete = AsyncMock()

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.ban_chat_member = AsyncMock()
            context.bot.send_message = AsyncMock(return_value=MagicMock())

            await self.handler.handle_spam_report(update, context)

            # 验证添加到群组黑名单
            is_blacklisted = self.handler.db.check_blacklist(
                sample_chat_id, "link", "https://global-spam.com"
            )
            assert is_blacklisted is True

            # 验证添加到全局黑名单
            is_global_blacklisted = self.handler.db.check_global_blacklist(
                "link", "https://global-spam.com"
            )
            assert is_global_blacklisted is True

    @pytest.mark.asyncio
    async def test_handle_spam_report_none_message(self):
        """测试update.message为None的情况（不应崩溃）"""
        update = MagicMock(spec=Update)
        update.message = None

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        # 应该正常返回，不抛出异常
        await self.handler.handle_spam_report(update, context)

        # 验证没有发送任何消息
        context.bot.send_message.assert_not_called()
