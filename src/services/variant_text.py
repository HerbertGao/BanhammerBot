"""短广告变体的保守骨架。

只回答两段文字是否近似，不决定删除或封禁。
骨架会去掉表情、格式字符和少量夹在字间的分隔符，因此不能还原原文。
哈希更不能还原，也不能拿去和另一条变体比较，所以调用方若要复评，
只能短期保存有长度上限的骨架本身。
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

# 只去掉常见的“拆字”分隔符。其余标点保留，避免把代码、报价和普通句子压成同一串。
_SEPARATORS = frozenset(
    " \t\r\n" "._~～·•‧∙⋅,，、。．" "*#@%&=:/\\|-—–" "()[]{}<>「」『』“”\"'`" "：；;！？!?…" "+＋"
)
_SANDWICH = re.compile(r"(\d)[a-z](\d)")
_DIGIT_RUN = re.compile(r"\d{3,}")
_CJK = re.compile(r"[\u3400-\u9fff]")
_FENCE = ("<<<", ">>>")


def _drop(char: str) -> bool:
    """表情、格式字符和空白。字母、数字和汉字保留。"""
    category = unicodedata.category(char)
    if category[0] in {"C", "M", "S", "Z"}:
        return True
    return char in _SEPARATORS


def _collapse_inserted_letters(text: str) -> str:
    """只去掉夹在数字中间的单个拉丁字母，例如 5a000。"""
    current = text
    for _ in range(8):
        updated = _SANDWICH.sub(r"\1\2", current)
        if updated == current:
            return current
        current = updated
    return current


def skeleton_of(text: str, *, max_chars: int = 96) -> str | None:
    """返回可比较的短骨架。信息量不够或过长时返回 None。"""
    if not isinstance(text, str):
        return None
    folded = unicodedata.normalize("NFKC", text).casefold()
    kept = "".join(char for char in folded if not _drop(char))
    kept = _collapse_inserted_letters(kept)
    if not kept or len(kept) < 6 or len(kept) > max_chars:
        return None
    cjk = len(_CJK.findall(kept))
    runs = _DIGIT_RUN.findall(kept)
    has_amount = cjk >= 2 and any(len(run) >= 3 for run in runs)
    if cjk < 8 and not has_amount:
        return None
    return kept


def make_excerpt(raw: str, skeleton: str, *, limit: int = 80) -> str:
    """尽量保留骨架所在的那一段，避免表情前缀把正文截掉。"""
    compact = " ".join((raw or "").split())
    if skeleton and skeleton in compact:
        start = max(0, compact.find(skeleton) - 8)
        return compact[start : start + limit]
    if skeleton:
        return skeleton[:limit]
    return compact[:limit]


def shield_untrusted(text: str) -> str:
    """拆掉围栏标记，避免摘录提前结束数据区。"""
    cleaned = text or ""
    cleaned = cleaned.replace(_FENCE[0], "‹‹‹").replace(_FENCE[1], "›››")
    return cleaned


def same_variant(
    left: str,
    right: str,
    *,
    ratio: float = 0.90,
    plain_ratio: float = 0.96,
    min_length_ratio: float = 0.75,
    max_chars: int = 96,
) -> bool:
    """两段文字是否像同一句的轻度变体。金额不同则否。"""
    left_skeleton = skeleton_of(left, max_chars=max_chars)
    right_skeleton = skeleton_of(right, max_chars=max_chars)
    if left_skeleton is None or right_skeleton is None:
        return False
    short, long = sorted((len(left_skeleton), len(right_skeleton)))
    if long == 0 or short / long < min_length_ratio:
        return False
    left_runs = Counter(_DIGIT_RUN.findall(left_skeleton))
    right_runs = Counter(_DIGIT_RUN.findall(right_skeleton))
    if left_runs != right_runs:
        return False
    needed = plain_ratio if not left_runs else ratio
    return SequenceMatcher(None, left_skeleton, right_skeleton).ratio() >= needed
