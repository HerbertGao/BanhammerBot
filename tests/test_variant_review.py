"""慢变体复评。时间、文本和用户都是合成的，不调用真实模型。"""

from __future__ import annotations

import asyncio
import sqlite3
from unittest.mock import MagicMock

import pytest

from config import Config, parse_variant_mode
from database import variant_store
from database.models import DatabaseManager
from services.clef_client import ClefClient, ClefScore
from services.variant_review import VariantReview
from utils.logger import logger
from utils.telegram_identity import (
    CHANNEL_BOT_USER_ID,
    GROUP_ANONYMOUS_BOT_ID,
    TELEGRAM_SERVICE_USER_ID,
)

CHAT = -100424242001
OTHER_CHAT = -100424242002
USER = 555001
OTHER_USER = 555002
PLAIN = "日入5000+"
VARIANTS = [
    "日入5000+",
    "日入5000+🔥💰",
    "日.入.5.0.0.0+",
    "日入5a000+",
    "日入5 0 0 0+",
    "日🔥入5000+",
]


class Clock:
    def __init__(self, now: float = 1_700_000_000.0):
        self.now = now

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeClef:
    def __init__(self, detail: ClefScore | None = ClefScore(0.42, 1.1), error: str | None = None):
        self.detail = detail
        self.error = error
        self.profile_calls = 0
        self.detail_calls: list[str] = []
        self.profile_score = ClefScore(0.20, 0.2)
        self._during = None

    async def score_profile(self, state, questions=None):
        self.profile_calls += 1
        return self.profile_score

    async def score_profile_detailed(self, state, questions=None):
        self.detail_calls.append(state)
        if self._during is not None:
            await self._during(state)
        return self.detail, self.error


def review_config(**overrides):
    config = dict(Config.VARIANT_REVIEW_CONFIG)
    config["mode"] = "enforce"
    config.update(overrides)
    return config


def make_review(db, client, clock, **overrides):
    review = VariantReview(
        db=db, client=client, config=review_config(**overrides), clock=clock.time
    )
    return review


async def feed(review, clock, text, message_id, *, chat_id=CHAT, user_id=USER, nickname="合成昵称"):
    return await review.consider(
        chat_id=chat_id,
        user_id=user_id,
        message_id=message_id,
        nickname=nickname,
        text=text,
    )


def sample_rows(db, chat_id=CHAT, user_id=USER):
    with sqlite3.connect(db.db_path) as connection:
        return connection.execute(
            """
            SELECT message_id, skeleton, excerpt FROM clef_variant_samples
            WHERE chat_id = ? AND user_id = ?
            ORDER BY created_at
            """,
            (chat_id, user_id),
        ).fetchall()


def test_mode_parser_rejects_unknown_values():
    assert parse_variant_mode(None) == "off"
    assert parse_variant_mode(" SHADOW ") == "shadow"
    assert parse_variant_mode("nope") == "off"
    assert Config.VARIANT_REVIEW_CONFIG["min_similar"] == 4
    assert Config.VARIANT_REVIEW_CONFIG["min_span_seconds"] == 1200
    assert Config.VARIANT_REVIEW_CONFIG["cooldown_seconds"] == 3600
    assert Config.VARIANT_REVIEW_CONFIG["max_reviews"] == 4
    assert Config.VARIANT_REVIEW_CONFIG["backoff_seconds"] == 21600
    assert Config.VARIANT_REVIEW_CONFIG["global_hourly_budget"] == 60
    assert Config.VARIANT_REVIEW_CONFIG["mode"] == "off"


def test_client_classifies_429_and_bad_json_without_a_network_call():
    client = ClefClient(account_id="a", api_token="t", enabled=True)
    limited = MagicMock(status_code=429, content=b"")
    assert client._interpret(limited) == (None, "http_429")
    broken = MagicMock(status_code=200, content=b"not-json")
    broken.json.side_effect = ValueError("bad")
    assert client._interpret(broken)[1] == "bad_json"


