"""服务身份、频道自动转发和匿名管理员不能进入 user 黑名单。

用例全部使用虚构的群、频道和用户。不读取生产库，也不复述真实消息。
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Update, User

from utils.telegram_identity import (
    CHANNEL_BOT_USER_ID,
    GROUP_ANONYMOUS_BOT_ID,
    TELEGRAM_SERVICE_USER_ID,
    is_service_user_blacklist,
    ordinary_user,
)

GROUP_ID = -100424242001
CHANNEL_A = -100900001
CHANNEL_B = -100900002
REAL_USER_ID = 555001
SPAM_BOT_ID = 900001
# 和 777000 共享前缀，但不是服务身份，不能被前缀规则误伤。
LOOKALIKE_USER_ID = 777
AD_TEXT = "虚构广告：加群看项目，日赚一万"
NORMAL_TEXT = "虚构的正常频道更新"


def _user(user_id: int, *, is_bot: bool = False, first_name: str = "User") -> User:
    return User(id=user_id, first_name=first_name, is_bot=is_bot, username=f"u{user_id}")


def _message(
    *,
    user_id: int | None,
    text: str = NORMAL_TEXT,
    is_bot: bool = False,
    first_name: str = "User",
    sender_chat_id: int | None = None,
    automatic: bool = False,
    forward_origin: object | None = None,
    chat_id: int = GROUP_ID,
):
    message = MagicMock()
    message.chat = MagicMock()
    message.chat.id = chat_id
    message.chat.title = "Fiction Group"
    message.message_id = 1000 + (user_id or 0)
    message.text = text
    message.caption = None
    message.via_bot = None
    message.sticker = None
    message.animation = None
    message.delete = AsyncMock()
    message.is_automatic_forward = automatic
    message.forward_origin = forward_origin
    message.sender_chat = (
        None if sender_chat_id is None else SimpleNamespace(id=sender_chat_id, type="channel")
    )
    message.from_user = (
        None if user_id is None else _user(user_id, is_bot=is_bot, first_name=first_name)
    )
    return message


def _context():
    context = MagicMock()
    context.bot.id = 1
    context.bot.ban_chat_member = AsyncMock()
    context.bot.unban_chat_member = AsyncMock()
    context.bot.send_message = AsyncMock(return_value=MagicMock())
    context.bot.get_chat = AsyncMock(side_effect=Exception("no bio"))
    context.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="member"))
    return context


def _plant_user_blacklist(db, user_id: int, *, global_list: bool = False, chat_id: int = GROUP_ID):
    """模拟升级前已经落库的记录。不走 add_to_blacklist，因为新代码会拒绝服务身份。"""
    with sqlite3.connect(db.db_path) as conn:
        if global_list:
            conn.execute(
                """
                INSERT INTO global_blacklists
                    (blacklist_type, blacklist_content, contributed_by, usage_count)
                VALUES ('user', ?, ?, 0)
                """,
                (str(user_id), chat_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO group_blacklists
                    (chat_id, blacklist_type, blacklist_content, created_by)
                VALUES (?, 'user', ?, 1)
                """,
                (chat_id, str(user_id)),
            )


def _usage_count(db, user_id: int) -> int:
    with sqlite3.connect(db.db_path) as conn:
        row = conn.execute(
            """
            SELECT usage_count FROM global_blacklists
            WHERE blacklist_type = 'user' AND blacklist_content = ?
            """,
            (str(user_id),),
        ).fetchone()
    assert row is not None
    return row[0]


