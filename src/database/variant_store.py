"""慢变体复评的短期状态。

只保存有上限的骨架和摘录。不保存原始长消息，也不写入操作日志。
"""

from __future__ import annotations

import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass
class VariantSample:
    """一条短期样本。"""

    message_id: int
    skeleton: str
    excerpt: str
    created_at: float


@dataclass
class VariantState:
    """一个用户在一个群里的复评计数。"""

    review_count: int = 0
    window_started_at: Optional[float] = None
    next_review_at: Optional[float] = None
    block_reason: Optional[str] = None
    inflight_token: Optional[str] = None
    inflight_until: Optional[float] = None


def create_tables(cursor: sqlite3.Cursor) -> None:
    """创建变体表。已有的 clef_scored_users 不动。"""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clef_variant_samples (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            skeleton TEXT NOT NULL,
            excerpt TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (chat_id, user_id, message_id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_clef_variant_samples_created
        ON clef_variant_samples (created_at)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clef_variant_state (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            review_count INTEGER NOT NULL DEFAULT 0,
            window_started_at REAL NULL,
            next_review_at REAL NULL,
            block_reason TEXT NULL,
            inflight_token TEXT NULL,
            inflight_until REAL NULL,
            PRIMARY KEY (chat_id, user_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clef_variant_budget (
            hour_bucket INTEGER PRIMARY KEY,
            call_count INTEGER NOT NULL
        )
    """)


def _connect(db_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def _session(db_path: str) -> Iterator[sqlite3.Connection]:
    connection = _connect(db_path)
    try:
        yield connection
    finally:
        connection.close()


def add_sample(
    db_path: str,
    chat_id: int,
    user_id: int,
    message_id: int,
    skeleton: str,
    excerpt: str,
    created_at: float,
    *,
    ttl_seconds: float,
    max_samples: int,
) -> bool:
    """写入样本。同一条消息重复投递不会加行。返回是否新插入。"""
    cutoff = created_at - ttl_seconds
    with _session(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                DELETE FROM clef_variant_samples
                WHERE chat_id = ? AND user_id = ? AND created_at < ?
                """,
                (chat_id, user_id, cutoff),
            )
            before = connection.total_changes
            connection.execute(
                """
                INSERT OR IGNORE INTO clef_variant_samples
                    (chat_id, user_id, message_id, skeleton, excerpt, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (chat_id, user_id, message_id, skeleton, excerpt, created_at),
            )
            inserted = connection.total_changes > before
            connection.execute(
                """
                DELETE FROM clef_variant_samples
                WHERE chat_id = ? AND user_id = ? AND message_id NOT IN (
                    SELECT message_id FROM clef_variant_samples
                    WHERE chat_id = ? AND user_id = ?
                    ORDER BY created_at DESC, message_id DESC
                    LIMIT ?
                )
                """,
                (chat_id, user_id, chat_id, user_id, max_samples),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    return inserted


def list_samples(
    db_path: str, chat_id: int, user_id: int, *, now: float, ttl_seconds: float
) -> list[VariantSample]:
    """读取尚未过期的样本，按时间从早到晚。"""
    cutoff = now - ttl_seconds
    with _session(db_path) as connection:
        rows = connection.execute(
            """
            SELECT message_id, skeleton, excerpt, created_at
            FROM clef_variant_samples
            WHERE chat_id = ? AND user_id = ? AND created_at >= ?
            ORDER BY created_at ASC, message_id ASC
            """,
            (chat_id, user_id, cutoff),
        ).fetchall()
    return [
        VariantSample(
            message_id=int(row["message_id"]),
            skeleton=str(row["skeleton"]),
            excerpt=str(row["excerpt"]),
            created_at=float(row["created_at"]),
        )
        for row in rows
    ]


def get_state(db_path: str, chat_id: int, user_id: int) -> VariantState:
    """没有记录时返回空状态，不插入行。"""
    with _session(db_path) as connection:
        row = connection.execute(
            """
            SELECT review_count, window_started_at, next_review_at,
                   block_reason, inflight_token, inflight_until
            FROM clef_variant_state
            WHERE chat_id = ? AND user_id = ?
            """,
            (chat_id, user_id),
        ).fetchone()
    if row is None:
        return VariantState()
    return VariantState(
        review_count=int(row["review_count"] or 0),
        window_started_at=row["window_started_at"],
        next_review_at=row["next_review_at"],
        block_reason=row["block_reason"],
        inflight_token=row["inflight_token"],
        inflight_until=row["inflight_until"],
    )


def save_state(db_path: str, chat_id: int, user_id: int, state: VariantState) -> None:
    """覆盖该用户在该群的计数。"""
    with _session(db_path) as connection:
        connection.execute(
            """
            INSERT INTO clef_variant_state (
                chat_id, user_id, review_count, window_started_at, next_review_at,
                block_reason, inflight_token, inflight_until
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                review_count = excluded.review_count,
                window_started_at = excluded.window_started_at,
                next_review_at = excluded.next_review_at,
                block_reason = excluded.block_reason,
                inflight_token = excluded.inflight_token,
                inflight_until = excluded.inflight_until
            """,
            (
                chat_id,
                user_id,
                state.review_count,
                state.window_started_at,
                state.next_review_at,
                state.block_reason,
                state.inflight_token,
                state.inflight_until,
            ),
        )


def claim_inflight(
    db_path: str, chat_id: int, user_id: int, *, now: float, hold_seconds: float
) -> Optional[str]:
    """占住这个用户。已有未过期的占位时返回 None。"""
    current = get_state(db_path, chat_id, user_id)
    if current.inflight_token and current.inflight_until and current.inflight_until > now:
        return None
    token = secrets.token_hex(8)
    current.inflight_token = token
    current.inflight_until = now + hold_seconds
    save_state(db_path, chat_id, user_id, current)
    return token


def complete_inflight(db_path: str, chat_id: int, user_id: int, token: str) -> bool:
    """只有令牌仍是当前占位时才清除。过期响应因此不能改写新的一轮。"""
    with _session(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE clef_variant_state
            SET inflight_token = NULL, inflight_until = NULL
            WHERE chat_id = ? AND user_id = ? AND inflight_token = ?
            """,
            (chat_id, user_id, token),
        )
        return cursor.rowcount == 1


def force_inflight(db_path: str, chat_id: int, user_id: int, token: str, until: float) -> None:
    """测试用：把占位换成另一个令牌。"""
    current = get_state(db_path, chat_id, user_id)
    current.inflight_token = token
    current.inflight_until = until
    save_state(db_path, chat_id, user_id, current)


def try_consume_budget(db_path: str, hour_bucket: int, limit: int) -> tuple[bool, int]:
    """全局小时预算。成功时返回剩余次数，失败时不增加计数。"""
    with _session(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute(
                "SELECT call_count FROM clef_variant_budget WHERE hour_bucket = ?",
                (hour_bucket,),
            ).fetchone()
            count = int(row["call_count"]) if row else 0
            if count >= limit:
                connection.execute("ROLLBACK")
                return False, 0
            new_count = count + 1
            connection.execute(
                """
                INSERT INTO clef_variant_budget (hour_bucket, call_count)
                VALUES (?, ?)
                ON CONFLICT(hour_bucket) DO UPDATE SET call_count = excluded.call_count
                """,
                (hour_bucket, new_count),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    return True, max(0, limit - new_count)


def clear_user(db_path: str, chat_id: int, user_id: int) -> None:
    """清掉一个用户在一个群的变体窗口，不动 clef_scored_users。"""
    with _session(db_path) as connection:
        connection.execute(
            "DELETE FROM clef_variant_samples WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        connection.execute(
            "DELETE FROM clef_variant_state WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )


def cleanup(
    db_path: str, *, now: float, ttl_seconds: float, budget_hours: int = 48
) -> dict[str, int]:
    """删除过期样本和已经结束的计数。不删除 clef_scored_users。"""
    cutoff = now - ttl_seconds
    old_hour = int(now // 3600) - budget_hours
    with _session(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            samples = connection.execute(
                "DELETE FROM clef_variant_samples WHERE created_at < ?",
                (cutoff,),
            ).rowcount
            budgets = connection.execute(
                "DELETE FROM clef_variant_budget WHERE hour_bucket < ?",
                (old_hour,),
            ).rowcount
            states = connection.execute(
                """
                DELETE FROM clef_variant_state
                WHERE (next_review_at IS NULL OR next_review_at < ?)
                  AND NOT EXISTS (
                    SELECT 1 FROM clef_variant_samples
                    WHERE clef_variant_samples.chat_id = clef_variant_state.chat_id
                      AND clef_variant_samples.user_id = clef_variant_state.user_id
                  )
                """,
                (now,),
            ).rowcount
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    return {"samples": samples or 0, "budgets": budgets or 0, "states": states or 0}
