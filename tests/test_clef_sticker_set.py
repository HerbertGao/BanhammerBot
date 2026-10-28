"""纯贴纸广告：贴纸包标题接入 clef 首条检测（不调用真实 API）。"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from handlers.clef_handler import (
    build_message_state,
    format_sticker_set_message,
)
from services.sticker_set_cache import (
    StickerSetTitleCache,
    clear_sticker_set_title_cache,
    lookup_sticker_set_title,
)

SET_NAME = "wancailai"
TITLE = "飞机号 @tsy999000 群 @kaiyungoo"
BODY = f"{TITLE}（{SET_NAME}）"
FILE_UNIQUE_ID = "AgADAgADmqcx"
CHAT_ID = -100555
_NO_STICKER = object()


@pytest.fixture(autouse=True)
def _reset_sticker_title_cache():
    clear_sticker_set_title_cache()
    yield
    clear_sticker_set_title_cache()


@contextmanager
def _clef_enabled():
    with (
        patch("handlers.clef_handler.Config") as cfg,
        patch("services.clef_client.Config.CLEF_AUTO_KICK_THRESHOLD", 0.85),
    ):
        cfg.CLEF_ENABLED = True
        cfg.BLACKLIST_CONFIG = {"ban_duration": 0, "log_actions": False}
        yield cfg


def _handler(db_path, score=None):
    from database.models import DatabaseManager
    from handlers.clef_handler import ClefHandler
    from services.clef_client import ClefClient

    db = DatabaseManager(db_path=db_path)
    client = ClefClient(account_id="a", api_token="t", enabled=True)
    client.score_profile = AsyncMock(return_value=score)
    return db, client, ClefHandler(db=db, client=client)


def _group_message(*, text=None, caption=None, set_name=SET_NAME, user_id=555):
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = user_id
    message.from_user.is_bot = False
    message.from_user.first_name = "Ad"
    message.from_user.last_name = "Bot"
    message.from_user.username = "adbot"
    message.from_user.mention_html = MagicMock(return_value="ad")
    message.chat = MagicMock()
    message.chat.id = CHAT_ID
    message.chat.title = "G"
    message.text = text
    message.caption = caption
    message.message_id = user_id
    message.delete = AsyncMock()

    if set_name is _NO_STICKER:
        message.sticker = None
    else:
        message.sticker = MagicMock()
        message.sticker.set_name = set_name
        message.sticker.file_unique_id = FILE_UNIQUE_ID
        message.sticker.file_id = "FILEID"

    context = MagicMock()
    context.bot.id = 1
    context.bot.get_chat = AsyncMock(side_effect=Exception("no bio"))
    context.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="member"))
    context.bot.ban_chat_member = AsyncMock()
    context.bot.send_message = AsyncMock()
    context.bot.get_file = AsyncMock()
    context.bot.get_sticker_set = AsyncMock(return_value=SimpleNamespace(title=TITLE))
    return message, context


class TestFormatStickerSetMessage:
    def test_title_is_the_message_and_set_name_is_appended(self):
        assert format_sticker_set_message(TITLE, SET_NAME) == BODY

    def test_set_name_already_in_title_is_not_repeated(self):
        assert format_sticker_set_message(f"{TITLE} {SET_NAME}", SET_NAME) == f"{TITLE} {SET_NAME}"

    def test_empty_title_does_not_guess_from_set_name(self):
        assert format_sticker_set_message("", SET_NAME) == ""
        assert format_sticker_set_message("   ", SET_NAME) == ""


class TestStickerSetTitleCache:
    def test_ttl_expires_entry(self):
        now = {"t": 100.0}
        cache = StickerSetTitleCache(maxsize=4, ttl_seconds=10, clock=lambda: now["t"])
        cache.put(SET_NAME, TITLE)

        assert cache.get(SET_NAME) == TITLE
        now["t"] = 110.0
        assert cache.get(SET_NAME) is None

    def test_lru_evicts_least_recently_used(self):
        cache = StickerSetTitleCache(maxsize=2, ttl_seconds=100, clock=lambda: 0.0)
        cache.put("a", "A")
        cache.put("b", "B")
        assert cache.get("a") == "A"

        cache.put("c", "C")

        assert cache.get("b") is None
        assert cache.get("a") == "A"
        assert cache.get("c") == "C"

    def test_blank_title_is_not_stored(self):
        cache = StickerSetTitleCache(clock=lambda: 0.0)
        cache.put(SET_NAME, "  ")
        assert cache.get(SET_NAME) is None


@pytest.mark.asyncio
class TestLookupStickerSetTitle:
    async def test_blank_set_name_skips_api(self):
        bot = MagicMock()
        bot.get_sticker_set = AsyncMock()
        assert await lookup_sticker_set_title(bot, "   ") is None
        bot.get_sticker_set.assert_not_awaited()

    async def test_non_string_title_fail_open(self):
        bot = MagicMock()
        bot.get_sticker_set = AsyncMock(return_value=SimpleNamespace(title=None))
        assert await lookup_sticker_set_title(bot, SET_NAME) is None

    async def test_second_lookup_uses_cache(self):
        bot = MagicMock()
        bot.get_sticker_set = AsyncMock(return_value=SimpleNamespace(title=TITLE))

        assert await lookup_sticker_set_title(bot, SET_NAME) == TITLE
        assert await lookup_sticker_set_title(bot, SET_NAME) == TITLE

        bot.get_sticker_set.assert_awaited_once_with(SET_NAME)

    async def test_api_error_is_not_cached(self):
        bot = MagicMock()
        bot.get_sticker_set = AsyncMock(side_effect=RuntimeError("STICKERSET_INVALID"))
        assert await lookup_sticker_set_title(bot, SET_NAME) is None

        bot.get_sticker_set = AsyncMock(return_value=SimpleNamespace(title=TITLE))
        assert await lookup_sticker_set_title(bot, SET_NAME) == TITLE
        bot.get_sticker_set.assert_awaited_once_with(SET_NAME)

    async def test_blank_title_is_not_cached(self):
        bot = MagicMock()
        bot.get_sticker_set = AsyncMock(return_value=SimpleNamespace(title="  "))
        assert await lookup_sticker_set_title(bot, SET_NAME) is None

        bot.get_sticker_set = AsyncMock(return_value=SimpleNamespace(title=TITLE))
        assert await lookup_sticker_set_title(bot, SET_NAME) == TITLE
        bot.get_sticker_set.assert_awaited_once()

    async def test_concurrent_lookups_share_one_request(self):
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def get_sticker_set(name):
            nonlocal calls
            calls += 1
            assert name == SET_NAME
            started.set()
            await release.wait()
            return SimpleNamespace(title=TITLE)

        bot = MagicMock()
        bot.get_sticker_set = get_sticker_set
        first = asyncio.create_task(lookup_sticker_set_title(bot, SET_NAME))
        await started.wait()
        second = asyncio.create_task(lookup_sticker_set_title(bot, f"  {SET_NAME}  "))
        await asyncio.sleep(0)
        release.set()

        assert await first == TITLE
        assert await second == TITLE
        assert calls == 1


@pytest.mark.asyncio
class TestClefStickerFirstMessage:
    async def test_plain_sticker_ad_title_bans_user_not_set(self, temp_db_path):
        """纯 sticker + 广告包标题命中：删消息、本群封禁、只写 user 黑名单。"""
        from services.clef_client import ClefScore

        db, client, handler = _handler(temp_db_path, ClefScore(0.92, 2.6))
        message, context = _group_message()

        with _clef_enabled():
            hit = await handler.check_first_message(message, context)

        assert hit is True
        client.score_profile.assert_awaited_once_with(build_message_state("Ad Bot", "", BODY))
        context.bot.get_sticker_set.assert_awaited_once_with(SET_NAME)
        context.bot.get_file.assert_not_awaited()
        message.delete.assert_awaited()
        context.bot.ban_chat_member.assert_awaited()
        assert db.check_blacklist(CHAT_ID, "user", "555") is True
        assert db.check_blacklist(CHAT_ID, "sticker", SET_NAME) is False
        assert db.check_blacklist(CHAT_ID, "sticker", FILE_UNIQUE_ID) is False
        assert db.check_global_blacklist("user", "555") is False
        assert db.check_global_blacklist("sticker", SET_NAME) is False
        assert db.has_clef_message_scored(CHAT_ID, 555) is True
        assert db.has_clef_join_scored(CHAT_ID, 555) is True

    async def test_same_set_is_fetched_once_for_two_users(self, temp_db_path):
        from services.clef_client import ClefScore

        db, client, handler = _handler(temp_db_path, ClefScore(0.92, 2.6))
        first, context = _group_message(user_id=555)
        second, second_context = _group_message(user_id=556)
        second_context.bot = context.bot

        with _clef_enabled():
            assert await handler.check_first_message(first, context) is True
            assert await handler.check_first_message(second, second_context) is True

        context.bot.get_sticker_set.assert_awaited_once_with(SET_NAME)
        assert client.score_profile.await_count == 2
        assert db.check_blacklist(CHAT_ID, "user", "555") is True
        assert db.check_blacklist(CHAT_ID, "user", "556") is True
        assert db.check_blacklist(CHAT_ID, "sticker", SET_NAME) is False

    @pytest.mark.parametrize("set_name", [_NO_STICKER, None, "", "   "])
    async def test_without_set_name_skips(self, temp_db_path, set_name):
        db, client, handler = _handler(temp_db_path)
        message, context = _group_message(set_name=set_name)

        with _clef_enabled():
            hit = await handler.check_first_message(message, context)

        assert hit is False
        client.score_profile.assert_not_awaited()
        context.bot.get_sticker_set.assert_not_awaited()
        context.bot.ban_chat_member.assert_not_awaited()
        message.delete.assert_not_awaited()
        assert db.has_clef_message_scored(CHAT_ID, 555) is False
        assert db.check_blacklist(CHAT_ID, "user", "555") is False

    @pytest.mark.parametrize("field", ["text", "caption"])
    async def test_text_or_caption_keeps_original_body(self, temp_db_path, field):
        from services.clef_client import ClefScore

        db, client, handler = _handler(temp_db_path, ClefScore(0.92, 2.6))
        message, context = _group_message()
        message.text = None
        message.caption = None
        setattr(message, field, "加群看项目 日赚10000")
        context.bot.get_sticker_set = AsyncMock(
            return_value=SimpleNamespace(title="不应被使用的标题")
        )

        with _clef_enabled():
            hit = await handler.check_first_message(message, context)

        assert hit is True
        context.bot.get_sticker_set.assert_not_awaited()
        client.score_profile.assert_awaited_once_with(
            build_message_state("Ad Bot", "", "加群看项目 日赚10000")
        )
        assert db.check_blacklist(CHAT_ID, "user", "555") is True
        assert db.check_blacklist(CHAT_ID, "sticker", SET_NAME) is False

    async def test_whitespace_text_uses_sticker_title(self, temp_db_path):
        from services.clef_client import ClefScore

        _db, client, handler = _handler(temp_db_path, ClefScore(0.1, 0.0))
        message, context = _group_message(text="  \n  ")

        with _clef_enabled():
            hit = await handler.check_first_message(message, context)

        assert hit is False
        context.bot.get_sticker_set.assert_awaited_once_with(SET_NAME)
        client.score_profile.assert_awaited_once_with(build_message_state("Ad Bot", "", BODY))

    async def test_get_sticker_set_error_fail_open(self, temp_db_path):
        db, client, handler = _handler(temp_db_path)
        message, context = _group_message()
        context.bot.get_sticker_set = AsyncMock(side_effect=RuntimeError("STICKERSET_INVALID"))

        with _clef_enabled():
            hit = await handler.check_first_message(message, context)

        assert hit is False
        client.score_profile.assert_not_awaited()
        context.bot.ban_chat_member.assert_not_awaited()
        message.delete.assert_not_awaited()
        assert db.has_clef_message_scored(CHAT_ID, 555) is False
        assert db.has_clef_join_scored(CHAT_ID, 555) is False

    async def test_blank_title_fail_open(self, temp_db_path):
        db, client, handler = _handler(temp_db_path)
        message, context = _group_message()
        context.bot.get_sticker_set = AsyncMock(return_value=SimpleNamespace(title="  "))

        with _clef_enabled():
            hit = await handler.check_first_message(message, context)

        assert hit is False
        client.score_profile.assert_not_awaited()
        assert db.has_clef_message_scored(CHAT_ID, 555) is False
        context.bot.ban_chat_member.assert_not_awaited()

    async def test_admin_sticker_skips_before_api(self, temp_db_path):
        _db, client, handler = _handler(temp_db_path)
        message, context = _group_message()
        context.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="administrator"))

        with _clef_enabled():
            hit = await handler.check_first_message(message, context)

        assert hit is False
        context.bot.get_sticker_set.assert_not_awaited()
        client.score_profile.assert_not_awaited()

    async def test_already_scored_sticker_skips_before_api(self, temp_db_path):
        db, client, handler = _handler(temp_db_path)
        db.mark_clef_message_scored(CHAT_ID, 555)
        message, context = _group_message()

        with _clef_enabled():
            hit = await handler.check_first_message(message, context)

        assert hit is False
        context.bot.get_sticker_set.assert_not_awaited()
        client.score_profile.assert_not_awaited()

    async def test_disabled_skips_before_api(self, temp_db_path):
        _db, client, handler = _handler(temp_db_path)
        message, context = _group_message()

        with _clef_enabled() as cfg:
            cfg.CLEF_ENABLED = False
            hit = await handler.check_first_message(message, context)

        assert hit is False
        context.bot.get_sticker_set.assert_not_awaited()
        client.score_profile.assert_not_awaited()

    async def test_bot_sticker_skips_before_api(self, temp_db_path):
        _db, client, handler = _handler(temp_db_path)
        message, context = _group_message()
        message.from_user.is_bot = True

        with _clef_enabled():
            hit = await handler.check_first_message(message, context)

        assert hit is False
        context.bot.get_sticker_set.assert_not_awaited()
        client.score_profile.assert_not_awaited()

    async def test_missing_message_skips(self, temp_db_path):
        _db, client, handler = _handler(temp_db_path)
        _message, context = _group_message()

        with _clef_enabled():
            hit = await handler.check_first_message(None, context)

        assert hit is False
        client.score_profile.assert_not_awaited()

    async def test_delete_failure_still_bans(self, temp_db_path):
        from services.clef_client import ClefScore

        db, _client, handler = _handler(temp_db_path, ClefScore(0.92, 2.6))
        message, context = _group_message()
        message.delete = AsyncMock(side_effect=RuntimeError("cannot delete"))

        with _clef_enabled():
            hit = await handler.check_first_message(message, context)

        assert hit is True
        assert db.check_blacklist(CHAT_ID, "user", "555") is True
        assert db.check_blacklist(CHAT_ID, "sticker", SET_NAME) is False
        context.bot.ban_chat_member.assert_awaited()

    async def test_score_failure_does_not_mark(self, temp_db_path):
        db, client, handler = _handler(temp_db_path, None)
        message, context = _group_message()

        with _clef_enabled():
            hit = await handler.check_first_message(message, context)

        assert hit is False
        client.score_profile.assert_awaited_once()
        context.bot.ban_chat_member.assert_not_awaited()
        assert db.has_clef_message_scored(CHAT_ID, 555) is False

    async def test_below_threshold_marks_message_only(self, temp_db_path):
        from services.clef_client import ClefScore

        db, client, handler = _handler(temp_db_path, ClefScore(0.84, 1.0))
        message, context = _group_message()

        with _clef_enabled():
            hit = await handler.check_first_message(message, context)

        assert hit is False
        client.score_profile.assert_awaited_once()
        assert db.has_clef_message_scored(CHAT_ID, 555) is True
        assert db.has_clef_join_scored(CHAT_ID, 555) is False
        context.bot.ban_chat_member.assert_not_awaited()
        assert db.check_blacklist(CHAT_ID, "user", "555") is False
        assert db.check_blacklist(CHAT_ID, "sticker", SET_NAME) is False
