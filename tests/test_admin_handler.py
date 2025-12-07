"""管理员处理器测试"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from handlers.admin_handler import AdminHandler
from telegram import Chat, ChatMember, Message, Update, User
from telegram.constants import ChatMemberStatus


class TestAdminHandler:
    """管理员处理器测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """每个测试前设置"""
        self.handler = AdminHandler()

    def test_contains_admin_call(self):
        """测试 @admin 呼叫检测"""
        # 包含 @admin
        assert self.handler._contains_admin_call("@admin help me") is True
        assert self.handler._contains_admin_call("Help @admin please") is True
        assert self.handler._contains_admin_call("@ADMIN") is True  # 不区分大小写
        assert self.handler._contains_admin_call("@AdMiN") is True

        # 不包含 @admin
        assert self.handler._contains_admin_call("hello world") is False
        assert self.handler._contains_admin_call("administrator") is False
        assert self.handler._contains_admin_call("") is False

    @pytest.mark.asyncio
    async def test_get_chat_admins(self):
        """测试获取群组管理员列表"""
        # Mock 管理员列表
        admin1 = MagicMock()
        admin1.user = User(id=1, first_name="Admin1", is_bot=False, username="admin1")

        admin2 = MagicMock()
        admin2.user = User(id=2, first_name="Admin2", is_bot=False, username="admin2")

        bot_admin = MagicMock()
        bot_admin.user = User(
            id=3, first_name="BotAdmin", is_bot=True, username="botadmin"
        )

        mock_context = MagicMock()
        mock_context.bot.get_chat_administrators = AsyncMock(
            return_value=[admin1, admin2, bot_admin]
        )

        admins = await self.handler._get_chat_admins(-1001234567890, mock_context)

        # 应该只返回非机器人管理员
        assert len(admins) == 2
        assert admins[0].id == 1
        assert admins[1].id == 2

    @pytest.mark.asyncio
    async def test_get_chat_admins_error(self):
        """测试获取管理员列表失败"""
        mock_context = MagicMock()
        mock_context.bot.get_chat_administrators = AsyncMock(
            side_effect=Exception("API Error")
        )

        admins = await self.handler._get_chat_admins(-1001234567890, mock_context)
        assert admins == []

    @pytest.mark.asyncio
    async def test_handle_admin_call_no_message(self):
        """测试处理空消息"""
        update = MagicMock(spec=Update)
        update.message = None
        context = MagicMock()

        # 应该直接返回，不做任何操作
        await self.handler.handle_admin_call(update, context)
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_admin_call_no_text(self):
        """测试处理无文本消息"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = None
        context = MagicMock()

        await self.handler.handle_admin_call(update, context)
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_admin_call_private_chat(self):
        """测试在私聊中呼叫管理员"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "@admin help"
        update.message.chat = MagicMock(spec=Chat)
        update.message.chat.type = "private"
        context = MagicMock()

        await self.handler.handle_admin_call(update, context)
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_admin_call_no_admin_keyword(self):
        """测试消息不包含 @admin"""
        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "hello world"
        update.message.chat = MagicMock(spec=Chat)
        update.message.chat.type = "supergroup"
        context = MagicMock()

        await self.handler.handle_admin_call(update, context)
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_admin_call_success(self):
        """测试成功呼叫管理员"""
        # 创建 mock 对象
        user = User(id=100, first_name="TestUser", is_bot=False, username="testuser")
        chat = Chat(id=-1001234567890, type="supergroup", title="Test Group")

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "@admin help me please"
        update.message.chat = chat
        update.message.from_user = user
        update.message.message_id = 123

        # Mock 管理员
        admin1 = MagicMock()
        admin1.user = User(
            id=1, first_name="Admin", last_name="One", is_bot=False, username="admin1"
        )

        admin2 = MagicMock()
        admin2.user = User(
            id=2, first_name="AdminTwo", is_bot=False, username=None
        )  # 无用户名

        context = MagicMock()
        context.bot.get_chat_administrators = AsyncMock(return_value=[admin1, admin2])
        context.bot.send_message = AsyncMock()

        await self.handler.handle_admin_call(update, context)

        # 验证发送了消息
        context.bot.send_message.assert_called_once()
        call_args = context.bot.send_message.call_args

        assert call_args.kwargs["chat_id"] == chat.id
        assert "Admin One" in call_args.kwargs["text"]
        assert "@admin1" in call_args.kwargs["text"]
        assert "AdminTwo" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_handle_admin_command_in_group(self):
        """测试在群组中使用 /admin 命令"""
        chat = Chat(id=-1001234567890, type="supergroup", title="Test Group")

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.chat = chat

        admin = MagicMock()
        admin.user = User(id=1, first_name="Admin", is_bot=False, username="admin1")

        context = MagicMock()
        context.bot.get_chat_administrators = AsyncMock(return_value=[admin])
        context.bot.send_message = AsyncMock()

        await self.handler.handle_admin_command(update, context)

        # 验证发送了管理员列表
        context.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_admin_command_in_private(self):
        """测试在私聊中使用 /admin 命令"""
        chat = Chat(id=123456, type="private", first_name="User")

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.chat = chat

        context = MagicMock()
        context.bot.send_message = AsyncMock()

        await self.handler.handle_admin_command(update, context)

        # 验证发送了提示消息
        context.bot.send_message.assert_called_once()
        call_args = context.bot.send_message.call_args
        assert "只能在群组中使用" in call_args.kwargs["text"]

    @pytest.mark.asyncio
    async def test_handle_admin_call_no_admins(self):
        """测试无管理员的群组"""
        chat = Chat(id=-1001234567890, type="supergroup", title="Test Group")
        user = User(id=100, first_name="TestUser", is_bot=False, username="testuser")

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "@admin help"
        update.message.chat = chat
        update.message.from_user = user
        update.message.message_id = 123

        context = MagicMock()
        context.bot.get_chat_administrators = AsyncMock(return_value=[])
        context.bot.send_message = AsyncMock()

        await self.handler.handle_admin_call(update, context)

        # 验证发送了无管理员消息
        context.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_admin_command_no_admins(self):
        """测试/admin命令在无管理员群组"""
        chat = Chat(id=-1001234567890, type="supergroup", title="Test Group")

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.chat = chat

        context = MagicMock()
        context.bot.get_chat_administrators = AsyncMock(return_value=[])
        context.bot.send_message = AsyncMock()

        await self.handler.handle_admin_command(update, context)

        # 验证发送了无管理员消息
        context.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_admin_list_error(self):
        """测试发送管理员列表失败"""
        chat = Chat(id=-1001234567890, type="supergroup", title="Test Group")

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.text = "@admin"
        update.message.chat = chat
        update.message.from_user = User(id=100, first_name="TestUser", is_bot=False, username="testuser")
        update.message.message_id = 123

        admin = MagicMock()
        admin.user = User(id=1, first_name="Admin", is_bot=False, username="admin1")

        context = MagicMock()
        context.bot.get_chat_administrators = AsyncMock(return_value=[admin])
        context.bot.send_message = AsyncMock(side_effect=Exception("Send failed"))

        # 应该捕获异常不崩溃
        await self.handler.handle_admin_call(update, context)

    @pytest.mark.asyncio
    async def test_send_private_chat_message_error(self):
        """测试私聊消息发送失败"""
        chat = Chat(id=123456, type="private", first_name="User")

        update = MagicMock(spec=Update)
        update.message = MagicMock(spec=Message)
        update.message.chat = chat

        context = MagicMock()
        context.bot.send_message = AsyncMock(side_effect=Exception("Send failed"))

        # 应该捕获异常不崩溃
        await self.handler.handle_admin_command(update, context)

    @pytest.mark.asyncio
    async def test_handle_admin_call_no_message(self):
        """测试handle_admin_call无消息"""
        update = MagicMock(spec=Update)
        update.message = None

        context = MagicMock()

        # 应该直接返回不报错
        await self.handler.handle_admin_call(update, context)

    @pytest.mark.asyncio
    async def test_handle_admin_command_no_message(self):
        """测试handle_admin_command无消息"""
        update = MagicMock(spec=Update)
        update.message = None

        context = MagicMock()

        # 应该直接返回不报错
        await self.handler.handle_admin_command(update, context)