"""clef-flash 客户端与阈值辅助测试（无真实 API 调用）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.clef_client import ClefClient, ClefScore, parse_clef_response
from services.clef_prompt import IS_AD_INSTRUCTIONS, RISK_CRITERIA, build_questions
from handlers.clef_handler import (
    build_join_state,
    build_message_state,
    display_name,
    is_join_transition,
)


class TestParseClefResponse:
    def test_parse_success(self):
        payload = {
            "success": True,
            "result": {
                "model": "clef-flash",
                "answers": {
                    "is_ad": {"type": "noul", "noul": 0.9488},
                    "risk": {"type": "score", "score": 2.8475},
                },
            },
        }
        score = parse_clef_response(payload)
        assert score is not None
        assert score.is_ad == pytest.approx(0.9488)
        assert score.risk_score == pytest.approx(2.8475)

    def test_parse_success_false(self):
        assert parse_clef_response({"success": False, "result": {}}) is None

    def test_parse_missing_answers(self):
        assert parse_clef_response({"success": True, "result": {}}) is None

    def test_parse_invalid_noul(self):
        payload = {
            "success": True,
            "result": {
                "answers": {
                    "is_ad": {"type": "noul", "noul": "bad"},
                    "risk": {"type": "score", "score": 1.0},
                }
            },
        }
        assert parse_clef_response(payload) is None

    def test_parse_out_of_range_is_ad(self):
        payload = {
            "success": True,
            "result": {
                "answers": {
                    "is_ad": {"type": "noul", "noul": 1.5},
                    "risk": {"type": "score", "score": 1.0},
                }
            },
        }
        assert parse_clef_response(payload) is None

    def test_parse_keeps_is_ad_when_risk_missing(self):
        payload = {
            "success": True,
            "result": {"answers": {"is_ad": {"type": "noul", "noul": 0.93}}},
        }
        score = parse_clef_response(payload)
        assert score is not None
        assert score.is_ad == pytest.approx(0.93)
        assert score.should_auto_kick(0.85) is True

    def test_parse_bare_number_does_not_raise(self):
        payload = {
            "success": True,
            "result": {"answers": {"is_ad": 0.91, "risk": "nope"}},
        }
        score = parse_clef_response(payload)
        assert score is not None
        assert score.is_ad == pytest.approx(0.91)
        assert score.risk_score == 0.0


class TestClefScoreThreshold:
    def test_should_auto_kick_default(self):
        assert ClefScore(0.85, 2.0).should_auto_kick(0.85) is True
        assert ClefScore(0.849, 2.0).should_auto_kick(0.85) is False
        assert ClefScore(0.93, 2.5).should_auto_kick(0.85) is True

    def test_should_auto_kick_custom(self):
        assert ClefScore(0.5, 1.0).should_auto_kick(0.4) is True
        assert ClefScore(0.5, 1.0).should_auto_kick(0.9) is False


class TestPrompt:
    def test_build_questions_shape(self):
        q = build_questions()
        assert q["is_ad"]["type"] == "noul"
        assert "引流拉群" in q["is_ad"]["instructions"]
        assert q["risk"]["type"] == "score"
        assert q["risk"]["criteria"] == RISK_CRITERIA
        assert IS_AD_INSTRUCTIONS.startswith("判断该 Telegram")

    def test_join_and_message_state(self):
        assert "昵称：张三" in build_join_state("张三", "hello")
        assert "消息：hi" in build_message_state("张三", "", "hi")


class TestJoinTransition:
    def test_left_to_member(self):
        assert is_join_transition("left", "member") is True

    def test_kicked_to_member(self):
        assert is_join_transition("kicked", "member") is True

    def test_member_to_member(self):
        assert is_join_transition("member", "member") is False

    def test_left_to_administrator(self):
        assert is_join_transition("left", "administrator") is False


class TestDisplayName:
    def test_first_last(self):
        user = MagicMock()
        user.first_name = "Herbert"
        user.last_name = "Gao"
        user.username = "x"
        assert display_name(user) == "Herbert Gao"

    def test_fallback_username(self):
        user = MagicMock()
        user.first_name = None
        user.last_name = None
        user.username = "only_name"
        user.id = 1
        assert display_name(user) == "only_name"


@pytest.mark.asyncio
class TestClefClientScoreProfile:
    async def test_disabled_returns_none(self):
        client = ClefClient(
            account_id="abc",
            api_token="token",
            enabled=False,
        )
        assert await client.score_profile("state") is None

    async def test_missing_creds_returns_none(self):
        client = ClefClient(account_id=None, api_token="t", enabled=True)
        assert await client.score_profile("state") is None

    async def test_success_http_mock(self):
        payload = {
            "success": True,
            "result": {
                "answers": {
                    "is_ad": {"type": "noul", "noul": 0.91},
                    "risk": {"type": "score", "score": 2.5},
                }
            },
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = payload
        mock_response.content = b"{}"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        client = ClefClient(
            account_id="acct",
            api_token="secret-token-should-not-log",
            enabled=True,
            timeout=5.0,
        )
        with patch("services.clef_client.httpx.AsyncClient", return_value=mock_client):
            score = await client.score_profile("Telegram 入群资料：\\n昵称：x\\n简介：y")

        assert score is not None
        assert score.is_ad == pytest.approx(0.91)
        assert score.risk_score == pytest.approx(2.5)
        # 确认调用了 post，且 Authorization 存在但不在我们断言日志里
        assert mock_client.post.await_count == 1
        call_kwargs = mock_client.post.await_args
        assert "Authorization" in call_kwargs.kwargs["headers"]

    async def test_http_error_fail_open(self):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("boom"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        client = ClefClient(account_id="a", api_token="t", enabled=True)
        with patch("services.clef_client.httpx.AsyncClient", return_value=mock_client):
            assert await client.score_profile("state") is None

    async def test_timeout_fail_open(self):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("t"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        client = ClefClient(account_id="a", api_token="t", enabled=True)
        with patch("services.clef_client.httpx.AsyncClient", return_value=mock_client):
            assert await client.score_profile("state") is None

    async def test_non_200_fail_open(self):
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.content = b"denied"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        client = ClefClient(account_id="a", api_token="t", enabled=True)
        with patch("services.clef_client.httpx.AsyncClient", return_value=mock_client):
            assert await client.score_profile("state") is None


class TestClefDbHelpers:
    def test_mark_and_query(self, temp_db_path):
        from database.models import DatabaseManager

        db = DatabaseManager(db_path=temp_db_path)
        chat_id, user_id = -1001, 42
        assert db.has_clef_join_scored(chat_id, user_id) is False
        assert db.has_clef_message_scored(chat_id, user_id) is False

        assert db.mark_clef_join_scored(chat_id, user_id) is True
        assert db.has_clef_join_scored(chat_id, user_id) is True
        assert db.has_clef_message_scored(chat_id, user_id) is False

        assert db.mark_clef_message_scored(chat_id, user_id) is True
        assert db.has_clef_message_scored(chat_id, user_id) is True

        # 再次标记不报错
        assert db.mark_clef_join_scored(chat_id, user_id) is True


def _first_message_mocks():
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = 555
    message.from_user.is_bot = False
    message.from_user.first_name = "Ad"
    message.from_user.last_name = "Bot"
    message.from_user.username = "adbot"
    message.from_user.mention_html = MagicMock(return_value="ad")
    message.chat = MagicMock()
    message.chat.id = -100555
    message.chat.title = "G"
    message.text = "加群看项目 日赚10000"
    message.caption = None
    message.message_id = 9
    message.delete = AsyncMock()

    context = MagicMock()
    context.bot.id = 1
    context.bot.get_chat = AsyncMock(side_effect=Exception("no bio"))
    context.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="member"))
    context.bot.ban_chat_member = AsyncMock()
    context.bot.send_message = AsyncMock()
    return message, context


@pytest.mark.asyncio
class TestClefBanAddsBlacklist:
    """clef 命中阈值时写入本群 user 黑名单，不写入通用黑名单。"""

    async def test_ban_user_adds_group_blacklist(self, temp_db_path):
        from database.models import DatabaseManager
        from handlers.clef_handler import ClefHandler
        from services.clef_client import ClefScore

        db = DatabaseManager(db_path=temp_db_path)
        handler = ClefHandler(db=db)

        chat = MagicMock()
        chat.id = -100999
        chat.title = "Test Group"

        user = MagicMock()
        user.id = 424242
        user.username = "spammer"
        user.mention_html = MagicMock(return_value='<a href="tg://user?id=424242">spammer</a>')

        context = MagicMock()
        context.bot.id = 1
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()

        score = ClefScore(is_ad=0.93, risk_score=2.7)
        await handler._ban_user(
            context=context,
            chat=chat,
            user=user,
            score=score,
            content="nick=x",
            reason="clef-flash 入群检测命中 (is_ad=0.930, risk=2.70)",
            action_type="clef_join_ban",
        )

        assert db.check_blacklist(chat.id, "user", "424242") is True
        assert db.check_global_blacklist("user", "424242") is False  # 未开贡献
        context.bot.ban_chat_member.assert_awaited()

    async def test_ban_user_does_not_publish_user_id_globally(self, temp_db_path):
        from database.models import DatabaseManager
        from handlers.clef_handler import ClefHandler
        from services.clef_client import ClefScore

        db = DatabaseManager(db_path=temp_db_path)
        chat_id = -100888
        db.update_group_settings(chat_id, contribute_to_global=True)

        handler = ClefHandler(db=db)

        chat = MagicMock()
        chat.id = chat_id
        chat.title = "Contributing"

        user = MagicMock()
        user.id = 777
        user.username = "ad"
        user.mention_html = MagicMock(return_value="ad")

        context = MagicMock()
        context.bot.id = 1
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()

        score = ClefScore(is_ad=0.96, risk_score=2.9)
        banned = await handler._ban_user(
            context=context,
            chat=chat,
            user=user,
            score=score,
            content="msg",
            reason="clef-flash 首条消息检测命中 (is_ad=0.960, risk=2.90)",
            action_type="clef_message_ban",
        )

        assert banned is True
        assert db.check_blacklist(chat_id, "user", "777") is True
        assert db.check_global_blacklist("user", "777") is False

    async def test_check_first_message_triggers_blacklist(self, temp_db_path):
        """首条消息超阈值整条路径应加黑名单。"""
        from database.models import DatabaseManager
        from handlers.clef_handler import ClefHandler
        from services.clef_client import ClefClient, ClefScore

        db = DatabaseManager(db_path=temp_db_path)
        client = ClefClient(account_id="a", api_token="t", enabled=True)
        client.score_profile = AsyncMock(return_value=ClefScore(0.92, 2.6))

        handler = ClefHandler(db=db, client=client)

        message = MagicMock()
        message.from_user = MagicMock()
        message.from_user.id = 555
        message.from_user.is_bot = False
        message.from_user.first_name = "Ad"
        message.from_user.last_name = "Bot"
        message.from_user.username = "adbot"
        message.from_user.mention_html = MagicMock(return_value="ad")
        message.chat = MagicMock()
        message.chat.id = -100555
        message.chat.title = "G"
        message.text = "加群看项目 日赚10000"
        message.caption = None
        message.message_id = 9
        message.delete = AsyncMock()

        context = MagicMock()
        context.bot.id = 1
        context.bot.get_chat = AsyncMock(side_effect=Exception("no bio"))
        context.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="member"))
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()

        with (
            patch("handlers.clef_handler.Config") as cfg,
            patch("services.clef_client.Config.CLEF_AUTO_KICK_THRESHOLD", 0.85),
        ):
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {
                "ban_duration": 0,
                "log_actions": False,
                "auto_ban_on_blacklist": True,
            }
            hit = await handler.check_first_message(message, context)

        assert hit is True
        assert db.check_blacklist(-100555, "user", "555") is True
        assert db.has_clef_message_scored(-100555, 555) is True
        assert db.has_clef_join_scored(-100555, 555) is True
        message.delete.assert_awaited()
        context.bot.ban_chat_member.assert_awaited()

    async def test_api_failure_does_not_mark_or_ban(self, temp_db_path):
        from database.models import DatabaseManager
        from handlers.clef_handler import ClefHandler
        from services.clef_client import ClefClient

        db = DatabaseManager(db_path=temp_db_path)
        client = ClefClient(account_id="a", api_token="t", enabled=True)
        client.score_profile = AsyncMock(return_value=None)
        handler = ClefHandler(db=db, client=client)
        message, context = _first_message_mocks()

        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            hit = await handler.check_first_message(message, context)

        assert hit is False
        assert db.has_clef_message_scored(message.chat.id, message.from_user.id) is False
        context.bot.ban_chat_member.assert_not_awaited()

    async def test_ban_failure_does_not_mark_scored(self, temp_db_path):
        from database.models import DatabaseManager
        from handlers.clef_handler import ClefHandler
        from services.clef_client import ClefClient, ClefScore

        db = DatabaseManager(db_path=temp_db_path)
        client = ClefClient(account_id="a", api_token="t", enabled=True)
        client.score_profile = AsyncMock(return_value=ClefScore(1.0, 3.0))
        handler = ClefHandler(db=db, client=client)
        message, context = _first_message_mocks()
        context.bot.ban_chat_member = AsyncMock(side_effect=Exception("Ban failed"))

        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0, "log_actions": False}
            hit = await handler.check_first_message(message, context)

        assert hit is False
        assert db.has_clef_message_scored(message.chat.id, message.from_user.id) is False
        assert db.check_blacklist(message.chat.id, "user", "555") is True

    async def test_below_threshold_marks_message_only(self, temp_db_path):
        from database.models import DatabaseManager
        from handlers.clef_handler import ClefHandler
        from services.clef_client import ClefClient, ClefScore

        db = DatabaseManager(db_path=temp_db_path)
        client = ClefClient(account_id="a", api_token="t", enabled=True)
        client.score_profile = AsyncMock(return_value=ClefScore(0.84, 1.0))
        handler = ClefHandler(db=db, client=client)
        message, context = _first_message_mocks()

        with (
            patch("handlers.clef_handler.Config") as cfg,
            patch("services.clef_client.Config.CLEF_AUTO_KICK_THRESHOLD", 0.85),
        ):
            cfg.CLEF_ENABLED = True
            hit = await handler.check_first_message(message, context)

        assert hit is False
        assert db.has_clef_message_scored(-100555, 555) is True
        assert db.has_clef_join_scored(-100555, 555) is False
        context.bot.ban_chat_member.assert_not_awaited()


def _join_update(chat_type="supergroup", new_status="member"):
    from telegram import ChatMemberUpdated

    user = MagicMock()
    user.id = 555
    user.is_bot = False
    user.first_name = "Ad"
    user.last_name = None
    user.username = "ad"
    chat = MagicMock()
    chat.id = -100555
    chat.type = chat_type
    chat.title = "G"
    result = MagicMock(spec=ChatMemberUpdated)
    result.old_chat_member.status = "left"
    result.new_chat_member.status = new_status
    result.new_chat_member.user = user
    result.chat = chat
    update = MagicMock()
    update.chat_member = result
    update.effective_message = None
    return update, chat


@pytest.mark.asyncio
class TestClefJoin:
    async def test_channel_join_is_not_scored(self, temp_db_path):
        from database.models import DatabaseManager
        from handlers.clef_handler import ClefHandler
        from services.clef_client import ClefClient

        client = ClefClient(account_id="a", api_token="t", enabled=True)
        client.score_profile = AsyncMock()
        handler = ClefHandler(db=DatabaseManager(db_path=temp_db_path), client=client)
        update, _chat = _join_update(chat_type="channel")
        context = MagicMock()

        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            await handler.handle_chat_member(update, context)

        client.score_profile.assert_not_awaited()

    async def test_listed_user_rejoin_bans_without_clef(self, temp_db_path):
        from database.models import DatabaseManager
        from handlers.clef_handler import ClefHandler
        from services.clef_client import ClefClient

        db = DatabaseManager(db_path=temp_db_path)
        db.add_to_blacklist(-100555, "user", "555", created_by=1)
        client = ClefClient(account_id="a", api_token="t", enabled=True)
        client.score_profile = AsyncMock()
        handler = ClefHandler(db=db, client=client)
        update, _chat = _join_update()
        context = MagicMock()
        context.bot.ban_chat_member = AsyncMock()
        context.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="member"))

        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0}
            await handler.handle_chat_member(update, context)

        client.score_profile.assert_not_awaited()
        context.bot.ban_chat_member.assert_awaited()

    async def test_scored_and_listed_rejoin_still_bans(self, temp_db_path):
        from database.models import DatabaseManager
        from handlers.clef_handler import ClefHandler
        from services.clef_client import ClefClient

        db = DatabaseManager(db_path=temp_db_path)
        db.add_to_blacklist(-100555, "user", "555", created_by=1)
        db.mark_clef_join_scored(-100555, 555)
        client = ClefClient(account_id="a", api_token="t", enabled=True)
        client.score_profile = AsyncMock()
        handler = ClefHandler(db=db, client=client)
        update, _chat = _join_update()
        context = MagicMock()
        context.bot.ban_chat_member = AsyncMock()
        context.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="member"))

        with patch("handlers.clef_handler.Config") as cfg:
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0}
            await handler.handle_chat_member(update, context)

        client.score_profile.assert_not_awaited()
        context.bot.ban_chat_member.assert_awaited()

    async def test_join_ban_marks_both_paths(self, temp_db_path):
        from database.models import DatabaseManager
        from handlers.clef_handler import ClefHandler
        from services.clef_client import ClefClient, ClefScore

        db = DatabaseManager(db_path=temp_db_path)
        client = ClefClient(account_id="a", api_token="t", enabled=True)
        client.score_profile = AsyncMock(return_value=ClefScore(0.9, 2.0))
        handler = ClefHandler(db=db, client=client)
        update, chat = _join_update()
        context = MagicMock()
        context.bot.id = 1
        context.bot.get_chat = AsyncMock(side_effect=Exception("no bio"))
        context.bot.get_chat_member = AsyncMock(return_value=MagicMock(status="member"))
        context.bot.ban_chat_member = AsyncMock()
        context.bot.send_message = AsyncMock()

        with (
            patch("handlers.clef_handler.Config") as cfg,
            patch("services.clef_client.Config.CLEF_AUTO_KICK_THRESHOLD", 0.85),
        ):
            cfg.CLEF_ENABLED = True
            cfg.BLACKLIST_CONFIG = {"ban_duration": 0, "log_actions": False}
            await handler.handle_chat_member(update, context)

        assert db.has_clef_join_scored(chat.id, 555) is True
        assert db.has_clef_message_scored(chat.id, 555) is True
        context.bot.ban_chat_member.assert_awaited()
