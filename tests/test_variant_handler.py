"""变体复评接到首条检测上。不调用真实 Telegram 或模型。"""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot import POLLED_UPDATE_TYPES
from services.clef_client import ClefScore
from utils.telegram_identity import TELEGRAM_SERVICE_USER_ID

CHAT = -100424242001
USER = 555001
AD = "日入5000+🔥"


class Clock:
    def __init__(self):
        self.now = 1_700_000_000.0

    def time(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeClef:
    def __init__(self):
        self.profile_calls = 0
        self.detail_calls = []
        self.profile_score = ClefScore(0.20, 0.2)
        self.detail_result = (ClefScore(0.91, 1.3), None)

    def is_configured(self):
        return True

    async def score_profile(self, state, questions=None):
        self.profile_calls += 1
        return self.profile_score

    async def score_profile_detailed(self, state, questions=None):
        self.detail_calls.append(state)
        return self.detail_result


def _message(text="你好", *, user_id=USER, chat_id=CHAT, message_id=1, caption=None):
    message = MagicMock()
    message.from_user = MagicMock(
        id=user_id, is_bot=False, first_name="合成", last_name=None, username="synthetic"
    )
    message.from_user.mention_html = MagicMock(return_value="synthetic")
    message.chat = MagicMock(id=chat_id, title="合成群", type="supergroup")
    message.text = text
    message.caption = caption
    message.message_id = message_id
    message.sender_chat = None
    message.is_automatic_forward = False
    message.forward_origin = None
    message.via_bot = None
    message.sticker = None
    message.delete = AsyncMock()
    return message


def _context():
    context = MagicMock()
    context.bot.id = 1
    context.bot.get_chat = AsyncMock(side_effect=Exception("no bio"))
    context.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="member"))
    context.bot.ban_chat_member = AsyncMock()
    context.bot.unban_chat_member = AsyncMock()
    context.bot.send_message = AsyncMock()
    return context


def _handler(temp_db_path, client):
    from database.models import DatabaseManager
    from handlers.clef_handler import ClefHandler

    handler = ClefHandler(db=DatabaseManager(db_path=temp_db_path), client=client)
    handler.variant.config["mode"] = "enforce"
    handler.variant.config["chat_ids"] = set()
    return handler