class TestOrdinaryUser:
    def test_service_ids_and_chat_senders_are_not_users(self):
        assert (
            ordinary_user(
                _message(user_id=TELEGRAM_SERVICE_USER_ID, automatic=True, sender_chat_id=CHANNEL_A)
            )
            is None
        )
        assert ordinary_user(_message(user_id=TELEGRAM_SERVICE_USER_ID)) is None
        assert (
            ordinary_user(
                _message(
                    user_id=GROUP_ANONYMOUS_BOT_ID,
                    is_bot=True,
                    first_name="Group",
                    sender_chat_id=GROUP_ID,
                )
            )
            is None
        )
        assert (
            ordinary_user(
                _message(user_id=CHANNEL_BOT_USER_ID, is_bot=True, sender_chat_id=CHANNEL_A)
            )
            is None
        )
        assert ordinary_user(_message(user_id=CHANNEL_BOT_USER_ID, is_bot=True)) is None
        # 结构信号优先于具体 id：看起来像真人，但消息是频道代发。
        assert (
            ordinary_user(_message(user_id=REAL_USER_ID, automatic=True, sender_chat_id=CHANNEL_A))
            is None
        )
        assert ordinary_user(_message(user_id=REAL_USER_ID, sender_chat_id=CHANNEL_A)) is None

    def test_real_user_and_manual_forward_stay_accountable(self):
        direct = ordinary_user(_message(user_id=REAL_USER_ID, text=AD_TEXT))
        assert direct is not None and direct.id == REAL_USER_ID

        forwarded = ordinary_user(
            _message(
                user_id=REAL_USER_ID,
                text=AD_TEXT,
                forward_origin=SimpleNamespace(type="channel", chat_id=CHANNEL_A),
            )
        )
        assert forwarded is not None and forwarded.id == REAL_USER_ID
        assert ordinary_user(_message(user_id=None)) is None

    def test_lookalike_ids_are_not_service_identities(self):
        assert is_service_user_blacklist("user", str(LOOKALIKE_USER_ID)) is False
        assert is_service_user_blacklist("user", "7770000") is False
        assert is_service_user_blacklist("user", f" {TELEGRAM_SERVICE_USER_ID} ") is True
        assert is_service_user_blacklist("link", str(TELEGRAM_SERVICE_USER_ID)) is False
        assert is_service_user_blacklist("user", str(GROUP_ANONYMOUS_BOT_ID)) is True
        assert is_service_user_blacklist("user", str(CHANNEL_BOT_USER_ID)) is True

    def test_threshold_and_prompt_stay(self):
        from config import Config
        from services import clef_prompt
        from services.clef_client import ClefScore

        assert Config.CLEF_AUTO_KICK_THRESHOLD == 0.80
        assert clef_prompt.__doc__ and "v4.2" in clef_prompt.__doc__
        assert "抵押车" in clef_prompt.IS_AD_INSTRUCTIONS
        assert ClefScore(0.80, 1.0).should_auto_kick() is True
        assert ClefScore(0.7999, 1.0).should_auto_kick() is False


def _handlers(db_path, score=None):
    from database.models import DatabaseManager
    from handlers.blacklist_handler import BlacklistHandler
    from handlers.clef_handler import ClefHandler
    from services.clef_client import ClefClient

    db = DatabaseManager(db_path=db_path)
    client = ClefClient(account_id="a", api_token="t", enabled=True)
    client.score_profile = AsyncMock(return_value=score)
    return db, client, BlacklistHandler(db=db), ClefHandler(db=db, client=client)


