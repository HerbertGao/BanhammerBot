"""测试私聊转发功能"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Chat, Message, Update, User

from handlers.blacklist_handler import BlacklistHandler


class TestPrivateForward:
    """测试私聊转发添加黑名单"""

    @pytest.fixture(autouse=True)
    def setup(self, temp_db_path):
        """每个测试前设置"""
        self.handler = BlacklistHandler()
        self.handler.db.db_path = temp_db_path
        self.handler.db.init_database()

    @pytest.mark.asyncio
    async def test_private_forward_link(self):
        """测试转发链接消息"""
        # 创建一个贡献群组
        group_id = -1001234567890
        self.handler.db.update_group_settings(group_id, contribute_to_global=True)

        # 创建转发消息
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "https://spam.com"
        update.message.via_bot = None
        update.message.sticker = None
        update.message.animation = None
        update.message.forward_from = User(id=777, first_name="Spammer", is_bot=False)
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)
        update.message.chat = Chat(id=999, type="private", first_name="Admin")

        with patch.object(self.handler, "_is_bot_admin", return_value=True):
            with patch(
                "config.Config.PRIVATE_FORWARD_CONFIG",
                {"auto_add_to_contributing_groups": True, "auto_add_to_global": True},
            ):
                context = MagicMock()
                context.bot.send_message = AsyncMock()

                await self.handler.handle_private_forward(update, context)

                # 验证添加到群组黑名单
                is_blacklisted = self.handler.db.check_blacklist(
                    group_id, "link", "https://spam.com"
                )
                assert is_blacklisted is True

                # 验证添加到全局黑名单
                is_global = self.handler.db.check_global_blacklist("link", "https://spam.com")
                assert is_global is True

                # 验证发送了确认消息
                context.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_private_forward_sticker(self):
        """测试转发贴纸消息"""
        group_id = -1001234567890
        self.handler.db.update_group_settings(group_id, contribute_to_global=True)

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = None
        update.message.via_bot = None
        update.message.sticker = MagicMock()
        update.message.sticker.file_unique_id = "StickerID123"
        update.message.animation = None
        update.message.forward_from = User(id=777, first_name="Spammer", is_bot=False)
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)
        update.message.chat = Chat(id=999, type="private", first_name="Admin")

        with patch.object(self.handler, "_is_bot_admin", return_value=True):
            with patch(
                "config.Config.PRIVATE_FORWARD_CONFIG",
                {"auto_add_to_contributing_groups": True, "auto_add_to_global": True},
            ):
                context = MagicMock()
                context.bot.send_message = AsyncMock()

                await self.handler.handle_private_forward(update, context)

                # 验证添加到黑名单
                is_blacklisted = self.handler.db.check_blacklist(
                    group_id, "sticker", "StickerID123"
                )
                assert is_blacklisted is True

    @pytest.mark.asyncio
    async def test_private_forward_via_bot(self):
        """测试转发内联Bot消息"""
        group_id = -1001234567890
        self.handler.db.update_group_settings(group_id, contribute_to_global=True)

        bot_user = User(id=123456, first_name="SpamBot", is_bot=True)

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "spam content"
        update.message.via_bot = bot_user
        update.message.sticker = None
        update.message.animation = None
        update.message.forward_from = User(id=777, first_name="Spammer", is_bot=False)
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)
        update.message.chat = Chat(id=999, type="private", first_name="Admin")

        with patch.object(self.handler, "_is_bot_admin", return_value=True):
            with patch(
                "config.Config.PRIVATE_FORWARD_CONFIG",
                {"auto_add_to_contributing_groups": True, "auto_add_to_global": True},
            ):
                context = MagicMock()
                context.bot.send_message = AsyncMock()

                await self.handler.handle_private_forward(update, context)

                # 验证添加到黑名单
                is_blacklisted = self.handler.db.check_blacklist(group_id, "bot", "123456")
                assert is_blacklisted is True

    @pytest.mark.asyncio
    async def test_private_forward_not_forwarded_message(self):
        """测试非转发消息"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "https://spam.com"
        update.message.via_bot = None
        update.message.sticker = None
        update.message.animation = None
        update.message.forward_from = None
        update.message.forward_from_chat = None
        update.message.forward_origin = None
        update.message.from_user = User(id=999, first_name="User", is_bot=False)
        update.message.chat = Chat(id=999, type="private", first_name="User")

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await self.handler.handle_private_forward(update, context)

        # 验证发送了错误消息
        context.bot.send_message.assert_called_once()
        call_args = context.bot.send_message.call_args
        assert "转发消息" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_private_forward_not_bot_admin(self):
        """测试非Bot管理员"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "https://spam.com"
        update.message.via_bot = None
        update.message.sticker = None
        update.message.animation = None
        update.message.forward_from = User(id=777, first_name="Spammer", is_bot=False)
        update.message.from_user = User(id=888, first_name="User", is_bot=False)
        update.message.chat = Chat(id=888, type="private", first_name="User")

        with patch.object(self.handler, "_is_bot_admin", return_value=False):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_private_forward(update, context)

            # 验证发送了错误消息
            context.bot.send_message.assert_called_once()
            call_args = context.bot.send_message.call_args
            assert "没有权限" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_private_forward_unrecognized_type(self):
        """测试无法识别的消息类型"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = None
        update.message.via_bot = None
        update.message.sticker = None
        update.message.animation = None
        update.message.forward_from = User(id=777, first_name="Spammer", is_bot=False)
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)
        update.message.chat = Chat(id=999, type="private", first_name="Admin")

        with patch.object(self.handler, "_is_bot_admin", return_value=True):
            context = MagicMock()
            context.bot.send_message = AsyncMock()

            await self.handler.handle_private_forward(update, context)

            # 验证发送了错误消息
            context.bot.send_message.assert_called_once()
            call_args = context.bot.send_message.call_args
            assert "无法识别" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_private_forward_only_to_groups(self):
        """测试只添加到群组（不添加到全局）"""
        group_id = -1001234567890
        self.handler.db.update_group_settings(group_id, contribute_to_global=True)

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "https://spam.com"
        update.message.via_bot = None
        update.message.sticker = None
        update.message.animation = None
        update.message.forward_from = User(id=777, first_name="Spammer", is_bot=False)
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)
        update.message.chat = Chat(id=999, type="private", first_name="Admin")

        with patch.object(self.handler, "_is_bot_admin", return_value=True):
            with patch(
                "config.Config.PRIVATE_FORWARD_CONFIG",
                {"auto_add_to_contributing_groups": True, "auto_add_to_global": False},
            ):
                context = MagicMock()
                context.bot.send_message = AsyncMock()

                await self.handler.handle_private_forward(update, context)

                # 验证添加到群组黑名单
                is_blacklisted = self.handler.db.check_blacklist(
                    group_id, "link", "https://spam.com"
                )
                assert is_blacklisted is True

                # 验证未添加到全局黑名单
                is_global = self.handler.db.check_global_blacklist("link", "https://spam.com")
                assert is_global is False

    @pytest.mark.asyncio
    async def test_private_forward_only_to_global(self):
        """测试只添加到全局（不添加到群组）"""
        group_id = -1001234567890
        self.handler.db.update_group_settings(group_id, contribute_to_global=True)

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "https://spam.com"
        update.message.via_bot = None
        update.message.sticker = None
        update.message.animation = None
        update.message.forward_from = User(id=777, first_name="Spammer", is_bot=False)
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)
        update.message.chat = Chat(id=999, type="private", first_name="Admin")

        with patch.object(self.handler, "_is_bot_admin", return_value=True):
            with patch(
                "config.Config.PRIVATE_FORWARD_CONFIG",
                {"auto_add_to_contributing_groups": False, "auto_add_to_global": True},
            ):
                context = MagicMock()
                context.bot.send_message = AsyncMock()

                await self.handler.handle_private_forward(update, context)

                # 验证未添加到群组黑名单
                is_blacklisted = self.handler.db.check_blacklist(
                    group_id, "link", "https://spam.com"
                )
                assert is_blacklisted is False

                # 验证添加到全局黑名单
                is_global = self.handler.db.check_global_blacklist("link", "https://spam.com")
                assert is_global is True

    @pytest.mark.asyncio
    async def test_private_forward_multiple_contributing_groups(self):
        """测试多个贡献群组"""
        group1_id = -1001111111111
        group2_id = -1002222222222
        self.handler.db.update_group_settings(group1_id, contribute_to_global=True)
        self.handler.db.update_group_settings(group2_id, contribute_to_global=True)

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "https://spam.com"
        update.message.via_bot = None
        update.message.sticker = None
        update.message.animation = None
        update.message.forward_from = User(id=777, first_name="Spammer", is_bot=False)
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)
        update.message.chat = Chat(id=999, type="private", first_name="Admin")

        with patch.object(self.handler, "_is_bot_admin", return_value=True):
            with patch(
                "config.Config.PRIVATE_FORWARD_CONFIG",
                {"auto_add_to_contributing_groups": True, "auto_add_to_global": True},
            ):
                context = MagicMock()
                context.bot.send_message = AsyncMock()

                await self.handler.handle_private_forward(update, context)

                # 验证添加到所有群组黑名单
                is_blacklisted1 = self.handler.db.check_blacklist(
                    group1_id, "link", "https://spam.com"
                )
                is_blacklisted2 = self.handler.db.check_blacklist(
                    group2_id, "link", "https://spam.com"
                )
                assert is_blacklisted1 is True
                assert is_blacklisted2 is True

    @pytest.mark.asyncio
    async def test_private_forward_with_forward_from_chat(self):
        """测试使用forward_from_chat的转发消息"""
        group_id = -1001234567890
        self.handler.db.update_group_settings(group_id, contribute_to_global=True)

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "https://spam.com"
        update.message.via_bot = None
        update.message.sticker = None
        update.message.animation = None
        update.message.forward_from = None
        update.message.forward_from_chat = Chat(
            id=-1003333333333, type="channel", title="Spam Channel"
        )
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)
        update.message.chat = Chat(id=999, type="private", first_name="Admin")

        with patch.object(self.handler, "_is_bot_admin", return_value=True):
            with patch(
                "config.Config.PRIVATE_FORWARD_CONFIG",
                {"auto_add_to_contributing_groups": True, "auto_add_to_global": True},
            ):
                context = MagicMock()
                context.bot.send_message = AsyncMock()

                await self.handler.handle_private_forward(update, context)

                # 验证添加到黑名单
                is_blacklisted = self.handler.db.check_blacklist(
                    group_id, "link", "https://spam.com"
                )
                assert is_blacklisted is True

    @pytest.mark.asyncio
    async def test_private_forward_none_message(self):
        """测试update.message为None的情况（不应崩溃）"""
        update = MagicMock(spec=Update)
        update.message = None

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        # 应该正常返回，不抛出异常
        await self.handler.handle_private_forward(update, context)

        # 验证没有发送任何消息
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_private_forward_none_from_user(self):
        """测试message.from_user为None的情况（防御性编程）"""
        # 创建一个转发消息，但from_user为None（理论上不应该发生，但我们要防御）
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "forwarded link: https://example.com"
        update.message.via_bot = None
        update.message.sticker = None
        update.message.animation = None
        update.message.forward_from = User(id=777, first_name="Spammer", is_bot=False)
        update.message.from_user = None  # 发送者为空
        update.message.chat = Chat(id=999, type="private", first_name="Admin")

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        # 应该正常返回，不抛出异常
        await self.handler.handle_private_forward(update, context)

        # 验证没有发送任何消息（因为在检查后直接return）
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_is_bot_admin_without_config(self):
        """测试未配置ADMIN_USER_IDS时拒绝访问（安全修复）"""
        from unittest.mock import patch

        user_id = 123456
        context = MagicMock()

        # Mock PRIVATE_FORWARD_CONFIG with empty admin_user_ids
        with patch(
            "handlers.blacklist_handler.Config.PRIVATE_FORWARD_CONFIG",
            {
                "enabled": True,
                "admin_user_ids": [],  # 空列表，模拟未配置
                "auto_add_to_contributing_groups": True,
                "auto_add_to_global": True,
            },
        ):
            # 应该返回 False（拒绝访问）
            result = await self.handler._is_bot_admin(user_id, context)
            assert result is False

    @pytest.mark.asyncio
    async def test_is_bot_admin_with_valid_admin(self):
        """测试有效的管理员ID"""
        from unittest.mock import patch

        user_id = 123456
        context = MagicMock()

        # Mock PRIVATE_FORWARD_CONFIG with valid admin_user_ids
        with patch(
            "handlers.blacklist_handler.Config.PRIVATE_FORWARD_CONFIG",
            {
                "enabled": True,
                "admin_user_ids": [123456, 789012],
                "auto_add_to_contributing_groups": True,
                "auto_add_to_global": True,
            },
        ):
            # 应该返回 True（允许访问）
            result = await self.handler._is_bot_admin(user_id, context)
            assert result is True

    @pytest.mark.asyncio
    async def test_is_bot_admin_with_invalid_user(self):
        """测试非管理员用户"""
        from unittest.mock import patch

        user_id = 999999  # 不在管理员列表中
        context = MagicMock()

        # Mock PRIVATE_FORWARD_CONFIG with admin_user_ids not including user_id
        with patch(
            "handlers.blacklist_handler.Config.PRIVATE_FORWARD_CONFIG",
            {
                "enabled": True,
                "admin_user_ids": [123456, 789012],
                "auto_add_to_contributing_groups": True,
                "auto_add_to_global": True,
            },
        ):
            # 应该返回 False（拒绝访问）
            result = await self.handler._is_bot_admin(user_id, context)
            assert result is False
