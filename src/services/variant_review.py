"""同一普通用户、同一群的慢变体复评。

历史 message_scored_at 只表示首条单句已经评过，不是永久豁免。
近似条数、时间跨度和冷却只决定要不要再调用模型。
模型只给当前消息一个 is_ad；不到现有阈值就不删除、不封禁。
历史骨架是不可信对照，不参与打分合并，也不能单独处罚当前消息。

默认参数是假设，不是用真实流量校准的结果。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Optional

from config import Config
from database import variant_store
from database.models import DatabaseManager
from database.variant_store import VariantSample, VariantState
from services.clef_client import ClefScore
from services.clef_prompt import build_context_questions, build_context_review_state
from services.variant_text import make_excerpt, same_variant, skeleton_of
from utils.logger import logger
from utils.telegram_identity import is_service_user_id


@dataclass
class VariantDecision:
    """一次复评结论。action=ban 只表示调用方可以处罚当前消息。"""

    reason: str
    action: str = "none"
    is_ad: Optional[float] = None
    risk: Optional[float] = None
    similar_count: int = 0
    span_seconds: int = 0
    review_count: int = 0
    budget_remaining: Optional[int] = None
    elapsed_ms: int = 0
    error: Optional[str] = None


def decide_current_message(score: Optional[ClefScore], mode: str, threshold: float) -> str:
    """把「当前消息」的一次 is_ad 映射成动作。

    不接收历史分数，不做平均或取最大值。risk 不参与。
    低于既有阈值时不删除、不封禁。shadow 只标记 would_ban。
    """
    if score is None:
        return "fail_open"
    if score.is_ad < threshold:
        return "below_threshold"
    if mode == "shadow":
        return "would_ban"
    if mode == "enforce":
        return "ban"
    return "ignored"


class VariantReview:
    """按用户×群累计近似文本，并在有跨度时复评当前消息。"""

    def __init__(
        self,
        db: DatabaseManager,
        client,
        config: Optional[dict] = None,
        clock: Optional[Callable[[], float]] = None,
    ):
        source = config if config is not None else Config.VARIANT_REVIEW_CONFIG
        self.config = dict(source)
        self.config["chat_ids"] = set(source.get("chat_ids") or ())
        self.db = db
        self.client = client
        self._clock = clock or time.time
        slots = max(1, self._int("max_inflight", 2))
        self._slots = asyncio.Semaphore(slots)
        self._guard = asyncio.Lock()
        self._locks: dict[tuple[int, int], asyncio.Lock] = {}

    def mode_for(self, chat_id: int) -> str:
        """off / shadow / enforce。名单非空时，名单外的群保持关闭。"""
        mode = self.config.get("mode", "off")
        if mode not in {"shadow", "enforce"}:
            return "off"
        chats = self.config.get("chat_ids") or set()
        if chats and int(chat_id) not in chats:
            return "off"
        return str(mode)

    def threshold(self) -> float:
        """沿用首条踢人阈值。读不到合法值时用 0.80。"""
        value = getattr(Config, "CLEF_AUTO_KICK_THRESHOLD", 0.80)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0.80
        number = float(value)
        if not 0.0 < number <= 1.0:
            return 0.80
        return number

    async def observe(self, *, chat_id: int, user_id: int, message_id: int, text: str) -> None:
        """首条未命中后记下骨架。模式关闭或信息量不足时不写库。"""
        if self.mode_for(chat_id) == "off" or is_service_user_id(user_id):
            return
        lock = await self._lock_for(chat_id, user_id)
        async with lock:
            self._record(chat_id, user_id, message_id, text, self._clock())

    async def consider(
        self,
        *,
        chat_id: int,
        user_id: int,
        message_id: int,
        nickname: str,
        text: str,
        bio_provider: Optional[Callable[[], Awaitable[str]]] = None,
    ) -> VariantDecision:
        """记录当前消息，证据够了才复评。返回值本身不封禁。"""
        lock = await self._lock_for(chat_id, user_id)
        async with lock:
            return await self._consider_locked(
                chat_id=chat_id,
                user_id=user_id,
                message_id=message_id,
                nickname=nickname,
                text=text,
                bio_provider=bio_provider,
            )

    async def _consider_locked(
        self,
        *,
        chat_id: int,
        user_id: int,
        message_id: int,
        nickname: str,
        text: str,
        bio_provider: Optional[Callable[[], Awaitable[str]]],
    ) -> VariantDecision:
        mode = self.mode_for(chat_id)
        if mode == "off":
            return VariantDecision(reason="mode_off")
        if is_service_user_id(user_id):
            return VariantDecision(reason="service_identity")
        now = self._clock()
        skeleton = self._record(chat_id, user_id, message_id, text, now)
        if skeleton is None:
            return VariantDecision(reason="low_information")
        matched = self._matched(chat_id, user_id, skeleton, now)
        decision = self._evidence_decision(matched)
        if decision.reason != "ready":
            self._log(decision, chat_id, user_id, mode)
            return decision
        state = variant_store.get_state(self.db.db_path, chat_id, user_id)
        blocked = self._blocked(state, now)
        if blocked is not None:
            decision.reason = blocked
            decision.review_count = state.review_count
            decision.budget_remaining = self._remaining(state.review_count)
            self._log(decision, chat_id, user_id, mode)
            return decision
        return await self._score_current(
            chat_id=chat_id,
            user_id=user_id,
            message_id=message_id,
            nickname=nickname,
            text=text,
            matched=matched,
            decision=decision,
            mode=mode,
            now=now,
            bio_provider=bio_provider,
        )

    def _record(
        self, chat_id: int, user_id: int, message_id: int, text: str, now: float
    ) -> Optional[str]:
        skeleton = skeleton_of(text, max_chars=self._int("skeleton_chars", 96))
        if not isinstance(skeleton, str):
            return None
        excerpt = make_excerpt(text, skeleton, limit=self._int("excerpt_chars", 80))
        variant_store.add_sample(
            self.db.db_path,
            chat_id,
            user_id,
            message_id,
            skeleton,
            excerpt,
            now,
            ttl_seconds=self._int("sample_ttl_seconds", 129600),
            max_samples=self._int("max_samples", 8),
        )
        return skeleton

    def _matched(
        self, chat_id: int, user_id: int, skeleton: str, now: float
    ) -> list[VariantSample]:
        samples = variant_store.list_samples(
            self.db.db_path,
            chat_id,
            user_id,
            now=now,
            ttl_seconds=self._int("sample_ttl_seconds", 129600),
        )
        return [sample for sample in samples if self._similar(skeleton, sample.skeleton)]

    def _similar(self, left: str, right: str) -> bool:
        return bool(
            same_variant(
                left,
                right,
                ratio=self._float("similarity_ratio", 0.90),
                plain_ratio=self._float("plain_ratio", 0.96),
                min_length_ratio=self._float("min_length_ratio", 0.75),
                max_chars=self._int("skeleton_chars", 96),
            )
        )

    def _evidence_decision(self, matched: list[VariantSample]) -> VariantDecision:
        span = 0
        if len(matched) >= 2:
            span = int(matched[-1].created_at - matched[0].created_at)
        ready = len(matched) >= self._int("min_similar", 4) and span >= self._int(
            "min_span_seconds", 1200
        )
        return VariantDecision(
            reason="ready" if ready else "insufficient_evidence",
            similar_count=len(matched),
            span_seconds=span,
        )

    def _blocked(self, state: VariantState, now: float) -> Optional[str]:
        if state.next_review_at is not None and now < state.next_review_at:
            if state.block_reason == "failure":
                return "failure_backoff"
            if state.block_reason == "backoff" or state.review_count >= self._int("max_reviews", 4):
                return "backoff"
            return "cooldown"
        return None

    async def _score_current(
        self,
        *,
        chat_id: int,
        user_id: int,
        message_id: int,
        nickname: str,
        text: str,
        matched: list[VariantSample],
        decision: VariantDecision,
        mode: str,
        now: float,
        bio_provider: Optional[Callable[[], Awaitable[str]]],
    ) -> VariantDecision:
        token = variant_store.claim_inflight(
            self.db.db_path,
            chat_id,
            user_id,
            now=now,
            hold_seconds=self._int("inflight_hold_seconds", 30),
        )
        if token is None:
            decision.reason = "inflight"
            self._log(decision, chat_id, user_id, mode)
            return decision
        acquired = await self._try_acquire()
        if not acquired:
            variant_store.complete_inflight(self.db.db_path, chat_id, user_id, token)
            decision.reason = "backpressure"
            self._log(decision, chat_id, user_id, mode)
            return decision
        try:
            return await self._call_and_apply(
                chat_id=chat_id,
                user_id=user_id,
                message_id=message_id,
                nickname=nickname,
                text=text,
                matched=matched,
                decision=decision,
                mode=mode,
                now=now,
                token=token,
                bio_provider=bio_provider,
            )
        finally:
            self._slots.release()

    async def _call_and_apply(
        self,
        *,
        chat_id: int,
        user_id: int,
        message_id: int,
        nickname: str,
        text: str,
        matched: list[VariantSample],
        decision: VariantDecision,
        mode: str,
        now: float,
        token: str,
        bio_provider: Optional[Callable[[], Awaitable[str]]],
    ) -> VariantDecision:
        allowed, _remaining = variant_store.try_consume_budget(
            self.db.db_path,
            int(now // 3600),
            self._int("global_hourly_budget", 60),
        )
        if not allowed:
            self._finish_token(chat_id, user_id, token)
            decision.reason = "global_budget"
            self._log(decision, chat_id, user_id, mode)
            return decision
        started = time.monotonic()
        score, error = await self._invoke(nickname, text, matched, message_id, bio_provider)
        decision.elapsed_ms = int((time.monotonic() - started) * 1000)
        decision.error = error
        if not self._finish_token(chat_id, user_id, token):
            decision.reason = "stale_response"
            decision.action = "none"
            self._log(decision, chat_id, user_id, mode)
            return decision
        self._record_outcome(chat_id, user_id, now, score)
        return self._finish_decision(decision, score, mode, chat_id, user_id)

    async def _invoke(
        self,
        nickname: str,
        text: str,
        matched: list[VariantSample],
        message_id: int,
        bio_provider: Optional[Callable[[], Awaitable[str]]],
    ) -> tuple[Optional[ClefScore], Optional[str]]:
        excerpts = self._history(matched, message_id)
        skeleton = skeleton_of(text, max_chars=self._int("skeleton_chars", 96)) or ""
        current = make_excerpt(text, skeleton, limit=self._int("current_chars", 400))
        state_text = build_context_review_state(
            nickname,
            await self._bio(bio_provider),
            current,
            excerpts,
            current_limit=self._int("current_chars", 400),
        )
        try:
            return await self._score(state_text)
        except Exception as exc:
            logger.error(f"clef variant: 调用失败（fail-open）: {type(exc).__name__}")
            return None, "error"

    async def _score(self, state_text: str) -> tuple[Optional[ClefScore], Optional[str]]:
        detailed = getattr(self.client, "score_profile_detailed", None)
        questions = build_context_questions()
        if detailed is None:
            score = await self.client.score_profile(state_text, questions)
            if isinstance(score, ClefScore):
                return score, None
            return None, "unavailable"
        scored = await detailed(state_text, questions)
        if not isinstance(scored, tuple) or len(scored) != 2:
            return None, "error"
        score, error = scored
        if score is not None and not isinstance(score, ClefScore):
            return None, "error"
        if error is not None and not isinstance(error, str):
            return None, "error"
        return score, error

    def _history(self, matched: list[VariantSample], message_id: int) -> list[str]:
        previous = [sample for sample in matched if sample.message_id != message_id]
        limit = self._int("history_limit", 3)
        chosen = previous[-limit:]
        return [sample.excerpt for sample in chosen]

    async def _bio(self, bio_provider: Optional[Callable[[], Awaitable[str]]]) -> str:
        if bio_provider is None:
            return ""
        try:
            bio = await bio_provider()
        except Exception:
            return ""
        if not isinstance(bio, str):
            return ""
        return bio.strip()[:200]

    def _finish_token(self, chat_id: int, user_id: int, token: str) -> bool:
        return bool(variant_store.complete_inflight(self.db.db_path, chat_id, user_id, token))

    def _record_outcome(
        self, chat_id: int, user_id: int, now: float, score: Optional[ClefScore]
    ) -> None:
        state = variant_store.get_state(self.db.db_path, chat_id, user_id)
        state.inflight_token = None
        state.inflight_until = None
        if score is None:
            state.next_review_at = now + self._int("failure_cooldown_seconds", 900)
            state.block_reason = "failure"
            variant_store.save_state(self.db.db_path, chat_id, user_id, state)
            return
        self._reset_if_due(state, now)
        if state.window_started_at is None:
            state.window_started_at = now
        state.review_count += 1
        if state.review_count >= self._int("max_reviews", 4):
            state.next_review_at = now + self._int("backoff_seconds", 21600)
            state.block_reason = "backoff"
        else:
            state.next_review_at = now + self._int("cooldown_seconds", 3600)
            state.block_reason = "cooldown"
        variant_store.save_state(self.db.db_path, chat_id, user_id, state)

    def _reset_if_due(self, state: VariantState, now: float) -> None:
        window = self._int("window_seconds", 86400)
        expired = state.window_started_at is not None and now - state.window_started_at >= window
        cooled = state.next_review_at is None or now >= state.next_review_at
        if not cooled:
            return
        if state.review_count >= self._int("max_reviews", 4) or expired:
            state.review_count = 0
            state.window_started_at = None
            state.block_reason = None

    def _finish_decision(
        self,
        decision: VariantDecision,
        score: Optional[ClefScore],
        mode: str,
        chat_id: int,
        user_id: int,
    ) -> VariantDecision:
        action = decide_current_message(score, mode, self.threshold())
        decision.reason = action
        decision.action = action if action in {"would_ban", "ban"} else "none"
        if score is not None:
            decision.is_ad = score.is_ad
            decision.risk = score.risk_score
        state = variant_store.get_state(self.db.db_path, chat_id, user_id)
        decision.review_count = state.review_count
        decision.budget_remaining = self._remaining(state.review_count)
        self._log(decision, chat_id, user_id, mode)
        return decision

    def _remaining(self, review_count: int) -> int:
        return max(0, self._int("max_reviews", 4) - review_count)

    async def _try_acquire(self) -> bool:
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=0.01)
        except asyncio.TimeoutError:
            return False
        return True

    async def _lock_for(self, chat_id: int, user_id: int) -> asyncio.Lock:
        async with self._guard:
            if len(self._locks) > 4096:
                stale = [key for key, lock in self._locks.items() if not lock.locked()]
                for key in stale:
                    self._locks.pop(key, None)
            key = (chat_id, user_id)
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]

    def _log(self, decision: VariantDecision, chat_id: int, user_id: int, mode: str) -> None:
        if decision.reason in {"low_information", "mode_off", "service_identity"}:
            return
        fields = [
            f"mode={mode}",
            f"reason={decision.reason}",
            f"chat={chat_id}",
            f"user={user_id}",
            f"similar={decision.similar_count}",
            f"span_s={decision.span_seconds}",
            f"reviews={decision.review_count}",
            f"budget_remaining={decision.budget_remaining}",
            f"elapsed_ms={decision.elapsed_ms}",
            f"error={decision.error or '-'}",
        ]
        if decision.is_ad is not None:
            fields.append(f"is_ad={decision.is_ad:.4f}")
        if decision.risk is not None:
            fields.append(f"risk={decision.risk:.4f}")
        line = "[CLEF_VARIANT] " + " ".join(fields)
        if decision.reason == "insufficient_evidence":
            logger.debug(line)
            return
        logger.info(line)

    def _int(self, key: str, default: int) -> int:
        value = self.config.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            return default
        return value

    def _float(self, key: str, default: float) -> float:
        value = self.config.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        return float(value)