@pytest.mark.asyncio
class TestServiceIdentityNotBlacklisted:
    async def test_channel_forward_is_not_scored_or_blacklisted(self, temp_db_path):
        from services.clef_client import ClefScore

        db, client, blacklist, clef = _handlers(temp_db_path, ClefScore(0.91, 2.5))
        context = _context()
        first = _message(
            user_id=TELEGRAM_SERVICE_USER_ID,
            text=AD_TEXT,
            first_name="Telegram",
            automatic=True,
            sender_chat_id=CHANNEL_A,
        )
        second = _message(
            user_id=TELEGRAM_SERVICE_USER_ID,
            text=NORMAL_TEXT,
            first_name="Telegram",
            automatic=True,
            sender_chat_id=CHANNEL_B,
        )

        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0, "log_actions": False}
            assert await blacklist.check_blacklist(first, context) is False
            assert await clef.check_first_message(first, context) is False
            assert await blacklist.check_blacklist(second, context) is False

        client.score_profile.assert_not_awaited()
        context.bot.ban_chat_member.assert_not_awaited()
        first.delete.assert_not_awaited()
        second.delete.assert_not_awaited()
        assert db.check_blacklist(GROUP_ID, "user", str(TELEGRAM_SERVICE_USER_ID)) is False
        assert db.check_global_blacklist("user", str(TELEGRAM_SERVICE_USER_ID)) is False

    async def test_sender_chat_without_service_id_does_not_blacklist_that_id(self, temp_db_path):
        """频道代发时即使 from 看起来像真人，也不能把这个 id 写成用户。"""
        from services.clef_client import ClefScore

        db, client, blacklist, clef = _handlers(temp_db_path, ClefScore(0.91, 2.5))
        context = _context()
        posted_as_channel = _message(
            user_id=REAL_USER_ID,
            text=AD_TEXT,
            automatic=False,
            sender_chat_id=CHANNEL_A,
        )

        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0, "log_actions": False}
            assert await clef.check_first_message(posted_as_channel, context) is False
            assert await blacklist.check_blacklist(posted_as_channel, context) is False

        client.score_profile.assert_not_awaited()
        assert db.check_blacklist(GROUP_ID, "user", str(REAL_USER_ID)) is False
        posted_as_channel.delete.assert_not_awaited()

    async def test_anonymous_admin_and_channel_bot_skip_user_blacklist(self, temp_db_path):
        db, client, blacklist, clef = _handlers(temp_db_path)
        _plant_user_blacklist(db, GROUP_ANONYMOUS_BOT_ID)
        _plant_user_blacklist(db, CHANNEL_BOT_USER_ID)
        context = _context()
        anonymous = _message(
            user_id=GROUP_ANONYMOUS_BOT_ID,
            is_bot=True,
            first_name="Group",
            text=NORMAL_TEXT,
            sender_chat_id=GROUP_ID,
        )
        channel_bot = _message(
            user_id=CHANNEL_BOT_USER_ID,
            is_bot=True,
            first_name="Channel",
            text=NORMAL_TEXT,
            sender_chat_id=CHANNEL_A,
        )

        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            assert await blacklist.check_blacklist(anonymous, context) is False
            assert await blacklist.check_blacklist(channel_bot, context) is False
            assert await clef.check_first_message(anonymous, context) is False
            assert await clef.check_first_message(channel_bot, context) is False

        client.score_profile.assert_not_awaited()
        context.bot.ban_chat_member.assert_not_awaited()
        anonymous.delete.assert_not_awaited()
        channel_bot.delete.assert_not_awaited()
        # 历史脏数据还在，只是不再被命中。
        assert db.check_blacklist(GROUP_ID, "user", str(GROUP_ANONYMOUS_BOT_ID)) is True
        assert db.check_blacklist(GROUP_ID, "user", str(CHANNEL_BOT_USER_ID)) is True

    async def test_historical_service_rows_do_not_delete_later_channel_posts(self, temp_db_path):
        db, client, blacklist, clef = _handlers(temp_db_path)
        _plant_user_blacklist(db, TELEGRAM_SERVICE_USER_ID)
        _plant_user_blacklist(db, TELEGRAM_SERVICE_USER_ID, global_list=True)
        context = _context()
        channel_a = _message(
            user_id=TELEGRAM_SERVICE_USER_ID,
            text=NORMAL_TEXT,
            first_name="Telegram",
            automatic=True,
            sender_chat_id=CHANNEL_A,
        )
        channel_b = _message(
            user_id=TELEGRAM_SERVICE_USER_ID,
            text="另一条虚构频道帖",
            first_name="Telegram",
            automatic=True,
            sender_chat_id=CHANNEL_B,
        )

        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            assert await blacklist.check_blacklist(channel_a, context) is False
            assert await clef.check_first_message(channel_a, context) is False
            assert await blacklist.check_blacklist(channel_b, context) is False

        client.score_profile.assert_not_awaited()
        context.bot.ban_chat_member.assert_not_awaited()
        channel_a.delete.assert_not_awaited()
        channel_b.delete.assert_not_awaited()
        assert db.check_blacklist(GROUP_ID, "user", str(TELEGRAM_SERVICE_USER_ID)) is True
        assert db.check_global_blacklist("user", str(TELEGRAM_SERVICE_USER_ID)) is True
        assert _usage_count(db, TELEGRAM_SERVICE_USER_ID) == 0

    async def test_content_blacklist_still_deletes_channel_post_without_banning_service_id(
        self, temp_db_path
    ):
        db, _client, blacklist, _clef = _handlers(temp_db_path)
        link = "https://fiction.example/spam"
        assert db.add_to_blacklist(GROUP_ID, "link", link, created_by=1) is True
        context = _context()
        message = _message(
            user_id=TELEGRAM_SERVICE_USER_ID,
            text=link,
            first_name="Telegram",
            automatic=True,
            sender_chat_id=CHANNEL_A,
        )

        assert await blacklist.check_blacklist(message, context) is True
        message.delete.assert_awaited()
        context.bot.ban_chat_member.assert_not_awaited()
        assert db.check_blacklist(GROUP_ID, "user", str(TELEGRAM_SERVICE_USER_ID)) is False

    async def test_real_user_ad_still_blocked_and_second_message_skips_clef(self, temp_db_path):
        from services.clef_client import ClefScore

        db, client, blacklist, clef = _handlers(temp_db_path, ClefScore(0.80, 2.0))
        context = _context()
        first = _message(user_id=REAL_USER_ID, text=AD_TEXT)
        second = _message(user_id=REAL_USER_ID, text="虚构的第二条广告")

        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0, "log_actions": False}
            assert await blacklist.check_blacklist(first, context) is False
            assert await clef.check_first_message(first, context) is True
            client.score_profile.assert_awaited()
            client.score_profile.reset_mock()
            assert await blacklist.check_blacklist(second, context) is True

        assert db.check_blacklist(GROUP_ID, "user", str(REAL_USER_ID)) is True
        assert db.check_global_blacklist("user", str(REAL_USER_ID)) is False
        second.delete.assert_awaited()
        assert context.bot.ban_chat_member.await_count == 2
        client.score_profile.assert_not_awaited()

    async def test_below_threshold_real_user_is_not_banned(self, temp_db_path):
        from services.clef_client import ClefScore

        db, client, _blacklist, clef = _handlers(temp_db_path, ClefScore(0.7999, 1.0))
        context = _context()
        message = _message(user_id=REAL_USER_ID, text=AD_TEXT)

        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0, "log_actions": False}
            assert await clef.check_first_message(message, context) is False

        client.score_profile.assert_awaited()
        context.bot.ban_chat_member.assert_not_awaited()
        message.delete.assert_not_awaited()
        assert db.check_blacklist(GROUP_ID, "user", str(REAL_USER_ID)) is False
        assert db.has_clef_message_scored(GROUP_ID, REAL_USER_ID) is True

    async def test_manual_forward_of_channel_post_still_uses_the_human(self, temp_db_path):
        from services.clef_client import ClefScore

        db, client, _blacklist, clef = _handlers(temp_db_path, ClefScore(0.91, 2.2))
        context = _context()
        message = _message(
            user_id=REAL_USER_ID,
            text=AD_TEXT,
            forward_origin=SimpleNamespace(type="channel", chat_id=CHANNEL_A),
        )

        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0, "log_actions": False}
            assert await clef.check_first_message(message, context) is True

        client.score_profile.assert_awaited()
        assert db.check_blacklist(GROUP_ID, "user", str(REAL_USER_ID)) is True
        assert db.check_blacklist(GROUP_ID, "user", str(TELEGRAM_SERVICE_USER_ID)) is False

    async def test_ban_user_refuses_service_identity(self, temp_db_path):
        from handlers.clef_handler import ClefHandler
        from services.clef_client import ClefScore

        db, _client, _blacklist, clef = _handlers(temp_db_path)
        assert isinstance(clef, ClefHandler)
        context = _context()
        chat = SimpleNamespace(id=GROUP_ID, title="Fiction Group")
        user = _user(TELEGRAM_SERVICE_USER_ID, first_name="Telegram")

        with patch("handlers.clef_handler.Config") as cfg:
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0, "log_actions": False}
            banned = await clef._ban_user(
                context=context,
                chat=chat,
                user=user,
                score=ClefScore(0.91, 2.5),
                content="fiction",
                reason="should not run",
                action_type="clef_message_ban",
            )

        assert banned is False
        context.bot.ban_chat_member.assert_not_awaited()
        assert db.check_blacklist(GROUP_ID, "user", str(TELEGRAM_SERVICE_USER_ID)) is False

    async def test_service_user_rejoin_does_not_ban_dirty_row(self, temp_db_path):
        from telegram import ChatMemberUpdated

        db, client, _blacklist, clef = _handlers(temp_db_path)
        _plant_user_blacklist(db, TELEGRAM_SERVICE_USER_ID)
        user = _user(TELEGRAM_SERVICE_USER_ID, first_name="Telegram")
        chat = SimpleNamespace(id=GROUP_ID, type="supergroup", title="Fiction Group")
        result = MagicMock(spec=ChatMemberUpdated)
        result.old_chat_member.status = "left"
        result.new_chat_member.status = "member"
        result.new_chat_member.user = user
        result.chat = chat
        update = MagicMock()
        update.chat_member = result
        update.effective_message = None
        context = _context()

        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0}
            await clef.handle_chat_member(update, context)

        client.score_profile.assert_not_awaited()
        context.bot.ban_chat_member.assert_not_awaited()
        assert db.check_blacklist(GROUP_ID, "user", str(TELEGRAM_SERVICE_USER_ID)) is True


