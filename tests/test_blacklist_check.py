"""测试黑名单检查功能"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from handlers.blacklist_handler import BlacklistHandler
from telegram import Chat, Message, User


class TestBlacklistCheck:
    """测试黑名单检查"""

    @pytest.fixture(autouse=True)
    def setup(self, temp_db_path):
        """每个测试前设置"""
        self.handler = BlacklistHandler()
        self.handler.db.db_path = temp_db_path
        self.handler.db.init_database()

    @pytest.mark.asyncio
    async def test_check_blacklist_link_in_group(self, sample_chat_id):
        """测试群组黑名单链接检测"""
        # 添加链接到黑名单
        link = "https://spam.com"
        self.handler.db.add_to_blacklist(
            chat_id=sample_chat_id, blacklist_type="link", content=link, created_by=999
        )

        # 创建包含该链接的消息
        message = MagicMock(spec=Message)
        message.text = link
        message.via_bot = None
        message.sticker = None
        message.animation = None
        message.chat = MagicMock(spec=Chat)
        message.chat.id = sample_chat_id
        message.from_user = User(id=123, first_name="User", is_bot=False)
        message.message_id = 456
        message.delete = AsyncMock()

        context = MagicMock()
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()
        context.bot.id = 987654321

        # 检查黑名单
        result = await self.handler.check_blacklist(message, context)

        # 验证被检测到
        assert result is True
        message.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_blacklist_sticker_in_group(self, sample_chat_id):
        """测试群组黑名单贴纸检测"""
        # 添加贴纸到黑名单
        sticker_id = "AgADAgADmqcx"
        self.handler.db.add_to_blacklist(
            chat_id=sample_chat_id, blacklist_type="sticker", content=sticker_id, created_by=999
        )

        # 创建包含该贴纸的消息
        message = MagicMock(spec=Message)
        message.text = None
        message.via_bot = None
        message.sticker = MagicMock()
        message.sticker.file_unique_id = sticker_id
        message.animation = None
        message.chat = MagicMock(spec=Chat)
        message.chat.id = sample_chat_id
        message.from_user = User(id=123, first_name="User", is_bot=False)
        message.message_id = 456
        message.delete = AsyncMock()

        context = MagicMock()
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()
        context.bot.id = 987654321

        # 检查黑名单
        result = await self.handler.check_blacklist(message, context)

        # 验证被检测到
        assert result is True
        message.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_blacklist_gif_in_group(self, sample_chat_id):
        """测试群组黑名单GIF检测"""
        # 添加GIF到黑名单
        gif_id = "CgACAgQAAxkBAAID"
        self.handler.db.add_to_blacklist(
            chat_id=sample_chat_id, blacklist_type="gif", content=gif_id, created_by=999
        )

        # 创建包含该GIF的消息
        message = MagicMock(spec=Message)
        message.text = None
        message.via_bot = None
        message.sticker = None
        message.animation = MagicMock()
        message.animation.file_id = gif_id
        message.chat = MagicMock(spec=Chat)
        message.chat.id = sample_chat_id
        message.from_user = User(id=123, first_name="User", is_bot=False)
        message.message_id = 456
        message.delete = AsyncMock()

        context = MagicMock()
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()
        context.bot.id = 987654321

        # 检查黑名单
        result = await self.handler.check_blacklist(message, context)

        # 验证被检测到
        assert result is True
        message.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_blacklist_not_in_list(self, sample_chat_id):
        """测试消息不在黑名单中"""
        # 不添加任何黑名单

        # 创建一个普通消息
        message = MagicMock(spec=Message)
        message.text = "正常消息"
        message.via_bot = None
        message.sticker = None
        message.animation = None
        message.chat = MagicMock(spec=Chat)
        message.chat.id = sample_chat_id
        message.from_user = User(id=123, first_name="User", is_bot=False)
        message.message_id = 456
        message.delete = AsyncMock()

        context = MagicMock()
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()

        # 检查黑名单
        result = await self.handler.check_blacklist(message, context)

        # 验证未被检测到
        assert result is False
        message.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_global_blacklist(self, sample_chat_id):
        """测试通用黑名单检测"""
        # 启用通用黑名单
        self.handler.db.update_group_settings(
            chat_id=sample_chat_id, contribute_to_global=True, use_global_blacklist=True
        )

        # 添加链接到通用黑名单
        link = "https://global-spam.com"
        self.handler.db.add_to_global_blacklist(
            blacklist_type="link", content=link, contributed_by=sample_chat_id
        )

        # 创建包含该链接的消息
        message = MagicMock(spec=Message)
        message.text = link
        message.via_bot = None
        message.sticker = None
        message.animation = None
        message.chat = MagicMock(spec=Chat)
        message.chat.id = sample_chat_id
        message.from_user = User(id=123, first_name="User", is_bot=False)
        message.message_id = 456
        message.delete = AsyncMock()

        context = MagicMock()
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()
        context.bot.id = 987654321

        # 检查黑名单
        result = await self.handler.check_blacklist(message, context)

        # 验证被检测到（通过通用黑名单）
        assert result is True
        message.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_global_blacklist_disabled(self, sample_chat_id):
        """测试禁用通用黑名单后不检测"""
        # 禁用通用黑名单使用
        self.handler.db.update_group_settings(
            chat_id=sample_chat_id, contribute_to_global=False, use_global_blacklist=False
        )

        # 添加链接到通用黑名单
        link = "https://global-spam.com"
        self.handler.db.add_to_global_blacklist(
            blacklist_type="link", content=link, contributed_by=-999
        )

        # 创建包含该链接的消息
        message = MagicMock(spec=Message)
        message.text = link
        message.via_bot = None
        message.sticker = None
        message.animation = None
        message.chat = MagicMock(spec=Chat)
        message.chat.id = sample_chat_id
        message.from_user = User(id=123, first_name="User", is_bot=False)
        message.message_id = 456
        message.delete = AsyncMock()

        context = MagicMock()
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()

        # 检查黑名单
        result = await self.handler.check_blacklist(message, context)

        # 验证未被检测到（因为禁用了通用黑名单）
        assert result is False
        message.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_blacklist_text_message(self, sample_chat_id):
        """测试文字消息黑名单检测"""
        # 添加文字哈希到黑名单
        text = "这是垃圾消息"
        text_hash = self.handler._generate_message_hash(text)
        self.handler.db.add_to_blacklist(
            chat_id=sample_chat_id, blacklist_type="text", content=text_hash, created_by=999
        )

        # 创建相同文本的消息
        message = MagicMock(spec=Message)
        message.text = text
        message.via_bot = None
        message.sticker = None
        message.animation = None
        message.chat = MagicMock(spec=Chat)
        message.chat.id = sample_chat_id
        message.from_user = User(id=123, first_name="User", is_bot=False)
        message.message_id = 456
        message.delete = AsyncMock()

        context = MagicMock()
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()
        context.bot.id = 987654321

        # 检查黑名单
        result = await self.handler.check_blacklist(message, context)

        # 验证被检测到
        assert result is True
        message.delete.assert_called_once()