@pytest.mark.asyncio
class TestVariantSchedule:
    async def test_fast_repeats_do_not_call_the_model(self, temp_db_path):
        db = DatabaseManager(db_path=temp_db_path)
        clock = Clock()
        client = FakeClef()
        review = make_review(db, client, clock)
        for index in range(4):
            decision = await feed(review, clock, VARIANTS[index], 10 + index)
            clock.advance(30)
        assert client.detail_calls == []
        assert decision.reason == "insufficient_evidence"
        assert decision.action == "none"

    async def test_slow_variants_over_hours_retry_after_backoff(self, temp_db_path):
        db = DatabaseManager(db_path=temp_db_path)
        clock = Clock()
        client = FakeClef(ClefScore(0.66, 1.4))
        review = make_review(db, client, clock)
        reasons = []
        for index in range(49):
            decision = await feed(review, clock, VARIANTS[index % len(VARIANTS)], 100 + index)
            reasons.append(decision.reason)
            clock.advance(450)
        assert len(client.detail_calls) == 4
        assert reasons.count("below_threshold") == 4
        assert "backoff" in reasons
        assert all(reason != "ban" for reason in reasons)
        clock.now = 1_700_000_000.0 + 33750
        again = await feed(review, clock, PLAIN, 900)
        assert again.reason == "below_threshold"
        assert len(client.detail_calls) == 5
        assert db.check_blacklist(CHAT, "user", str(USER)) is False

    async def test_legacy_scored_user_is_not_wiped_and_can_enter(self, temp_db_path):
        db = DatabaseManager(db_path=temp_db_path)
        db.mark_clef_message_scored(CHAT, USER)
        db.init_database()
        assert db.has_clef_message_scored(CHAT, USER) is True
        clock = Clock()
        client = FakeClef(ClefScore(0.91, 1.0))
        review = make_review(db, client, clock)
        first = None
        for index in range(4):
            first = await feed(review, clock, VARIANTS[index], 20 + index)
            clock.advance(450)
        assert first is not None
        assert first.action == "ban"
        assert len(client.detail_calls) == 1
        assert "不可信" in client.detail_calls[0]
        assert "<<<CURRENT>>>" in client.detail_calls[0]
        assert db.has_clef_message_scored(CHAT, USER) is True

    async def test_normal_text_is_not_convicted_by_older_samples(self, temp_db_path):
        db = DatabaseManager(db_path=temp_db_path)
        clock = Clock()
        client = FakeClef(ClefScore(0.95, 2.0))
        review = make_review(db, client, clock)
        for index in range(4):
            await feed(review, clock, VARIANTS[index], 30 + index)
            clock.advance(450)
        assert len(client.detail_calls) == 1
        normal = await feed(review, clock, "大家讨论一下每月收入", 80)
        quote = await feed(review, clock, "这单报价100元含税", 81)
        assert normal.reason == "insufficient_evidence"
        assert quote.reason == "insufficient_evidence"
        assert len(client.detail_calls) == 1

    async def test_same_quote_can_be_rereviewed_but_low_score_does_not_act(self, temp_db_path):
        db = DatabaseManager(db_path=temp_db_path)
        clock = Clock()
        client = FakeClef(ClefScore(0.21, 0.4))
        review = make_review(db, client, clock)
        decision = None
        for index in range(4):
            decision = await feed(review, clock, "这单报价100元含税", 40 + index)
            clock.advance(450)
        assert decision is not None
        assert decision.reason == "below_threshold"
        assert decision.action == "none"
        other = await feed(review, clock, "这单报价200元含税", 90)
        assert other.reason == "insufficient_evidence"
        assert len(client.detail_calls) == 1

    async def test_failure_does_not_mark_passed_and_retries_after_cooldown(self, temp_db_path):
        db = DatabaseManager(db_path=temp_db_path)
        db.mark_clef_message_scored(CHAT, USER)
        clock = Clock()
        client = FakeClef(None, "timeout")
        review = make_review(db, client, clock)
        for index in range(3):
            await feed(review, clock, VARIANTS[index], 50 + index)
            clock.advance(450)
        failed = await feed(review, clock, VARIANTS[3], 53)
        assert failed.reason == "fail_open"
        assert failed.error == "timeout"
        assert failed.action == "none"
        clock.advance(60)
        blocked = await feed(review, clock, VARIANTS[4], 54)
        assert blocked.reason == "failure_backoff"
        assert len(client.detail_calls) == 1
        clock.advance(900)
        client.error = None
        client.detail = ClefScore(0.4, 0.2)
        retried = await feed(review, clock, VARIANTS[0], 55)
        assert retried.reason == "below_threshold"
        assert len(client.detail_calls) == 2
        assert db.has_clef_message_scored(CHAT, USER) is True
        state = variant_store.get_state(db.db_path, CHAT, USER)
        assert state.review_count == 1

    async def test_restart_keeps_the_window(self, temp_db_path):
        db = DatabaseManager(db_path=temp_db_path)
        clock = Clock()
        client = FakeClef()
        review = make_review(db, client, clock)
        for index in range(3):
            await feed(review, clock, VARIANTS[index], 60 + index)
            clock.advance(450)
        restored = DatabaseManager(db_path=temp_db_path)
        restored_review = make_review(restored, client, clock)
        decision = await feed(restored_review, clock, VARIANTS[3], 63)
        assert decision.reason == "below_threshold"
        assert len(client.detail_calls) == 1

    async def test_cleanup_expires_samples_without_deleting_scores(self, temp_db_path):
        db = DatabaseManager(db_path=temp_db_path)
        db.mark_clef_message_scored(CHAT, USER)
        clock = Clock()
        client = FakeClef()
        review = make_review(db, client, clock)
        await feed(review, clock, PLAIN, 70)
        clock.advance(200_000)
        result = db.cleanup_variant_tracking(now=clock.now)
        assert result["samples"] == 1
        assert sample_rows(db) == []
        assert db.has_clef_message_scored(CHAT, USER) is True

    async def test_groups_and_service_identities_stay_isolated(self, temp_db_path):
        db = DatabaseManager(db_path=temp_db_path)
        clock = Clock()
        client = FakeClef(ClefScore(0.93, 1.0))
        review = make_review(db, client, clock)
        for index in range(4):
            await feed(review, clock, VARIANTS[index], 80 + index)
            clock.advance(450)
        assert len(client.detail_calls) == 1
        other = await feed(review, clock, PLAIN, 1, chat_id=OTHER_CHAT)
        assert other.reason == "insufficient_evidence"
        assert sample_rows(db, OTHER_CHAT, USER) != []
        for service_id in (
            TELEGRAM_SERVICE_USER_ID,
            GROUP_ANONYMOUS_BOT_ID,
            CHANNEL_BOT_USER_ID,
        ):
            decision = await feed(review, clock, PLAIN, 2, user_id=service_id)
            assert decision.reason == "service_identity"
            assert sample_rows(db, CHAT, service_id) == []

    async def test_duplicate_message_does_not_double_count(self, temp_db_path):
        db = DatabaseManager(db_path=temp_db_path)
        clock = Clock()
        review = make_review(db, FakeClef(), clock)
        await feed(review, clock, PLAIN, 7)
        await feed(review, clock, PLAIN + "🔥", 7)
        assert len(sample_rows(db)) == 1
        excerpt = sample_rows(db)[0][2]
        assert len(excerpt) <= 80

    async def test_global_budget_and_backpressure_fail_open(self, temp_db_path):
        db = DatabaseManager(db_path=temp_db_path)
        clock = Clock()
        client = FakeClef(ClefScore(0.3, 0.2))
        review = make_review(db, client, clock, global_hourly_budget=1, cooldown_seconds=0)
        for index, user_id in enumerate((USER, OTHER_USER)):
            for step in range(3):
                await feed(review, clock, VARIANTS[step], 200 + index * 10 + step, user_id=user_id)
                clock.advance(450)
        first = await feed(review, clock, VARIANTS[3], 230, user_id=USER)
        second = await feed(review, clock, VARIANTS[3], 231, user_id=OTHER_USER)
        assert first.reason == "below_threshold"
        assert second.reason == "global_budget"
        assert len(client.detail_calls) == 1
        state = variant_store.get_state(db.db_path, CHAT, OTHER_USER)
        assert state.review_count == 0

    async def test_backpressure_does_not_mark_passed(self, temp_db_path):
        db = DatabaseManager(db_path=temp_db_path)
        clock = Clock()
        client = FakeClef(ClefScore(0.3, 0.2))
        review = make_review(db, client, clock, max_inflight=1)
        for step in range(3):
            await feed(review, clock, VARIANTS[step], 300 + step, user_id=USER)
            await feed(review, clock, VARIANTS[step], 400 + step, user_id=OTHER_USER)
            clock.advance(450)
        blocked = asyncio.Event()
        started = asyncio.Event()

        async def hold(_state):
            started.set()
            await blocked.wait()

        client._during = hold
        left = asyncio.create_task(feed(review, clock, VARIANTS[4], 310, user_id=USER))
        await started.wait()
        right = await feed(review, clock, VARIANTS[4], 410, user_id=OTHER_USER)
        blocked.set()
        await left
        assert right.reason == "backpressure"
        assert right.action == "none"
        assert variant_store.get_state(db.db_path, CHAT, OTHER_USER).review_count == 0

    async def test_concurrent_same_user_calls_the_model_once(self, temp_db_path):
        db = DatabaseManager(db_path=temp_db_path)
        clock = Clock()
        client = FakeClef(ClefScore(0.33, 0.2))
        review = make_review(db, client, clock)
        for index in range(3):
            await feed(review, clock, VARIANTS[index], 500 + index)
            clock.advance(450)
        started = asyncio.Event()
        release = asyncio.Event()

        async def wait(_state):
            started.set()
            await release.wait()

        client._during = wait
        first = asyncio.create_task(feed(review, clock, VARIANTS[3], 503))
        await started.wait()
        second = asyncio.create_task(feed(review, clock, VARIANTS[4], 504))
        await asyncio.sleep(0.05)
        release.set()
        done = await asyncio.gather(first, second)
        assert len(client.detail_calls) == 1
        assert {item.reason for item in done} == {"below_threshold", "cooldown"}

    async def test_stale_response_does_not_act_on_the_message(self, temp_db_path):
        db = DatabaseManager(db_path=temp_db_path)
        clock = Clock()
        client = FakeClef(ClefScore(0.99, 2.0))
        review = make_review(db, client, clock)

        async def steal(_state):
            variant_store.force_inflight(db.db_path, CHAT, USER, "replaced", clock.now + 30)

        client._during = steal
        for index in range(3):
            await feed(review, clock, VARIANTS[index], 600 + index)
            clock.advance(450)
        decision = await feed(review, clock, VARIANTS[3], 603)
        assert decision.reason == "stale_response"
        assert decision.action == "none"
        assert variant_store.get_state(db.db_path, CHAT, USER).review_count == 0

    async def test_logs_omit_message_text(self, temp_db_path):
        db = DatabaseManager(db_path=temp_db_path)
        clock = Clock()
        client = FakeClef(ClefScore(0.15, 0.1))
        review = make_review(db, client, clock)
        captured = []
        handle = logger.add(lambda message: captured.append(str(message)), format="{message}")
        try:
            for index in range(4):
                await feed(review, clock, VARIANTS[index], 700 + index)
                clock.advance(450)
        finally:
            logger.remove(handle)
        assert client.detail_calls
        assert "当前消息" in client.detail_calls[0]
        logged = "\n".join(captured)
        assert "日入5000" not in logged
        assert "is_ad=" in logged