@pytest.mark.asyncio
class TestManualBlacklistPath:
    async def test_manual_user_blacklist_still_blocks_that_user(self, temp_db_path):
        db, _client, blacklist, _clef = _handlers(temp_db_path)
        assert db.add_to_blacklist(GROUP_ID, "user", str(REAL_USER_ID), created_by=1) is True
        assert db.add_to_blacklist(GROUP_ID, "user", str(SPAM_BOT_ID), created_by=1) is True
        assert (
            db.add_to_blacklist(GROUP_ID, "user", str(TELEGRAM_SERVICE_USER_ID), created_by=1)
            is False
        )
        assert (
            db.add_to_blacklist(GROUP_ID, "user", str(GROUP_ANONYMOUS_BOT_ID), created_by=1)
            is False
        )
        assert (
            db.add_to_global_blacklist("user", str(CHANNEL_BOT_USER_ID), contributed_by=GROUP_ID)
            is False
        )
        assert db.add_to_blacklist(GROUP_ID, "user", str(LOOKALIKE_USER_ID), created_by=1) is True
        assert (
            db.add_to_blacklist(GROUP_ID, "link", str(TELEGRAM_SERVICE_USER_ID), created_by=1)
            is True
        )

        context = _context()
        human = _message(user_id=REAL_USER_ID, text=NORMAL_TEXT)
        bot = _message(user_id=SPAM_BOT_ID, is_bot=True, first_name="SpamBot", text=NORMAL_TEXT)
        assert await blacklist.check_blacklist(human, context) is True
        assert await blacklist.check_blacklist(bot, context) is True
        human.delete.assert_awaited()
        bot.delete.assert_awaited()
        assert context.bot.ban_chat_member.await_count == 2

    async def test_spam_report_bans_human_but_not_channel_forward(self, temp_db_path):
        _db, _client, blacklist, _clef = _handlers(temp_db_path)
        context = _context()

        human_target = _message(user_id=REAL_USER_ID, text="https://fiction.example/ad")
        human_report = MagicMock(spec=Update)
        human_report.message = _message(user_id=999001, text="/spam", chat_id=GROUP_ID)
        human_report.message.reply_to_message = human_target
        human_report.message.chat.id = GROUP_ID

        channel_target = _message(
            user_id=TELEGRAM_SERVICE_USER_ID,
            text="https://fiction.example/channel",
            first_name="Telegram",
            automatic=True,
            sender_chat_id=CHANNEL_A,
        )
        channel_report = MagicMock(spec=Update)
        channel_report.message = _message(user_id=999001, text="/spam", chat_id=GROUP_ID)
        channel_report.message.reply_to_message = channel_target
        channel_report.message.chat.id = GROUP_ID

        text_target = _message(
            user_id=TELEGRAM_SERVICE_USER_ID,
            text=AD_TEXT,
            first_name="Telegram",
            automatic=True,
            sender_chat_id=CHANNEL_B,
        )
        text_report = MagicMock(spec=Update)
        text_report.message = _message(user_id=999001, text="/spam", chat_id=GROUP_ID)
        text_report.message.reply_to_message = text_target
        text_report.message.chat.id = GROUP_ID

        with patch.object(blacklist, "_is_admin_or_creator", new=AsyncMock(return_value=True)):
            await blacklist.handle_spam_report(human_report, context)
            await blacklist.handle_spam_report(channel_report, context)
            await blacklist.handle_spam_report(text_report, context)

        banned_ids = [
            call.kwargs["user_id"] for call in context.bot.ban_chat_member.await_args_list
        ]
        assert banned_ids == [REAL_USER_ID]
        assert blacklist.db.check_blacklist(GROUP_ID, "link", "https://fiction.example/ad") is True
        assert (
            blacklist.db.check_blacklist(GROUP_ID, "link", "https://fiction.example/channel")
            is True
        )
        assert (
            blacklist.db.check_blacklist(GROUP_ID, "user", str(TELEGRAM_SERVICE_USER_ID)) is False
        )
        text_hash = blacklist._generate_message_hash(AD_TEXT)
        assert (
            blacklist.db.get_text_report_info(GROUP_ID, TELEGRAM_SERVICE_USER_ID, text_hash)[
                "report_count"
            ]
            == 0
        )
        channel_target.delete.assert_awaited()
        text_target.delete.assert_not_awaited()


