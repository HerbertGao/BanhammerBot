"""测试via_bot检测优先级问题"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Message, User

from handlers.blacklist_handler import BlacklistHandler


class TestViaBotPriority:
    """测试via_bot检测优先级"""

    @pytest.fixture(autouse=True)
    def setup(self, temp_db_path):
        """每个测试前设置"""
        self.handler = BlacklistHandler()
        self.handler.db.db_path = temp_db_path
        self.handler.db.init_database()

    @pytest.mark.asyncio
    async def test_via_bot_should_be_checked_before_text_content(self, sample_chat_id):
        """
        测试via_bot应该在文本内容之前检查

        场景：
        1. 某个内联Bot (ID: 123456) 被加入黑名单
        2. 该Bot发送的新消息包含普通文本（不在黑名单中）
        3. 应该因为Bot ID在黑名单而被拦截，而不是检查文本内容
        """
        # 1. 添加内联Bot到黑名单
        bot_id = "123456"
        self.handler.db.add_to_blacklist(
            chat_id=sample_chat_id,
            blacklist_type="bot",
            content=bot_id,
            created_by=999,
        )

        # 2. 创建一个通过该Bot发送的消息，包含新的文本内容
        bot_user = User(id=int(bot_id), first_name="SpamBot", is_bot=True)
        message = MagicMock(spec=Message)
        message.via_bot = bot_user
        message.text = "这是新的文本内容，从未被举报过"  # 新内容，不在黑名单
        message.sticker = None
        message.animation = None
        message.chat = MagicMock()
        message.chat.id = sample_chat_id
        message.from_user = User(id=888, first_name="User", is_bot=False)
        message.message_id = 111

        context = MagicMock()
        context.bot.delete_message = AsyncMock()
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()
        context.bot.id = 987654321  # Bot ID for ban records

        # Mock message.delete() instead of context.bot.delete_message()
        message.delete = AsyncMock()

        # 3. 检查黑名单 - 应该被拦截（因为via_bot在黑名单）
        result = await self.handler._check_group_blacklist(message, context)

        # 4. 验证结果
        assert result is True, "应该因为via_bot在黑名单而返回True"
        message.delete.assert_called_once()  # 使用 message.delete()
        context.bot.ban_chat_member.assert_called_once()

    @pytest.mark.asyncio
    async def test_via_bot_with_new_link_should_still_be_blocked(self, sample_chat_id):
        """
        测试通过黑名单Bot发送新链接应该被拦截

        场景：
        1. 内联Bot被加入黑名单
        2. 通过该Bot发送包含新链接的消息（链接本身不在黑名单）
        3. 应该被拦截（因为Bot在黑名单，而不是链接）
        """
        # 1. 添加Bot到黑名单
        bot_id = "999888"
        self.handler.db.add_to_blacklist(
            chat_id=sample_chat_id,
            blacklist_type="bot",
            content=bot_id,
            created_by=999,
        )

        # 2. 创建通过该Bot发送的新链接消息
        bot_user = User(id=int(bot_id), first_name="LinkBot", is_bot=True)
        message = MagicMock(spec=Message)
        message.via_bot = bot_user
        message.text = "https://totally-new-spam-link.com"  # 新链接
        message.sticker = None
        message.animation = None
        message.chat = MagicMock()
        message.chat.id = sample_chat_id
        message.from_user = User(id=777, first_name="User", is_bot=False)
        message.message_id = 222

        context = MagicMock()
        context.bot.delete_message = AsyncMock()
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()
        context.bot.id = 987654321  # Bot ID for ban records

        # Mock message.delete()
        message.delete = AsyncMock()

        # 3. 检查黑名单
        result = await self.handler._check_group_blacklist(message, context)

        # 4. 验证：即使链接不在黑名单，也应该因为Bot被拦截
        assert result is True, "应该因为via_bot在黑名单而被拦截"
        message.delete.assert_called_once()  # 使用 message.delete()

    def test_extract_vs_check_consistency(self):
        """
        测试_extract_blacklist_content和_check_group_blacklist的优先级一致性

        当一个消息既有via_bot又有text时：
        - _extract_blacklist_content应该返回'bot'类型
        - _check_group_blacklist应该优先检查via_bot
        """
        # 创建一个既有via_bot又有text的消息
        bot_user = User(id=111222, first_name="TestBot", is_bot=True)
        message = MagicMock(spec=Message)
        message.via_bot = bot_user
        message.text = "普通文本消息"
        message.sticker = None
        message.animation = None

        # extract应该返回bot类型（优先级最高）
        blacklist_type, content = self.handler._extract_blacklist_content(message)
        assert blacklist_type == "bot", "_extract_blacklist_content应该优先识别bot"
        assert content == "111222"
