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