@pytest.mark.asyncio
class TestHandleMessageOrder:
    @pytest.fixture
    def bot(self, temp_db_path):
        from bot import BanhammerBot

        with patch("bot.Config") as mock_config:
            mock_config.BOT_TOKEN = "test_token_123456"
            mock_config.BLACKLIST_CONFIG = {
                "auto_ban_on_blacklist": True,
                "ban_duration": 0,
                "log_actions": False,
            }
            mock_config.ADMIN_USER_IDS = [999001]
            bot = BanhammerBot()
            bot.db.db_path = temp_db_path
            bot.db.init_database()
            bot.clef_handler.client.account_id = "a"
            bot.clef_handler.client.api_token = "t"
            bot.clef_handler.client.enabled = True
            bot.clef_handler.client.score_profile = AsyncMock()
            return bot

    async def test_dirty_service_row_does_not_swallow_channel_post(self, bot):
        from services.clef_client import ClefScore

        _plant_user_blacklist(bot.db, TELEGRAM_SERVICE_USER_ID)
        bot.clef_handler.client.score_profile.return_value = ClefScore(0.91, 2.5)
        message = _message(
            user_id=TELEGRAM_SERVICE_USER_ID,
            text=NORMAL_TEXT,
            first_name="Telegram",
            automatic=True,
            sender_chat_id=CHANNEL_A,
        )
        update = MagicMock(spec=Update)
        update.message = message
        context = _context()

        with (
            patch.object(bot, "_is_admin_or_creator", new=AsyncMock(return_value=False)) as admin,
            patch("handlers.clef_handler.Config") as cfg,
        ):
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0, "log_actions": False}
            await bot._handle_message(update, context)

        admin.assert_not_awaited()
        bot.clef_handler.client.score_profile.assert_not_awaited()
        message.delete.assert_not_awaited()
        context.bot.ban_chat_member.assert_not_awaited()
        assert bot.db.check_blacklist(GROUP_ID, "user", str(TELEGRAM_SERVICE_USER_ID)) is True

    async def test_real_user_ad_still_runs_through_handle_message(self, bot):
        from services.clef_client import ClefScore

        bot.clef_handler.client.score_profile.return_value = ClefScore(0.91, 2.5)
        message = _message(user_id=REAL_USER_ID, text=AD_TEXT)
        update = MagicMock(spec=Update)
        update.message = message
        context = _context()

        with (
            patch.object(bot, "_is_admin_or_creator", new=AsyncMock(return_value=False)),
            patch("handlers.clef_handler.Config") as cfg,
        ):
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {
                "ban_duration": 0,
                "log_actions": False,
                "auto_ban_on_blacklist": True,
            }
            await bot._handle_message(update, context)

        bot.clef_handler.client.score_profile.assert_awaited()
        message.delete.assert_awaited()
        context.bot.ban_chat_member.assert_awaited()
        assert bot.db.check_blacklist(GROUP_ID, "user", str(REAL_USER_ID)) is True
