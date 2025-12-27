"""测试垃圾消息举报功能"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Chat, Message, Update, User

from handlers.blacklist_handler import BlacklistHandler


class TestSpamReport:
    """测试垃圾消息举报"""

    @pytest.fixture(autouse=True)
    def setup(self, temp_db_path):
        """每个测试前设置"""
        from utils.rate_limiter import rate_limiter

        self.handler = BlacklistHandler()
        self.handler.db.db_path = temp_db_path
        self.handler.db.init_database()

        # 清理速率限制器，避免测试间相互影响
        rate_limiter._records.clear()

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

    @pytest.mark.asyncio
    async def test_handle_spam_report_none_from_user(self):
        """测试message.from_user为None的情况（频道消息）"""
        update = MagicMock(spec=Update)
        message = MagicMock(spec=Message)
        message.from_user = None  # 模拟频道消息
        message.chat.id = -1001234567890
        update.message = message

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        # 应该正常返回，不抛出异常
        await self.handler.handle_spam_report(update, context)

        # 验证没有发送任何消息
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_spam_report_target_none_from_user(self):
        """测试target_message.from_user为None的情况（频道消息）"""
        update = MagicMock(spec=Update)
        target_message = MagicMock(spec=Message)
        target_message.from_user = None  # 目标消息来自频道
        target_message.text = "https://spam.com"
        target_message.via_bot = None
        target_message.sticker = None
        target_message.animation = None
        target_message.message_id = 999
        target_message.delete = AsyncMock()

        message = MagicMock(spec=Message)
        message.from_user = User(id=123456, first_name="Admin", is_bot=False)
        message.chat.id = -1001234567890
        message.reply_to_message = target_message
        message.message_id = 1000
        message.delete = AsyncMock()

        update.message = message

        with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock(return_value=MagicMock())
            context.bot.ban_chat_member = AsyncMock()

            # 应该正常返回，添加到黑名单但不封禁
            await self.handler.handle_spam_report(update, context)

            # 验证已删除消息
            target_message.delete.assert_called_once()

            # 验证没有调用封禁（因为from_user为None）
            context.bot.ban_chat_member.assert_not_called()

    @pytest.mark.asyncio
    async def test_background_task_cleanup(self, sample_chat_id):
        """测试后台任务清理功能"""
        import asyncio

        # 创建举报消息
        target_message = MagicMock(spec=Message)
        target_message.text = "https://spam.com"
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

            # 执行举报（会创建后台任务）
            await self.handler.handle_spam_report(update, context)

            # 验证后台任务已被创建
            assert len(self.handler.background_tasks) == 1
            assert not self.handler.background_tasks[0].done()

            # 清理后台任务
            await self.handler.cleanup_background_tasks()

            # 验证任务列表已清空
            assert len(self.handler.background_tasks) == 0

    @pytest.mark.asyncio
    async def test_background_task_auto_cleanup(self, sample_chat_id):
        """测试后台任务自动清理功能（防止内存泄漏）"""
        import asyncio

        from config import Config

        # 临时修改延迟配置以加快测试
        original_delay = Config.BLACKLIST_CONFIG["auto_delete_confirmation_delay"]
        Config.BLACKLIST_CONFIG["auto_delete_confirmation_delay"] = 0.2  # 200ms延迟

        try:
            # 创建多个举报消息
            with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
                context = MagicMock()
                context.bot.ban_chat_member = AsyncMock()
                context.bot.send_message = AsyncMock(return_value=MagicMock())

                # 执行多次举报
                for i in range(5):
                    target_message = MagicMock(spec=Message)
                    target_message.text = f"https://spam{i}.com"
                    target_message.via_bot = None
                    target_message.sticker = None
                    target_message.animation = None
                    target_message.from_user = User(id=888 + i, first_name="Spammer", is_bot=False)
                    target_message.message_id = 999 + i
                    target_message.delete = AsyncMock()

                    update = MagicMock(spec=Update)
                    update.message = MagicMock(spec=Message)
                    update.message.text = "/spam"
                    update.message.reply_to_message = target_message
                    update.message.chat = MagicMock()
                    update.message.chat.id = sample_chat_id
                    update.message.from_user = User(id=999, first_name="Admin", is_bot=False)
                    update.message.message_id = 1000 + i
                    update.message.delete = AsyncMock()

                    await self.handler.handle_spam_report(update, context)

                    # 等待一小段时间让之前的任务完成
                    await asyncio.sleep(0.3)  # 等待比延迟时间稍长

                # 验证列表不会无限增长（应该远少于5个）
                # 因为已完成的任务会在添加新任务时被清理
                assert len(self.handler.background_tasks) <= 5
                assert len(self.handler.background_tasks) >= 1  # 至少有最后一个任务

                # 等待所有任务完成
                await asyncio.sleep(0.5)

                # 手动清理验证
                self.handler._cleanup_completed_tasks()
                assert len(self.handler.background_tasks) == 0
        finally:
            # 恢复原始配置
            Config.BLACKLIST_CONFIG["auto_delete_confirmation_delay"] = original_delay

    @pytest.mark.asyncio
    async def test_background_task_limit_enforcement(self, sample_chat_id):
        """测试后台任务数量限制的强制执行"""
        import asyncio

        from config import Config

        # 临时修改最大任务数限制和延迟配置
        original_max_tasks = self.handler.MAX_BACKGROUND_TASKS
        original_delay = Config.BLACKLIST_CONFIG["auto_delete_confirmation_delay"]

        # 设置小的限制值用于测试（3个任务）
        self.handler.MAX_BACKGROUND_TASKS = 3
        # 设置较长延迟，确保任务不会立即完成
        Config.BLACKLIST_CONFIG["auto_delete_confirmation_delay"] = 5.0

        try:
            with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
                context = MagicMock()
                context.bot.ban_chat_member = AsyncMock()
                context.bot.send_message = AsyncMock(return_value=MagicMock())

                # 快速创建4个举报（超过限制3个）
                for i in range(4):
                    target_message = MagicMock(spec=Message)
                    target_message.text = f"https://spam{i}.com"
                    target_message.via_bot = None
                    target_message.sticker = None
                    target_message.animation = None
                    target_message.from_user = User(id=888 + i, first_name="Spammer", is_bot=False)
                    target_message.message_id = 999 + i
                    target_message.delete = AsyncMock()

                    update = MagicMock(spec=Update)
                    update.message = MagicMock(spec=Message)
                    update.message.text = "/spam"
                    update.message.reply_to_message = target_message
                    update.message.chat = MagicMock()
                    update.message.chat.id = sample_chat_id
                    update.message.from_user = User(id=999, first_name="Admin", is_bot=False)
                    update.message.message_id = 1000 + i
                    update.message.delete = AsyncMock()

                    # 异步执行，不等待完成（模拟高并发）
                    asyncio.create_task(self.handler.handle_spam_report(update, context))

                # 短暂等待所有举报处理完成
                await asyncio.sleep(0.5)

                # 验证任务数不超过限制
                assert len(self.handler.background_tasks) <= self.handler.MAX_BACKGROUND_TASKS, (
                    f"后台任务数 {len(self.handler.background_tasks)} 超过限制 "
                    f"{self.handler.MAX_BACKGROUND_TASKS}"
                )

                # 清理所有任务
                for task in self.handler.background_tasks:
                    task.cancel()
                await asyncio.sleep(0.1)
                self.handler._cleanup_completed_tasks()

        finally:
            # 恢复原始配置
            self.handler.MAX_BACKGROUND_TASKS = original_max_tasks
            Config.BLACKLIST_CONFIG["auto_delete_confirmation_delay"] = original_delay

    @pytest.mark.asyncio
    async def test_admin_exempt_from_rate_limit(self, sample_chat_id):
        """测试管理员豁免速率限制 - 可以快速处理多条举报"""
        from config import Config
        from utils.rate_limiter import rate_limiter

        # 清理速率限制记录
        rate_limiter._records.clear()

        # 确保速率限制已启用且管理员豁免已开启
        original_enabled = Config.RATE_LIMIT_CONFIG["enabled"]
        original_exempt = Config.RATE_LIMIT_CONFIG.get("exempt_admins", False)
        Config.RATE_LIMIT_CONFIG["enabled"] = True
        Config.RATE_LIMIT_CONFIG["exempt_admins"] = True

        try:
            # 模拟管理员快速举报超过限制次数（默认限制是5次/60秒）
            with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
                context = MagicMock()
                context.bot.ban_chat_member = AsyncMock()
                context.bot.send_message = AsyncMock(return_value=MagicMock())

                admin_user = User(id=999, first_name="Admin", is_bot=False)

                # 尝试举报10次（远超限制5次）
                for i in range(10):
                    target_message = MagicMock(spec=Message)
                    target_message.text = f"https://spam{i}.com"
                    target_message.via_bot = None
                    target_message.sticker = None
                    target_message.animation = None
                    target_message.from_user = User(id=888 + i, first_name="Spammer", is_bot=False)
                    target_message.message_id = 999 + i
                    target_message.delete = AsyncMock()

                    update = MagicMock(spec=Update)
                    update.message = MagicMock(spec=Message)
                    update.message.text = "/spam"
                    update.message.reply_to_message = target_message
                    update.message.chat = MagicMock()
                    update.message.chat.id = sample_chat_id
                    update.message.from_user = admin_user
                    update.message.message_id = 1000 + i
                    update.message.delete = AsyncMock()

                    await self.handler.handle_spam_report(update, context)

                    # 验证消息已被删除（表示举报成功）
                    target_message.delete.assert_called_once()

                # 验证所有10条都成功举报（管理员不受速率限制）
                assert (
                    context.bot.ban_chat_member.call_count == 10
                ), f"管理员应该成功处理所有10次举报，实际: {context.bot.ban_chat_member.call_count}"

        finally:
            # 恢复原始配置
            Config.RATE_LIMIT_CONFIG["enabled"] = original_enabled
            Config.RATE_LIMIT_CONFIG["exempt_admins"] = original_exempt
            rate_limiter._records.clear()

    @pytest.mark.asyncio
    async def test_admin_rate_limited_when_exemption_disabled(self, sample_chat_id):
        """测试管理员在禁用豁免时受速率限制 - 超过限制后被阻止"""
        from config import Config
        from utils.rate_limiter import rate_limiter

        # 清理速率限制记录
        rate_limiter._records.clear()

        # 确保速率限制已启用
        original_enabled = Config.RATE_LIMIT_CONFIG["enabled"]
        original_exempt = Config.RATE_LIMIT_CONFIG.get("exempt_admins", False)
        Config.RATE_LIMIT_CONFIG["enabled"] = True
        Config.RATE_LIMIT_CONFIG["exempt_admins"] = True

        try:
            # 测试场景：管理员在 exempt_admins=False 时也应受速率限制
            Config.RATE_LIMIT_CONFIG["exempt_admins"] = False

            with patch.object(self.handler, "_is_admin_or_creator", return_value=True):
                context = MagicMock()
                context.bot.ban_chat_member = AsyncMock()
                context.bot.send_message = AsyncMock(return_value=MagicMock())

                admin_user = User(id=888, first_name="Admin", is_bot=False)
                success_count = 0

                # 尝试举报10次（超过限制5次/60秒）
                for i in range(10):
                    target_message = MagicMock(spec=Message)
                    target_message.text = f"https://spam{i}.com"
                    target_message.via_bot = None
                    target_message.sticker = None
                    target_message.animation = None
                    target_message.from_user = User(id=777 + i, first_name="Spammer", is_bot=False)
                    target_message.message_id = 999 + i
                    target_message.delete = AsyncMock()

                    update = MagicMock(spec=Update)
                    update.message = MagicMock(spec=Message)
                    update.message.text = "/spam"
                    update.message.reply_to_message = target_message
                    update.message.chat = MagicMock()
                    update.message.chat.id = sample_chat_id
                    update.message.from_user = admin_user
                    update.message.message_id = 1000 + i
                    update.message.delete = AsyncMock()

                    await self.handler.handle_spam_report(update, context)

                    # 检查是否成功处理（通过检查是否调用了ban）
                    if context.bot.ban_chat_member.call_count > success_count:
                        success_count = context.bot.ban_chat_member.call_count

                # 验证只有前5次成功（受速率限制）
                assert (
                    success_count == 5
                ), f"管理员在禁用豁免时应该只能成功处理5次举报（速率限制），实际: {success_count}"

                # 验证最后几次调用发送了速率限制错误消息
                # send_message 会被调用多次（成功消息+错误消息）
                assert context.bot.send_message.call_count >= 10

        finally:
            # 恢复原始配置
            Config.RATE_LIMIT_CONFIG["enabled"] = original_enabled
            Config.RATE_LIMIT_CONFIG["exempt_admins"] = original_exempt
            rate_limiter._records.clear()
