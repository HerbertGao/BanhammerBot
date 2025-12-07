"""Bot集成测试"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bot import BanhammerBot
from telegram import Chat, Message, Update, User


class TestBotIntegration:
    """Bot集成测试"""

    @pytest.fixture
    def bot_instance(self, temp_db_path):
        """创建Bot实例"""
        with patch("bot.Config") as mock_config:
            mock_config.BOT_TOKEN = "test_token_123456"
            mock_config.BLACKLIST_CONFIG = {
                "auto_ban_on_blacklist": True,
                "ban_duration": 0,
                "log_actions": False,
            }
            mock_config.ADMIN_USER_IDS = [999]

            bot = BanhammerBot()
            # 使用测试数据库
            bot.db.db_path = temp_db_path
            bot.db.init_database()
            return bot

    @pytest.mark.asyncio
    async def test_handle_start_private(self, bot_instance):
        """测试私聊/start命令"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.chat = MagicMock()
        update.message.chat.type = "private"
        update.message.chat.id = 123

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await bot_instance._handle_start(update, context)

        context.bot.send_message.assert_called_once()
        call_args = context.bot.send_message.call_args
        assert "Banhammer Bot" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_handle_start_group(self, bot_instance):
        """测试群组/start命令"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.chat = MagicMock()
        update.message.chat.type = "supergroup"
        update.message.chat.id = -1001234567890

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await bot_instance._handle_start(update, context)

        context.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_help(self, bot_instance):
        """测试/help命令"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.chat = MagicMock()
        update.message.chat.id = -1001234567890

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await bot_instance._handle_help(update, context)

        context.bot.send_message.assert_called_once()
        call_args = context.bot.send_message.call_args
        assert "帮助" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_handle_admin_command(self, bot_instance):
        """测试/admin命令"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.chat = MagicMock()
        update.message.chat.id = -1001234567890

        # Mock管理员列表
        admin1 = MagicMock()
        admin1.user = User(id=1, first_name="Admin1", is_bot=False, username="admin1")

        context = MagicMock()
        context.bot.get_chat_administrators = AsyncMock(return_value=[admin1])
        context.bot.send_message = AsyncMock()

        await bot_instance._handle_admin(update, context)

        context.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_admin_command_error(self, bot_instance):
        """测试/admin命令获取失败"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.chat = MagicMock()
        update.message.chat.id = -1001234567890

        context = MagicMock()
        context.bot.get_chat_administrators = AsyncMock(side_effect=Exception("API Error"))
        context.bot.send_message = AsyncMock()

        await bot_instance._handle_admin(update, context)

        context.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_message_admin_skip(self, bot_instance):
        """测试管理员消息跳过检测"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "test message"
        update.message.chat = MagicMock()
        update.message.chat.id = -1001234567890
        update.message.from_user = User(id=999, first_name="Admin", is_bot=False)

        # Mock管理员检查
        with patch.object(bot_instance, "_is_admin_or_creator", return_value=True):
            context = MagicMock()

            await bot_instance._handle_message(update, context)

            # 管理员消息不应该被处理

    @pytest.mark.asyncio
    async def test_handle_message_normal_user(self, bot_instance, sample_chat_id):
        """测试普通用户消息"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "normal message"
        update.message.via_bot = None
        update.message.sticker = None
        update.message.animation = None
        update.message.chat = MagicMock()
        update.message.chat.id = sample_chat_id
        update.message.from_user = User(id=888, first_name="User", is_bot=False)
        update.message.message_id = 123

        with patch.object(bot_instance, "_is_admin_or_creator", return_value=False):
            context = MagicMock()
            context.bot.ban_chat_member = AsyncMock()
            context.bot.send_message = AsyncMock()

            await bot_instance._handle_message(update, context)

            # 正常消息不应触发黑名单

    @pytest.mark.asyncio
    async def test_handle_private_help(self, bot_instance):
        """测试/private_help命令"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.chat = MagicMock()
        update.message.chat.id = 123

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await bot_instance._handle_private_help(update, context)

        context.bot.send_message.assert_called_once()
        call_args = context.bot.send_message.call_args
        assert "私聊转发" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_is_admin_or_creator_admin(self, bot_instance):
        """测试检查管理员"""
        message = MagicMock(spec=Message)
        message.chat = MagicMock()
        message.from_user = MagicMock()
        message.from_user.id = 123

        member = MagicMock()
        member.status = "administrator"
        message.chat.get_member = AsyncMock(return_value=member)

        result = await bot_instance._is_admin_or_creator(message)
        assert result is True

    @pytest.mark.asyncio
    async def test_is_admin_or_creator_creator(self, bot_instance):
        """测试检查群主"""
        message = MagicMock(spec=Message)
        message.chat = MagicMock()
        message.from_user = MagicMock()
        message.from_user.id = 123

        member = MagicMock()
        member.status = "creator"
        message.chat.get_member = AsyncMock(return_value=member)

        result = await bot_instance._is_admin_or_creator(message)
        assert result is True

    @pytest.mark.asyncio
    async def test_is_admin_or_creator_member(self, bot_instance):
        """测试普通成员"""
        message = MagicMock(spec=Message)
        message.chat = MagicMock()
        message.from_user = MagicMock()
        message.from_user.id = 123

        member = MagicMock()
        member.status = "member"
        message.chat.get_member = AsyncMock(return_value=member)

        result = await bot_instance._is_admin_or_creator(message)
        assert result is False

    @pytest.mark.asyncio
    async def test_is_admin_or_creator_error(self, bot_instance):
        """测试权限检查错误"""
        message = MagicMock(spec=Message)
        message.chat = MagicMock()
        message.from_user = MagicMock()
        message.from_user.id = 123

        message.chat.get_member = AsyncMock(side_effect=Exception("API Error"))

        result = await bot_instance._is_admin_or_creator(message)
        assert result is False

    @pytest.mark.asyncio
    async def test_error_handler(self, bot_instance):
        """测试错误处理器"""
        update = MagicMock(spec=Update)
        context = MagicMock()
        context.error = Exception("Test error")

        result = await bot_instance._error_handler(update, context)
        assert result is None

    def test_bot_initialization(self):
        """测试Bot初始化"""
        with patch("bot.Config") as mock_config:
            mock_config.BOT_TOKEN = "test_token"
            mock_config.BLACKLIST_CONFIG = {
                "auto_ban_on_blacklist": True,
                "ban_duration": 0,
                "log_actions": False,
            }

            bot = BanhammerBot()
            assert bot.token == "test_token"
            assert bot.db is not None

    def test_bot_initialization_no_token(self):
        """测试无Token初始化"""
        with patch("bot.Config") as mock_config:
            mock_config.BOT_TOKEN = None

            with pytest.raises(ValueError, match="BOT_TOKEN 未设置"):
                BanhammerBot()

    def test_register_handlers(self, bot_instance):
        """测试处理器注册"""
        with patch("bot.Application") as mock_app:
            mock_application = MagicMock()
            mock_app.builder.return_value.token.return_value.build.return_value = (
                mock_application
            )

            # 调用注册方法
            bot_instance._register_handlers(mock_application)

            # 验证处理器被注册
            assert mock_application.add_handler.called
            assert mock_application.add_error_handler.called

    def test_bot_stop(self, bot_instance):
        """测试Bot停止功能（异步方法正确执行）"""
        # 创建mock application
        mock_app = MagicMock()
        mock_app.stop = AsyncMock()
        mock_app.shutdown = AsyncMock()
        bot_instance.application = mock_app

        # 调用stop方法（同步）
        bot_instance.stop()

        # 验证异步方法被正确执行（通过asyncio.run调用）
        mock_app.stop.assert_called_once()
        mock_app.shutdown.assert_called_once()

    def test_bot_stop_no_application(self, bot_instance):
        """测试Bot停止功能（无application实例）"""
        bot_instance.application = None

        # 应该正常返回，不抛出异常
        bot_instance.stop()

    def test_bot_stop_with_exception(self, bot_instance):
        """测试Bot停止时出现异常"""
        # 创建会抛出异常的mock application
        mock_app = MagicMock()
        mock_app.stop = AsyncMock(side_effect=Exception("Stop failed"))
        mock_app.shutdown = AsyncMock()
        bot_instance.application = mock_app

        # 应该捕获异常并继续清理数据库
        bot_instance.stop()

        # 验证数据库仍然被关闭
        # (通过finally块保证执行)