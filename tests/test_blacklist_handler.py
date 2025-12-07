"""黑名单处理器测试"""

import hashlib

import pytest

from handlers.blacklist_handler import BlacklistHandler


class TestBlacklistHandler:
    """黑名单处理器测试"""

    @pytest.fixture(autouse=True)
    def setup(self, temp_db_path):
        """每个测试前设置"""
        self.handler = BlacklistHandler()
        self.handler.db.db_path = temp_db_path
        self.handler.db.init_database()

    def test_generate_message_hash(self):
        """测试消息哈希生成"""
        text1 = "这是一条测试消息"
        text2 = "  这是一条测试消息  "  # 有额外空格
        text3 = "这是   一条   测试   消息"  # 多余空格

        hash1 = self.handler._generate_message_hash(text1)
        hash2 = self.handler._generate_message_hash(text2)
        hash3 = self.handler._generate_message_hash(text3)

        # 不同格式的相同内容应生成相同哈希
        assert hash1 == hash2
        # 不同内容应生成不同哈希
        assert hash1 != hash3

        # 哈希应该是64字符的十六进制字符串（SHA256）
        assert len(hash1) == 64
        assert all(c in "0123456789abcdef" for c in hash1)

    def test_is_only_link(self):
        """测试链接识别"""
        assert self.handler._is_only_link("https://example.com") is True
        assert self.handler._is_only_link("http://test.org") is True
        assert self.handler._is_only_link("www.example.com") is True
        assert self.handler._is_only_link("t.me/username") is True
        assert self.handler._is_only_link("@username") is True

        # 非链接
        assert self.handler._is_only_link("这是一段文字") is False
        assert self.handler._is_only_link("文字 https://link.com") is False

    def test_extract_link(self):
        """测试链接提取"""
        link1 = self.handler._extract_link("https://example.com")
        assert link1 == "https://example.com"

        link2 = self.handler._extract_link("访问 https://test.org 了解更多")
        assert link2 == "https://test.org"

        link3 = self.handler._extract_link("@username")
        assert link3 == "@username"

    def test_extract_blacklist_content_link(self):
        """测试提取链接黑名单内容"""
        from unittest.mock import MagicMock

        message = MagicMock()
        message.text = "https://spam.com"
        message.via_bot = None
        message.sticker = None
        message.animation = None

        blacklist_type, content = self.handler._extract_blacklist_content(message)
        assert blacklist_type == "link"
        assert content == "https://spam.com"

    def test_extract_blacklist_content_sticker(self):
        """测试提取贴纸黑名单内容"""
        from unittest.mock import MagicMock

        message = MagicMock()
        message.via_bot = None
        message.text = None
        message.sticker = MagicMock()
        message.sticker.file_unique_id = "AgADAgADmqcx"
        message.animation = None

        blacklist_type, content = self.handler._extract_blacklist_content(message)
        assert blacklist_type == "sticker"
        assert content == "AgADAgADmqcx"

    def test_extract_blacklist_content_gif(self):
        """测试提取GIF黑名单内容"""
        from unittest.mock import MagicMock

        message = MagicMock()
        message.via_bot = None
        message.text = None
        message.sticker = None
        message.animation = MagicMock()
        message.animation.file_id = "CgACAgQAAxkBAAID"

        blacklist_type, content = self.handler._extract_blacklist_content(message)
        assert blacklist_type == "gif"
        assert content == "CgACAgQAAxkBAAID"

    def test_extract_blacklist_content_bot(self):
        """测试提取内联Bot黑名单内容"""
        from unittest.mock import MagicMock

        from telegram import User

        bot_user = User(id=123456, first_name="TestBot", is_bot=True)
        message = MagicMock()
        message.via_bot = bot_user
        message.text = "Some content"
        message.sticker = None
        message.animation = None

        blacklist_type, content = self.handler._extract_blacklist_content(message)
        assert blacklist_type == "bot"
        assert content == "123456"

    def test_extract_blacklist_content_text(self):
        """测试提取文字黑名单内容"""
        from unittest.mock import MagicMock

        message = MagicMock()
        message.via_bot = None
        message.text = "这是一条垃圾消息"
        message.sticker = None
        message.animation = None

        blacklist_type, content = self.handler._extract_blacklist_content(message)
        assert blacklist_type == "text"
        # 应该返回哈希
        assert len(content) == 64
        assert all(c in "0123456789abcdef" for c in content)

    def test_extract_blacklist_content_none(self):
        """测试无法识别的消息类型"""
        from unittest.mock import MagicMock

        message = MagicMock()
        message.via_bot = None
        message.text = None
        message.sticker = None
        message.animation = None

        blacklist_type, content = self.handler._extract_blacklist_content(message)
        assert blacklist_type is None
        assert content is None