def _samples(db, chat_id=CHAT, user_id=USER):
    with sqlite3.connect(db.db_path) as connection:
        return connection.execute(
            "SELECT excerpt FROM clef_variant_samples WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        ).fetchall()


def test_polling_does_not_include_edits_or_channel_posts():
    assert "edited_message" not in POLLED_UPDATE_TYPES
    assert "channel_post" not in POLLED_UPDATE_TYPES
    assert "edited_channel_post" not in POLLED_UPDATE_TYPES
    assert "message" in POLLED_UPDATE_TYPES


@pytest.mark.asyncio
class TestVariantHandler:
    async def test_mode_off_keeps_single_first_message_score(self, temp_db_path):
        client = FakeClef()
        handler = _handler(temp_db_path, client)
        handler.variant.config["mode"] = "off"
        context = _context()
        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0, "log_actions": False}
            assert await handler.check_first_message(_message(AD, message_id=1), context) is False
            assert (
                await handler.check_first_message(_message(AD + "💰", message_id=2), context)
                is False
            )
        assert client.profile_calls == 1
        assert client.detail_calls == []
        assert _samples(handler.db) == []
        assert handler.db.has_clef_message_scored(CHAT, USER) is True

    async def test_first_threshold_is_unchanged(self, temp_db_path):
        client = FakeClef()
        client.profile_score = ClefScore(0.80, 0.1)
        handler = _handler(temp_db_path, client)
        context = _context()
        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0, "log_actions": False}
            hit = await handler.check_first_message(_message(AD), context)
        assert hit is True
        assert client.detail_calls == []
        assert handler.db.check_blacklist(CHAT, "user", str(USER)) is True
        assert handler.db.check_global_blacklist("user", str(USER)) is False

    async def test_low_first_score_then_slow_ads_ban_only_the_current_message(self, temp_db_path):
        client = FakeClef()
        client.profile_score = ClefScore(0.12, 0.2)
        handler = _handler(temp_db_path, client)
        clock = Clock()
        handler.variant._clock = clock.time
        context = _context()
        texts = ["大家好今天只是来打个招呼", AD, AD + "💰", "日.入.5.0.0.0+", "日入5a000+"]
        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0, "log_actions": False}
            first = await handler.check_first_message(_message(texts[0], message_id=1), context)
            assert first is False
            hit = False
            for index, text in enumerate(texts[1:], start=2):
                clock.advance(450)
                hit = await handler.check_first_message(_message(text, message_id=index), context)
                if hit:
                    break
        assert hit is True
        assert client.profile_calls == 1
        assert len(client.detail_calls) == 1
        assert "大家好" not in client.detail_calls[0]
        context.bot.ban_chat_member.assert_awaited()
        assert handler.db.check_blacklist(CHAT, "user", str(USER)) is True
        assert handler.db.check_global_blacklist("user", str(USER)) is False
        assert handler.db.has_clef_join_scored(CHAT, USER) is True
        with sqlite3.connect(handler.db.db_path) as connection:
            content = connection.execute(
                "SELECT target_content FROM action_logs WHERE action_type = 'clef_variant_ban'"
            ).fetchone()
        assert content == ("variant_review",)

    async def test_shadow_records_would_ban_without_enforcing(self, temp_db_path):
        client = FakeClef()
        handler = _handler(temp_db_path, client)
        handler.variant.config["mode"] = "shadow"
        handler.db.mark_clef_message_scored(CHAT, USER)
        clock = Clock()
        handler.variant._clock = clock.time
        context = _context()
        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0, "log_actions": False}
            hit = False
            for index in range(4):
                hit = await handler.check_first_message(
                    _message(AD, message_id=10 + index), context
                )
                clock.advance(450)
        assert hit is False
        assert client.detail_calls
        context.bot.ban_chat_member.assert_not_awaited()
        assert handler.db.check_blacklist(CHAT, "user", str(USER)) is False

    async def test_allowlist_keeps_other_chats_on_the_old_path(self, temp_db_path):
        client = FakeClef()
        handler = _handler(temp_db_path, client)
        handler.variant.config["chat_ids"] = {-100999}
        context = _context()
        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0, "log_actions": False}
            await handler.check_first_message(_message("大家好今天只是来打个招呼"), context)
            await handler.check_first_message(_message(AD, message_id=2), context)
        assert client.profile_calls == 1
        assert client.detail_calls == []
        assert _samples(handler.db) == []

    async def test_service_and_channel_senders_are_not_tracked(self, temp_db_path):
        client = FakeClef()
        handler = _handler(temp_db_path, client)
        context = _context()
        service = _message(AD, user_id=TELEGRAM_SERVICE_USER_ID)
        service.is_automatic_forward = True
        service.sender_chat = MagicMock(id=-100900001)
        channel = _message(AD, message_id=2)
        channel.sender_chat = MagicMock(id=-100900002)
        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            assert await handler.check_first_message(service, context) is False
            assert await handler.check_first_message(channel, context) is False
        assert client.profile_calls == 0
        assert client.detail_calls == []
        assert _samples(handler.db, user_id=TELEGRAM_SERVICE_USER_ID) == []
        context.bot.ban_chat_member.assert_not_awaited()

    async def test_unban_clears_variant_state_but_keeps_scored_mark(self, temp_db_path):
        from handlers.blacklist_handler import BlacklistHandler

        client = FakeClef()
        handler = _handler(temp_db_path, client)
        clock = Clock()
        handler.variant._clock = clock.time
        context = _context()
        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0, "log_actions": False}
            for index in range(4):
                await handler.check_first_message(_message(AD, message_id=index + 1), context)
                clock.advance(450)
        assert handler.db.check_blacklist(CHAT, "user", str(USER)) is True
        assert handler.db.has_clef_message_scored(CHAT, USER) is True
        blacklist = BlacklistHandler(db=handler.db)
        command = _message(f"/unban {USER}", message_id=99)
        with patch.object(blacklist, "_is_admin_or_creator", AsyncMock(return_value=True)):
            await blacklist.handle_unban_command(MagicMock(message=command), context)
        assert handler.db.check_blacklist(CHAT, "user", str(USER)) is False
        assert handler.db.has_clef_message_scored(CHAT, USER) is True
        assert handler.db.has_clef_join_scored(CHAT, USER) is True
        assert _samples(handler.db) == []

    async def test_caption_uses_the_same_variant_path(self, temp_db_path):
        client = FakeClef()
        client.profile_score = ClefScore(0.10, 0.1)
        handler = _handler(temp_db_path, client)
        clock = Clock()
        handler.variant._clock = clock.time
        context = _context()
        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0, "log_actions": False}
            for index in range(4):
                message = _message(None, message_id=index + 1, caption=AD)
                clock.advance(450 if index else 0)
                await handler.check_first_message(message, context)
        assert client.profile_calls == 1
        assert len(client.detail_calls) == 1
