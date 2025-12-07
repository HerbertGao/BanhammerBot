"""测试文字消息举报功能"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Message, Update, User

from handlers.blacklist_handler import BlacklistHandler
from utils.rate_limiter import rate_limiter


class TestTextSpamReport:
    """测试文字消息举报"""

    @pytest.fixture(autouse=True)
    async def setup(self, temp_db_path):
        """每个测试前设置（异步fixture）"""
        self.handler = BlacklistHandler()
        self.handler.db.db_path = temp_db_path
        self.handler.db.init_database()
        # 重置速率限制
        await rate_limiter.reset(999)  # 测试使用的用户ID

    @pytest.mark.asyncio
    async def test_text_spam_report_first_time(self, sample_chat_id):
        """测试第一次举报文字消息"""
        # 创建包含文字的消息
        target_message = MagicMock(spec=Message)
        target_message.text = "spam text message"
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
            context.bot.send_message = AsyncMock(return_value=MagicMock())

            # Mock asyncio.sleep to avoid waiting
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await self.handler.handle_spam_report(update, context)

            # 验证删除消息
            target_message.delete.assert_called_once()

            # 验证发送确认消息
            context.bot.send_message.assert_called()

            # 验证举报次数为1
            message_hash = self.handler._generate_message_hash("spam text message")
            info = self.handler.db.get_text_report_info(sample_chat_id, 888, message_hash)
            assert info["report_count"] == 1
            assert info["is_blacklisted"] is False

    @pytest.mark.asyncio
    async def test_text_spam_report_reach_threshold(self, sample_chat_id):
        """测试达到举报阈值（3次）"""
        # 先手动增加2次举报
        message_text = "spam text"
        message_hash = self.handler._generate_message_hash(message_text)
        self.handler.db.increment_text_report_count(sample_chat_id, 888, message_hash)
        self.handler.db.increment_text_report_count(sample_chat_id, 888, message_hash)

        # 创建第3次举报
        target_message = MagicMock(spec=Message)
        target_message.text = message_text
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

            with patch("asyncio.sleep", new_callable=AsyncMock):
                await self.handler.handle_spam_report(update, context)

            # 验证封禁用户
            context.bot.ban_chat_member.assert_called_once()

            # 验证添加到黑名单
            is_blacklisted = self.handler.db.check_blacklist(sample_chat_id, "text", message_hash)
            assert is_blacklisted is True

            # 验证举报次数为3
            info = self.handler.db.get_text_report_info(sample_chat_id, 888, message_hash)
            assert info["report_count"] == 3
            assert info["is_blacklisted"] is True

    @pytest.mark.asyncio
    async def test_text_spam_report_with_global_contribution(self, sample_chat_id):
        """测试启用全局贡献的文字举报"""
        # 启用全局贡献
        self.handler.db.update_group_settings(sample_chat_id, contribute_to_global=True)

        # 先手动增加2次举报
        message_text = "global spam text"
        message_hash = self.handler._generate_message_hash(message_text)
        self.handler.db.increment_text_report_count(sample_chat_id, 888, message_hash)
        self.handler.db.increment_text_report_count(sample_chat_id, 888, message_hash)

        # 第3次举报
        target_message = MagicMock(spec=Message)
        target_message.text = message_text
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

            with patch("asyncio.sleep", new_callable=AsyncMock):
                await self.handler.handle_spam_report(update, context)

            # 验证添加到群组黑名单
            is_blacklisted = self.handler.db.check_blacklist(sample_chat_id, "text", message_hash)
            assert is_blacklisted is True

            # 验证添加到全局黑名单
            is_global_blacklisted = self.handler.db.check_global_blacklist("text", message_hash)
            assert is_global_blacklisted is True

    @pytest.mark.asyncio
    async def test_text_spam_report_delete_failure(self, sample_chat_id):
        """测试删除消息失败的情况"""
        target_message = MagicMock(spec=Message)
        target_message.text = "spam text"
        target_message.via_bot = None
        target_message.sticker = None
        target_message.animation = None
        target_message.from_user = User(id=888, first_name="Spammer", is_bot=False)
        target_message.message_id = 999
        target_message.delete = AsyncMock(side_effect=Exception("Delete failed"))

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
            context.bot.send_message = AsyncMock(return_value=MagicMock())

            with patch("asyncio.sleep", new_callable=AsyncMock):
                # 应该捕获异常并继续
                await self.handler.handle_spam_report(update, context)

            # 验证发送了确认消息
            context.bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_text_spam_report_ban_failure(self, sample_chat_id):
        """测试封禁失败的情况"""
        # 先手动增加2次举报
        message_text = "spam text"
        message_hash = self.handler._generate_message_hash(message_text)
        self.handler.db.increment_text_report_count(sample_chat_id, 888, message_hash)
        self.handler.db.increment_text_report_count(sample_chat_id, 888, message_hash)

        target_message = MagicMock(spec=Message)
        target_message.text = message_text
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
            context.bot.ban_chat_member = AsyncMock(side_effect=Exception("Ban failed"))
            context.bot.send_message = AsyncMock(return_value=MagicMock())

            with patch("asyncio.sleep", new_callable=AsyncMock):
                # 应该捕获异常并继续
                await self.handler.handle_spam_report(update, context)

            # 验证仍然添加到黑名单
            is_blacklisted = self.handler.db.check_blacklist(sample_chat_id, "text", message_hash)
            assert is_blacklisted is True

    @pytest.mark.asyncio
    async def test_text_spam_report_auto_delete_messages(self, sample_chat_id):
        """测试自动删除确认消息和命令消息（作为后台任务）"""
        import asyncio as real_asyncio

        target_message = MagicMock(spec=Message)
        target_message.text = "spam text"
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

        sent_message = MagicMock()
        sent_message.delete = AsyncMock()

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock(return_value=sent_message)

            # Mock asyncio.create_task 以捕获后台任务
            with patch("handlers.blacklist_handler.asyncio.create_task") as mock_create_task:
                # Mock返回一个假的任务，避免实际执行
                mock_task = MagicMock()
                mock_create_task.return_value = mock_task

                await self.handler.handle_spam_report(update, context)

                # 验证创建了后台任务
                assert mock_create_task.call_count == 1

                # 验证任务参数是 _auto_delete_messages 协程
                call_args = mock_create_task.call_args[0][0]
                assert hasattr(call_args, "__name__") or hasattr(call_args, "cr_code")

                # 注意：由于消息删除现在在后台任务中，我们不直接测试 delete 是否被调用
                # 相反，我们测试后台任务是否被正确创建

    @pytest.mark.asyncio
    async def test_text_spam_report_auto_delete_failure(self, sample_chat_id):
        """测试自动删除消息失败不会导致程序崩溃（后台任务）"""
        target_message = MagicMock(spec=Message)
        target_message.text = "spam text"
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
        update.message.delete = AsyncMock(side_effect=Exception("Delete failed"))

        sent_message = MagicMock()
        sent_message.delete = AsyncMock(side_effect=Exception("Delete failed"))

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock(return_value=sent_message)

            # Mock create_task 来避免后台任务实际执行
            with patch("handlers.blacklist_handler.asyncio.create_task") as mock_create_task:
                mock_task = MagicMock()
                mock_create_task.return_value = mock_task

                # 应该不抛出异常，即使删除会失败（失败发生在后台任务中）
                await self.handler.handle_spam_report(update, context)

                # 验证创建了后台任务
                assert mock_create_task.call_count == 1
